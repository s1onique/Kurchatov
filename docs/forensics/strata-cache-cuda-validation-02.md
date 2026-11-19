# Strata cache decision observability: the ACT-02 validation (ACT-KURCHATOV-STRATA-CACHE-CUDA-02)

**Branch:** `act/strata-cache-cuda-validation-02`
**Parent:** `d217d783c6d9ae133277b2edf1edaa1cb835a6d2` (`act/strata-cache-observability-01`)
**Scope:** Phase 1 (entry and source review) and Phase 2 (reproduce and fix the observability defects) only.

This document records what ACT-02 did in its first two phases. Phases 3 to 5 (the native CUDA 12 build, the test
parity on the GPU and the P40 runtime window) are **not** part of this run and are listed as NOT_EXECUTED below.

## Phase 1 - entry and source review

### Repository identity and ancestry

```
$ git remote -v
origin  git@github.com:s1onique/Kurchatov.git (fetch)
origin  git@github.com:s1onique/Kurchatov.git (push)

$ git status --porcelain=v1 -b
## act/strata-cache-cuda-validation-02     (clean at the start)

$ git log --oneline -n 2
d217d783 serve: the conversation cache's decision observability (STRATA_CACHE_DIAG=1)
3e164216 Merge the engine work for 0.1.45-poly.10

$ git merge-base --is-ancestor d217d783c6d9ae133277b2edf1edaa1cb835a6d2 HEAD && echo ANCESTOR_OK
ANCESTOR_OK
```

The repository is `s1onique/Kurchatov`. The branch `act/strata-cache-cuda-validation-02` was branched from the
required parent `d217d783c6d9ae133277b2edf1edaa1cb835a6d2`, which is the ACT-01 commit. The working tree was
clean before the first edit.

### The production diffs, read

The ACT-01 changeset is 11 files, 2201 insertions, 10 deletions:

| File | Change |
|---|---|
| `include/strata/program/cache_diag.hpp` | new: the event, the typed reasons, the switch, `analyse()`, `common_prefix()`, the writer |
| `include/strata/core/conversation_cache.hpp` | `ConversationCache::candidates()`: the same walk as `best()`, with each candidate's reason. `best()` untouched |
| `src/program/generate.cpp` | the collector, the candidate analysis at the decision sites, the decision resolution, the secondary events |
| `serve/server.py` | `ConvCacheLog` reads the lines; the `/metrics` card carries the events and their counts |
| `src/program/cache_diag_test.cpp`, `src/program/cache_diag_engine_test.cpp`, `src/program/cache_diag_roundtrip.cpp` | the host-only tests |
| `tools/test_cache_diag_log.py` | the server's parsing and the writer/reader round trip |
| `CMakeLists.txt`, `docs/DETAILS.md`, `docs/forensics/strata-cache-observability-01.md` | the build, the documentation |

The lifetime, the pointer validity and the disabled-path overhead were checked in the source:

- **Lifetime.** `cache_diag::Sink::instance()` is a function-local static: it lives for the whole run. `Writer`
  holds a `std::FILE*` (stderr) and flushes after every line. The event is a value (`CacheDiagEvent`), built and
  written inside the request loop; nothing is kept after `record()` returns.
- **Candidate pointer validity.** `CacheDiagCollector::Entry` holds only counts and positions - no pointer to a
  candidate. `cdiag_consider()` takes `const std::vector<int32_t>&` and reads it inside the call, so no pointer
  outlives the vector it points into. The parked side's `ConversationCache::Candidate::ids` points into the
  cache's own `entries_`, and the walk that uses it (`candidates()`) does not mutate the cache; the cache is
  mutated later (`take()`, `put()`), after the diagnostic's parked walk.
- **Disabled-path overhead.** `cache_diag::enabled()` is one `static const bool` read once from the environment.
  `cdiag.on` is that flag. Every diagnostic block is behind `if (cdiag.on)`; `reset()` returns immediately when
  off (no request id is spent); `cdiag_consider()` returns immediately when off; `ConversationCache::candidates()`
  is called only when `cdiag.on`. Nothing was added to the per-token fast path.
