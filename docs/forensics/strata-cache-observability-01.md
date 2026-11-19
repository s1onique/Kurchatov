# Strata cache decision observability (ACT-KURCHATOV-STRATA-CACHE-OBS-01)

**Branch:** `act/strata-cache-observability-01`
**Base:** `3e1642161198c50ff1abed4046f4e4f476099dbb` (`main`, "Merge the engine work for 0.1.45-poly.10")
**Engine:** Strata (Qwen3.8-Flash-Next), `src/program/generate.cpp`
**Scope:** observability only. No kernel, no cache policy, no quantization, no `strata-poly`.

## What this ACT is

The engine can tell you *what* it reused (`RESUME N`, `REUSED N`, "conversation cache: restored N tokens
(live|checkpoint)") but not *why* it reused that and not something deeper. When a request rereads 30 000 of its
32 000 prompt tokens, the log does not say whether the deep checkpoint was gone, was refused because the picture
changed, was refused because the steering mode differed, or was never there.

This ACT adds an opt-in diagnostic (`STRATA_CACHE_DIAG=1`) that answers that question from the authoritative
decision boundary: one structured event per request, naming the source that was mounted, the prefix that was
actually reused, and the typed reason the other candidates were refused.

Nothing about inference changes: the selection, the checkpoints, the retention and the tokens are the same with
the switch on and off.

## The production decision map

The request path in `src/program/generate.cpp` (the serve loop) resolves the reusable prefix from four sources.
Each is decided in a different place, and each has its own rejection rules.

| # | Source | Where it is decided | What can refuse it |
|---|---|---|---|
| 1 | **Live session** (the running state of the last request) | `generate.cpp` ~11983-11992, the `starts_with(live, live_imgs)` test | tokens differ; pictures differ; `--prompt-cache 0`; another steering mode |
| 2 | **Active checkpoint chain** (`checks`) | the same block, the loop over `checks` | as above; the checkpoint is past `resume` (its cells were rewritten) |
| 3 | **Parked conversation / parked checkpoint** | `include/strata/core/conversation_cache.hpp`, `ConversationCache::best()` -> `conversation_prefix()` | tokens differ; pictures differ; another steering mode (`e.cvec != cvec`); the entry was evicted or superseded |
| 4 | **Batch slot** | `generate.cpp` ~11995-12010 (`slot_source`), the `--batch` path | the slot is busy, tainted (#879), or in another steering mode |

Then the engine resolves the winner:

- the parked side wins when it is deeper than the live side (`parked.tokens > max(resume, slot_tokens)`);
- a *borrow* (a checkpoint inside a parked conversation) restores only the prefix and leaves the donor parked
  (`ConversationCache::borrows()`);
- a taken parked conversation is restored whole (`conversation_snapshot_restore`), then the checkpoints that are
  off this prompt's path are pruned (`off_path()` in `generate.cpp`).

The reusable prefix is `resume`, and it is final just before the engine zeroes the session (`resume == 0`) or
mounts the chosen checkpoint (`checkpoint_restore`). That is the boundary this ACT instruments.

### What the log already explained

| Already in the log | Where |
|---|---|
| the reused token count | `RESUME N` / `REUSED N` (stdout) |
| the parked conversation's state | "conversation cache: restored N tokens (live\|checkpoint) in X ms" (stderr) |
| a borrow | "borrowed N tokens from a parked conversation, which stays parked" |
| a picture that is not the same | "the state at N tokens has this prompt's tokens but picture K is not the same as when it was saved" (#2228) |
| the parked count, bytes, evictions | "parked=P bytes=B evictions=E" |
| a refused park | "skip parking (snapshot N MiB exceeds available budget)" / "(physical RAM admission ...)" |
| the server's view | `serve/server.py`'s `ConvCacheLog` reads those lines into `/metrics` |

### What needed new instrumentation

| Not explained before | Now |
|---|---|
| which source was mounted, in one field | `selected_source` |
| how far the tokens actually agreed (not how long a checkpoint was) | `longest_common_prefix_tokens`, `first_mismatch_position` |
| why the deepest candidate was refused | `rejection_reason` (typed) |
| how many candidates were examined | `candidate_count`, `max_candidate_prefix_tokens` |
| a checkpoint that left the chain, and why | a separate `checkpoint_evict` event |
| a park that was refused | a separate `park_refused` event |
| a parked conversation evicted to admit another | a separate `park_evict` event |

## The event schema

One line per event, on stderr, in a fixed `key=value` form:

```
STRATA_CACHE_DIAG event=decision request_seq=7 prompt_tokens=1200 selected_source=active_checkpoint \
  selected_prefix_tokens=900 candidate_count=4 max_candidate_prefix_tokens=1024 \
  longest_common_prefix_tokens=900 first_mismatch_position=-1 rejection_reason=EXACT_MATCH \
  cache_parked_entries=2 cache_parked_bytes=3145728 cache_evictions_total=1 \
  subject_tokens=0 subject_serial=-1
```

| Field | Meaning |
|---|---|
| `request_seq` | opaque, process-local correlation id (a counter, one per request) |
| `prompt_tokens` | the request's actual input token count |
| `selected_source` | `live`, `active_checkpoint`, `parked_live`, `parked_checkpoint`, `slot` or `none` |
| `selected_prefix_tokens` | the reusable prefix the engine actually used (0 when none) |
| `candidate_count` | the number of candidates examined |
| `max_candidate_prefix_tokens` | the longest candidate's length |
| `longest_common_prefix_tokens` | the **actual** matching token prefix with the prompt |
| `first_mismatch_position` | the position of the first differing token (-1 when they agree throughout) |
| `rejection_reason` | a typed reason (below), or `UNKNOWN`: the **selected** source's own reason |
| `deeper_rejection_reason` | the **deeper refused** candidate's reason, or `UNKNOWN`: WHY the request could not reuse more than it did. `UNKNOWN` when no deeper candidate was refused |
| `deeper_candidate_tokens` | the deeper refused candidate's length (0 when there was none) |
| `cache_parked_entries` | the number of parked conversations |
| `cache_parked_bytes` | their retained footprint |
| `cache_evictions_total` | the observed eviction counter |
| `subject_tokens`, `subject_serial` | the secondary event's own subject (a checkpoint's length, a conversation's id) |

### The typed reasons

| Reason | Meaning |
|---|---|
| `EXACT_MATCH` | the candidate matched the prompt exactly and was used |
| `TOKEN_MISMATCH` | the candidate's tokens differ from the prompt's |
| `IMAGE_MISMATCH` | the tokens agree but the pictures are not the same |
| `STEERING_MISMATCH` | the candidate was saved with another steering (control-vector) mode |
| `ABSENT` | there was no candidate at all |
| `INELIGIBLE` | a candidate was there but not eligible (e.g. it would consume the last prompt token) |
| `EVICTED` | the candidate was **observed** to be evicted by the retention policy |
| `RETENTION_REMOVED` | the candidate left the active chain because this request rewrote its cells |
| `CACHE_DISABLED` | the cache is off for this request |
| `BUDGET_REFUSED` | a memory-budget or slot-limit admission refusal |
| `SUPERSEDED` | the candidate was dropped because this request supersedes it |
| `BORROWED` | the candidate is used through a borrow (the donor stays parked) |
| `SLOT_SOURCE` | a batch slot gave back the conversation |
| `UNKNOWN` | no evidence for a narrower reason (the honest default) |

### The rules the diagnostic keeps

- **A partial longest common prefix is never a usable prefix.** `longest_common_prefix_tokens` is the token
  comparison, not a checkpoint's length. A 5 000-token checkpoint whose tokens agree for 100 tokens and then
  differ reports 100, and `selected_prefix_tokens` stays 0 for it.
- **An absent checkpoint is not called "evicted".** `EVICTED` is reported only where the engine observed the
  removal (the RAM admission gate's `evict_oldest()`). A checkpoint that was never in the chain is `ABSENT`.
- **No user data.** The fields are counts, positions and fixed words. No prompt text, no token ids, no image
  content, no tool schemas, no API keys. The engine never writes a token id into an event; the server's reader
  keeps only the fields above.
- **Bounded output.** One decision event per request, plus one line per checkpoint that leaves the chain, per
  refused park and per eviction-to-admit. The server keeps the last 64 events and counts them all.

## What was changed

| File | Change |
|---|---|
| `include/strata/program/cache_diag.hpp` | **new.** The event, the reasons, the switch (`STRATA_CACHE_DIAG=1`, default off), the candidate analysis (`analyse()`, `common_prefix()`) and the writer. |
| `include/strata/core/conversation_cache.hpp` | `ConversationCache::candidates()`: the same walk as `best()`, with the reason each candidate was or was not usable. `best()` is untouched. |
| `src/program/generate.cpp` | the collector, the candidate analysis at the three decision sites, the decision resolution after `resume` is final, and the three secondary events. The selection code is untouched. |
| `serve/server.py` | `ConvCacheLog` reads the diagnostic lines; `/metrics`' conversation-cache card carries the last events and their counts. |
| `src/program/cache_diag_test.cpp` | **new.** The scenarios, against the real `ConversationCache`. |
| `src/program/cache_diag_engine_test.cpp` | **new.** The engine's request-loop wiring, transcribed from `generate.cpp`, over the same cache. |
| `src/program/cache_diag_roundtrip.cpp` | **new.** The engine's writer on its own, so the server's reader is checked against the real writer. |
| `tools/test_cache_diag_log.py` | **new.** The server's parsing of the events, and the round trip against the C++ writer. |
| `CMakeLists.txt` | the two new tests and the round-trip program, under `STRATA_BUILD_CONVERSATION_TESTS`. |

### Why the diagnostics cost nothing when they are off

- `cache_diag::enabled()` is one `static const bool`, read once from the environment.
- `cdiag.on` is that flag; every diagnostic block is behind `if (cdiag.on)`.
- `CacheDiagCollector::reset()` returns immediately when off, so no request id is even spent.
- `cdiag_consider()` returns immediately when off, so no extra token comparison happens.
- `ConversationCache::candidates()` is only called when `cdiag.on`.
- Nothing is added to the per-token fast path: the diagnostics live in the request loop, once per request.

## Evidence

### The host-only tests (this machine: macOS 23.6.0, arm64, clang 15, no CUDA toolkit, no GPU)

Built and run directly with the compiler (the CMake configure fetches llama.cpp and was not usable here; the
sources are the repository's, the flags are the project's C++20):

```
$ clang++ -std=c++20 -O2 -Iinclude src/program/cache_diag_test.cpp -o build-host/cache_diag_test
$ ./build-host/cache_diag_test
cache_diag_test
cache_diag_test: 77 checks passed

$ clang++ -std=c++20 -O2 -Iinclude src/program/cache_diag_engine_test.cpp -o build-host/cache_diag_engine_test
$ ./build-host/cache_diag_engine_test
cache_diag_engine_test
cache_diag_engine_test: 74 checks passed

$ clang++ -std=c++20 -O2 -Iinclude src/core/conversation_cache_test.cpp -o build-host/conversation_cache_test
$ ./build-host/conversation_cache_test
conversation_cache_test: 4772 checks passed

$ clang++ -std=c++20 -O2 -Iinclude src/program/conv_cache_test.cpp -o build-host/conv_cache_test
$ ./build-host/conv_cache_test
PASS

$ python3 tools/test_cache_diag_log.py
.......
Ran 7 tests in 0.412s

OK
```

The existing `conversation_cache_test` (4 772 checks) and `conv_cache_test` are unchanged by this ACT: they pass
byte for byte as before.

### The round trip, observed

The engine's writer and the server's reader were run against each other (the program
`src/program/cache_diag_roundtrip.cpp`, built from the repository's own header):

```
$ ./build-host/cache_diag_roundtrip        # the switch unset
enabled=0
(no output on stderr)

$ STRATA_CACHE_DIAG=1 ./build-host/cache_diag_roundtrip
enabled=1
STRATA_CACHE_DIAG event=decision request_seq=1 prompt_tokens=100 selected_source=live selected_prefix_tokens=60 candidate_count=2 max_candidate_prefix_tokens=60 longest_common_prefix_tokens=60 first_mismatch_position=-1 rejection_reason=EXACT_MATCH cache_parked_entries=0 cache_parked_bytes=0 cache_evictions_total=0 subject_tokens=0 subject_serial=0
```

and the server's reader parsed that line into:

```
{'event': 'decision', 'request_seq': 1, 'prompt_tokens': 100, 'selected_source': 'live',
 'selected_prefix_tokens': 60, 'candidate_count': 2, 'max_candidate_prefix_tokens': 60,
 'longest_common_prefix_tokens': 60, 'first_mismatch_position': -1,
 'rejection_reason': 'EXACT_MATCH', 'cache_parked_entries': 0, 'cache_parked_bytes': 0,
 'cache_evictions_total': 0}
```

This is what `tools/test_cache_diag_log.py`'s "the engine writes what the reader reads" checks.

### What the new tests cover

| Scenario | Test |
|---|---|
| 1. append-only continuation with deep reuse | `cache_diag_test` case 1, `cache_diag_engine_test` "the live session" / "an active checkpoint" |
| 2. a mutation near the beginning | `cache_diag_test` case 2, `cache_diag_engine_test` "a mutation near the beginning" |
| 3. a mutation between two checkpoints | `cache_diag_test` case 3, `cache_diag_engine_test` "a mutation between two checkpoints" |
| 4. an image identity mismatch | `cache_diag_test` case 4, `cache_diag_engine_test` "the image identity does not match" |
| 5. an incompatible steering mode | `cache_diag_test` case 5, `cache_diag_engine_test` "the steering mode does not match" |
| 6. alternating conversations with a parked-state restoration | `cache_diag_test` case 6 |
| 7. a checkpoint eviction and a memory-budget refusal | `cache_diag_test` case 7 |
| 8. diagnostic disabled/enabled parity | `cache_diag_test` case 8, `cache_diag_engine_test` "the switch OFF" |
| a borrow | `cache_diag_engine_test` "a borrow" |
| the cache disabled | `cache_diag_engine_test` "the cache is off for this request" |
| no user data | `cache_diag_test` "the event carries no user data", `cache_diag_engine_test` "the events carry no user data", `tools/test_cache_diag_log.py` "test_no_user_data" |
| the writer and the reader agree | `tools/test_cache_diag_log.py` "the engine writes what the reader reads" (with `src/program/cache_diag_roundtrip.cpp`) |
| the secondary events (a supersession, a park refusal, a checkpoint that left the chain) | `cache_diag_engine_test` "the secondary events" |

### What was NOT executed, and why

| Item | Status | Reason |
|---|---|---|
| `CUDA` build of `src/program/generate.cpp` | **NOT_EXECUTED** | this machine is macOS (arm64) with no CUDA toolkit (`nvcc` not found) and no NVIDIA GPU (`nvidia-smi` not found) |
| `HIP` build of `src/program/generate.cpp` | **NOT_EXECUTED** | no ROCm toolchain here |
| `SYCL` build | **NOT_EXECUTED** | no `icpx` here |
| `P40_RUNTIME` | **NOT_EXECUTED** | no P40 (no GPU at all) and no exclusive test window |
| `tools/conversation_cache_parity.py` | **NOT_EXECUTED** | it loads a real model on a GPU; none here |
| `tools/conversation_cache_http_smoke.py` | **NOT_EXECUTED** | it is destructive to the cache state and needs an exclusive, idle instance with a GPU; neither exists here, and the deployed service must not be touched |
| the full `ctest` suite | **NOT_EXECUTED** | the CMake configure fetches llama.cpp (network, ~4 min) and needs the CUDA tree for the engine targets; the host-only conversation tests were built and run directly instead |

### How the modified compilation units were checked without CUDA

`src/program/generate.cpp` cannot be compiled on this machine (no `nvcc`, no CUDA headers). Its diagnostic
blocks were therefore checked two ways:

1. **The engine-side wiring is transcribed and compiled.** `src/program/cache_diag_engine_test.cpp` contains the
   collector, the candidate analysis, the parked-side walk and the decision resolution as they appear in
   `generate.cpp`, over the real `ConversationCache` and the real `cache_diag.hpp`. It compiles and runs (74
   checks). Any type or scope error in those blocks would fail that build.
2. **The blocks that `generate.cpp` adds are syntactically self-contained.** Every added block is an
   `if (cdiag.on) { ... }` around statements that use only `cdiag`, `conversations`, `live`, `checks`, `n` and
   `strata::program::cache_diag::*` - all in scope at their sites (the collector is declared at line 8 796, the
   request's `n` at 11 832, and the park sites follow the collector). The three secondary events use the same
   `CacheDiagEvent` type the compiled test uses.

**This is a weaker guarantee than a CUDA build.** A CUDA build is still required before this ACT is merged.

## Known limitations

1. **No GPU run.** The diagnostic's output has not been seen from a real engine on real hardware. The engine
   path is exercised by the transcribed test, not by the engine itself.
2. **A batch slot is reported as `selected_source=slot`** (ACT-02). Before ACT-02 a slot's conversation was
   reported as `active_checkpoint` with the reason `SLOT_SOURCE`, which did not describe the actual selection:
   a slot is not one of the conversation cache's own sources. It now has its own source name, and the slot's
   candidates are examined by the diagnostic too (so the event can name them).
3. **The steering mismatch of the parked side is reported per candidate.** `ConversationCache::best()` skips a
   whole entry of another mode, so the candidates list reports its live state and its checkpoints with
   `cvec_mismatch` set. They were not candidates for the decision; they are reported so the reason can be named.
4. **The `EVICTED` reason covers the RAM admission gate.** The slot-limit eviction inside `make_room()` is
   counted in `cache_evictions_total` but does not get its own event; the counter carries it.
5. **`SUPERSEDED` counts the parked conversations, not the checkpoints.** `ConversationCache::drop_superseded()`
   removes a parked conversation because the outgoing chain holds its deepest checkpoint; the event reports how
   many went. The individual conversations are not named (the cache does not expose their identities here).
6. **The events are on stderr.** The server reads them from the engine's log file. A deployment that discards
   the log loses them; `/metrics` keeps the last 64.
7. **The server's event counts are not always comprehensive (ACT-02).** The reader's window is 1 MiB per poll.
   When more than that arrives between two polls, the older lines are passed over. Before ACT-02 this was
   silent; now the reader counts the passed-over events (`diag_lost`) and flags the truncation
   (`diag_truncated`), and the `/metrics` card carries both (`diagnostic_lost`, `diagnostic_truncated`). The
   counts are comprehensive only when `diagnostic_truncated` is false.

## Reproducing

```bash
# the diagnostics on (the engine writes one line per request to stderr)
STRATA_CACHE_DIAG=1 ./strata --serve ...

# the diagnostics off (the default): nothing changes
./strata --serve ...

# the server's view
curl -s http://127.0.0.1:8081/metrics | python3 -m json.tool | grep -A40 diagnostics
```

## What this ACT deliberately does not do

- It does not optimize the cache, and it does not touch the 14 t/s problem.
- It does not change the checkpoint retention, the eviction order or the cache matching.
- It does not change `strata-poly`.
- It does not change the default path: with the switch unset the engine's behaviour is the release's.