- **Emission timing.** The decision event is written after `resume` is final (after the parked restore, the
  borrow, the slot restore and the steering update) and before the engine zeroes the session or mounts the
  chosen checkpoint. The secondary events are written at the sites where the removal is **observed** (the park
  refusal, the RAM admission's eviction, the supersession, the off-path pruning).

### The findings of the review that this ACT fixes

Two of the review's points are confirmed defects in the production code, and one is a semantic gap:

1. **A successful shallow reuse concealed the deeper rejection.** `CacheDiagEvent` had ONE reason field. The
## Phase 2 - the counterexamples, reproduced before the fix

Each counterexample was reproduced against the production code first (RED), then fixed, then checked again
(GREEN). The C++ reproductions compile against the repository's own header
(`include/strata/program/cache_diag.hpp`), so the regression test and the production writer cannot drift apart.

### R1 - the deeper rejection is concealed

**RED** (the production event has no field for it):

```
$ clang++ -std=c++20 -O2 -Iinclude src/program/cache_diag_regress_test.cpp -o build-host/cache_diag_regress_test
src/program/cache_diag_regress_test.cpp:304:17: error: no member named 'deeper_rejection_reason' in
    'strata::program::cache_diag::CacheDiagEvent'; did you mean 'rejection_reason'?
src/program/cache_diag_regress_test.cpp:306:17: error: no member named 'deeper_candidate_tokens' in
    'strata::program::cache_diag::CacheDiagEvent'
```

**The fix.** The event gained two fields:

- `deeper_rejection_reason` - the reason the **deeper refused** candidate was refused (`UNKNOWN` when there was
  no deeper refusal, so the field never carries a stale reason);
- `deeper_candidate_tokens` - that candidate's length (0 when there was none), so the event says how much was
  NOT reused.

The collector tracks the longest candidate that was **not usable** (`deeper_tokens` / `deeper_reason` in
`CacheDiagCollector::add()`), which is the candidate the request wanted but could not have. `rejection_reason`
keeps its old meaning (the selected source's own reason), so nothing that read the old field changes.

**GREEN:**

```
$ ./build-host/cache_diag_regress_test
cache_diag_regress_test
cache_diag_regress_test: 29 checks passed
```

The writer's line now carries both:

```
... rejection_reason=EXACT_MATCH deeper_rejection_reason=IMAGE_MISMATCH deeper_candidate_tokens=6 ...
```

### R2 - the batch slot was not named

**RED:**

```
src/program/cache_diag_regress_test.cpp:211:61: error: no member named 'slot' in
    'strata::program::cache_diag::Source'
```

**The fix.** `Source` gained a `slot` value, and `source_name()` maps it to `"slot"`. The decision resolution
reports `Source::slot` when a batch slot gave the conversation back (it is not one of the cache's own sources),
and the slot's candidates are now added to the collector, so they are counted in `candidate_count`.

The engine's ORDER is unchanged: the parked side still wins over the slot (`parked_used` is checked first), the
slot still wins over the live session and the active chain. Only the **name** of the source changed, and only the
diagnostic's own candidate list grew. `slot_source` was already the engine's own variable; nothing in the
selection was touched.

**GREEN:** the R2, R2b, R2c and R2d cases in `cache_diag_regress_test` (the slot's own state, the slot's
checkpoint, the parked side still winning, and the switch off doing no work).

### R3 - the reader lost records silently

**RED:**

```
$ python3 tools/test_cache_diag_log.py
FAIL: test_more_than_the_read_window_between_two_polls_loses_records
AssertionError: False is not true : the reader says that records were lost between the polls
```

**The fix.** `ConvCacheLog` now detects the truncation:

- `diag_truncated` - whether the 1 MiB window was truncated at least once;
- `diag_lost` - how many diagnostic events were passed over (the passed-over region is scanned, bounded by the
## What was changed in ACT-02

| File | Change |
|---|---|
| `include/strata/program/cache_diag.hpp` | `Source::slot`; the event's `deeper_rejection_reason` and `deeper_candidate_tokens`; the writer emits them |
| `src/program/generate.cpp` | the collector tracks the deeper refused candidate; the decision resolution reports `Source::slot`; the slot's candidates are added to the collector |
| `serve/server.py` | the reader parses the two new fields and detects the truncation (`diag_lost`, `diag_truncated`, `diag_bytes_lost`); the `/metrics` card carries the loss signal |
| `src/program/cache_diag_regress_test.cpp` | **new.** the three counterexamples as regression tests (29 checks) |
| `src/program/cache_diag_engine_test.cpp` | the collector transcription follows the production one; the deeper-refusal case is covered (74 -> 81 checks) |
| `src/program/cache_diag_test.cpp` | the deeper-refusal scenario; the test renders the event with the **production** `Writer` instead of a copy of its format (77 -> 82 checks) |
| `tools/test_cache_diag_log.py` | the new fields, the loss detection and the view's loss signal (7 -> 10 tests) |
| `CMakeLists.txt` | the new regression test, under `STRATA_BUILD_CONVERSATION_TESTS` |
| `docs/DETAILS.md`, `docs/forensics/strata-cache-observability-01.md` | the new fields, the `slot` source and the loss signal |

**What it leaves alone.** The checkpoint selection, the eviction, the retention, the matching rules, the
checkpoint policy, the kernels, the quantization, `strata-poly` and the default path (the switch unset is still
the release's behaviour) are untouched. The event's `rejection_reason` keeps its old meaning.

## Evidence

### The host-only tests (this machine: macOS, arm64, clang, no CUDA toolkit, no GPU)

```
$ clang++ -std=c++20 -O2 -Iinclude src/program/cache_diag_test.cpp -o build-host/cache_diag_test
$ ./build-host/cache_diag_test
cache_diag_test: 82 checks passed

$ clang++ -std=c++20 -O2 -Iinclude src/program/cache_diag_engine_test.cpp -o build-host/cache_diag_engine_test
$ ./build-host/cache_diag_engine_test
cache_diag_engine_test: 81 checks passed

$ clang++ -std=c++20 -O2 -Iinclude src/program/cache_diag_regress_test.cpp -o build-host/cache_diag_regress_test
$ ./build-host/cache_diag_regress_test
cache_diag_regress_test: 29 checks passed

$ clang++ -std=c++20 -O2 -Iinclude src/core/conversation_cache_test.cpp -o build-host/conversation_cache_test
$ ./build-host/conversation_cache_test
conversation_cache_test: 4772 checks passed

$ clang++ -std=c++20 -O2 -Iinclude src/program/conv_cache_test.cpp -o build-host/conv_cache_test
$ ./build-host/conv_cache_test
PASS

$ python3 tools/test_cache_diag_log.py
..........
Ran 10 tests in 0.400s

OK
```

`conversation_cache_test` (4 772 checks) and `conv_cache_test` are unchanged by ACT-02: they pass as before.

### NOT EXECUTED in this run

| Item | Status | Reason |
|---|---|---|
| the `CUDA` build of `src/program/generate.cpp` | **NOT_EXECUTED** | Phase 3. This machine is macOS (arm64) with no CUDA toolkit and no NVIDIA GPU. The ACT-02 changes to `generate.cpp` are inside the diagnostic blocks only, but they have NOT been through `nvcc`. |
| the `HIP` and `SYCL` builds | **NOT_EXECUTED** | no ROCm or `icpx` here |
| `P40_RUNTIME` | **NOT_EXECUTED** | no GPU and no exclusive test window; the deployed service was not touched |
| `tools/conversation_cache_parity.py`, `tools/conversation_cache_http_smoke.py` | **NOT_EXECUTED** | they need a GPU; the smoke test is destructive to the cache state |
| `serve/test_monitor.py`, `serve/test_server.py` | **NOT_EXECUTED** | `jinja2` is not installed in this environment. This is a pre-existing limitation: the same import error occurs at the base commit `d217d783`. The reader and the view are checked by `tools/test_cache_diag_log.py`, which takes them from `serve/server.py` by source and needs none of the server's other imports. |

**The ACT-02 changes to `generate.cpp` have not been through a CUDA compiler.** The changes are: three
assignments and one `if` block inside the diagnostic's own blocks. The types they use (`Source::slot`,
`Reason`, `CacheDiagEvent::deeper_rejection_reason`, `CacheDiagEvent::deeper_candidate_tokens`) are the
production header's own, and the same header compiles in the host tests. A CUDA build is still required.

## What ACT-02 deliberately does not do

- It does not change the cache's selection, eviction, retention or matching.
- It does not change `strata-poly`, the kernels or the quantization.
- It does not change the default path: with `STRATA_CACHE_DIAG` unset the engine's behaviour is the release's.
- It does not touch the deployed inference service, the installed engine, the model files, the Ansible
  configuration or the recovery artifacts.

  window's own size, so the read stays bounded);
- `diag_bytes_lost` - how many bytes of the log were passed over.

The `/metrics` card carries `diagnostic_lost` and `diagnostic_truncated`, so the counts are presented as
comprehensive only when `diagnostic_truncated` is false. The counts themselves are unchanged: they still count
what was read. What changed is that the loss is **detectable** instead of silent.

**GREEN:**

```
$ python3 tools/test_cache_diag_log.py
..........
Ran 10 tests in 0.400s

OK
```

   decision resolution set it to `EXACT_MATCH` whenever a source was mounted, and the deeper candidate's refusal
   (`cdiag.best_reason`, computed but never written) was discarded. A 4 K checkpoint selected while a 6 K
   candidate was refused for its picture produced `rejection_reason=EXACT_MATCH` and nothing else: the event
   did not say why the 6 K candidate was unavailable. **CONFIRMED** (see R1 below).
2. **The diagnostic event counts could lose records.** `ConvCacheLog.poll()` had `READ_MAX = 1 << 20` and, when
   more than that arrived between two polls, it advanced `self.pos` past the older lines **silently**. The
   resulting `diag_counts` were not comprehensive, but nothing said so. **CONFIRMED** (see R3 below).
3. **A checkpoint selected from a batch slot was mis-described.** The decision resolution reported
   `selected_source=active_checkpoint` with the reason `SLOT_SOURCE`. A batch slot is neither the live session
   nor an active checkpoint: the event did not describe the actual selection. The slot's candidates were also
   never added to the collector, so they were not counted. **CONFIRMED** (see R2 below).
