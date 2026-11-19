# Strata cache decision observability: the ACT-02 validation (ACT-KURCHATOV-STRATA-CACHE-CUDA-02)

**Branch:** `act/strata-cache-cuda-validation-02`
**Parent:** `d217d783c6d9ae133277b2edf1edaa1cb835a6d2` (`act/strata-cache-observability-01`)
**Scope:** Phase 1 (entry and source review) and Phase 2 (reproduce and fix the observability defects) only.

This document records what ACT-02 did in its first two phases. Phases 3 to 5 (the native CUDA 12 build, the test
parity on the GPU and the P40 runtime window) are **not** part of this run and are listed as NOT_EXECUTED below.

## The continuation run (Gate 0 and Gate 1 of the second mission)

The second mission (Gate 0 identity, Gate 1 the three counterexamples R4, R5 and R6) was executed on the same
branch. **Gate 2 (the native CUDA 12 build) was NOT executed**: the only machine available for this run is a
macOS arm64 host with no CUDA toolkit and no NVIDIA GPU, and the mission states plainly that nothing can be
compiled for CUDA here. Gate 2's evidence is therefore absent, not partial.

| Gate | Status | Note |
|---|---|---|
| Gate 0 - identity | **PASS** | repository, branch, exact HEAD `579a51a73631eb3f388f7d4055ec5bbe072ad60e`, clean tree, no stash, no push, no PR, no merge |
| Gate 1 - R4, R5, R6 | **PASS** | each reproduced RED against the pre-fix collector, then fixed, then GREEN (55 checks) |
| Gate 2 - native CUDA 12 SM 6.1 build | **NOT_EXECUTED** | no CUDA toolkit on this host (macOS arm64); no Linux x86-64 workspace was available |
| Gate 3 - real-engine validation | **NOT_EXECUTED** | no GPU and no exclusive test window; the deployed service was not touched |

### Gate 0 - identity

```
$ git remote -v
origin  git@github.com:s1onique/Kurchatov.git (fetch)
origin  git@github.com:s1onique/Kurchatov.git (push)

$ git status --porcelain=v1 -b
## act/strata-cache-cuda-validation-02

$ git rev-parse HEAD
579a51a73631eb3f388f7d4055ec5bbe072ad60e

$ git stash list
(empty)

$ git --no-pager log --oneline -n 4
579a51a7 docs: the ACT-02 evidence: the CMake and ctest run
72453b55 serve: the conversation cache's decision observability: the ACT-01 review's three defects
d217d783 serve: the conversation cache's decision observability (STRATA_CACHE_DIAG=1)
3e164216 Merge the engine work for 0.1.45-poly.10
```

The repository is `s1onique/Kurchatov`, the branch is `act/strata-cache-cuda-validation-02`, the required HEAD
`579a51a73631eb3f388f7d4055ec5bbe072ad60e` was present and was the tip, and the working tree was clean with no
stashes. All the earlier work was preserved.
### Gate 1 - the three counterexamples

#### R4 - a rejected checkpoint SHORTER than the selected one

The required case: a selected 6 000-token checkpoint and a rejected 2 000-token candidate.

**RED** (the pre-fix collector reported the shorter refusal as the "deeper" candidate):

```
FAIL: R4: a SHORTER rejected candidate is not a deeper one: deeper_candidate_tokens is 0
FAIL: R4: a SHORTER rejected candidate leaves deeper_rejection_reason UNKNOWN
```

**The defect.** `CacheDiagCollector::add()` tracked the longest candidate that was **not usable**, and the event
wrote it unconditionally. A refused candidate that was SHORTER than what was selected was therefore reported as
the "deeper" one, with a typed reason - which is wrong: it is not what stopped the request from reusing more.

**The fix.** The comparison is now made at the **decision boundary**, where the selected prefix is known:

```cpp
// The deeper refused candidate, but only when it really was deeper than what was selected: a
// refused candidate that was SHORTER is not what stopped the request from reusing more.
if (deeper_tokens > selected_prefix) {
    e.deeper_rejection_reason = deeper_reason;
    e.deeper_candidate_tokens = deeper_tokens;
}
```

With nothing selected (`selected_prefix == 0`) every refused candidate is deeper than nothing, so the old
behaviour is kept: a request that reused nothing still names its best refused candidate.

**GREEN:** `selected_prefix_tokens=6000`, `deeper_candidate_tokens=0`, `deeper_rejection_reason=UNKNOWN`.

#### R5 - the image identity at the checkpoint's boundary

The R1 fixture was corrected: the picture now sits at **index 5** inside a **six-token** checkpoint (before, it
was at index 6, which was below the checkpoint's end and so never tested the boundary). The boundary was
measured, not assumed - `imgs_below(prompt_imgs, L)` keeps the pictures with `start < L`:

```
L=4 -> 0 picture(s) below
L=5 -> 0 picture(s) below
L=6 -> 1 picture(s) below
L=7 -> 1 picture(s) below
```

So a 4-token checkpoint sees no picture at all (the picture is below its end) and a 6-token checkpoint sees it.
The three cases:

| Case | Fixture | Expected | Result |
|---|---|---|---|
| R5a | the checkpoint's picture IS the prompt's (`{5,222}`) | the six-token checkpoint is reused | `resume=6`, `selected_prefix_tokens=6`, `deeper_rejection_reason=UNKNOWN`, `deeper_candidate_tokens=0` |
| R5b | the checkpoint's picture is NOT the prompt's (`{5,111}`) | the six-token checkpoint is refused | `resume=0`, `selected_source=none`, `deeper_rejection_reason=IMAGE_MISMATCH`, `deeper_candidate_tokens=6` |
| R5c | the 4-token checkpoint (ends before the picture) plus the refused 6-token one | the shallower one is reused | `resume=4`, `selected_prefix_tokens=4`, `deeper_rejection_reason=IMAGE_MISMATCH`, `deeper_candidate_tokens=6` |

**R5 needed no production change**: the boundary logic was already correct. The corrected fixture is now a
#### R6 - the batch slot against a parked checkpoint

The required case: `slot_tokens=6000`, `parked.tokens=5000`, `resume=0`.

**The production source was read first** (`src/program/generate.cpp`):

```
12148:  if (idle_source && (int64_t) sl.ids.size() > std::max(resume, slot_tokens) && starts_with(sl.ids, {})) {
12149:      slot_source = b;  slot_tokens = (int64_t) sl.ids.size();  slot_ck = nullptr;
12233:  bool borrow = stages.empty() && parked.tokens > std::max(resume, slot_tokens) && ...
12241:  if (parked.tokens > std::max(resume, slot_tokens) && !borrow) incoming.emplace(...);
12243:  if (incoming || borrow) slot_source = -1;
12370:      resume = slot_tokens;  12371: from_live = true;
```

**RED** (the test harness did not reproduce the production selection):

```
FAIL: R6: the SLOT wins: 6000 tokens, not the parked 5000
FAIL: R6: the event names the SLOT, not the parked side
FAIL: R6: the reported prefix is the slot's 6000 tokens
FAIL: R6: the reason is the slot
```

**The defect was in the TEST HARNESS, not in production.** The harness compared the parked side with `resume`
alone (`parked.tokens > resume`), while production compares it with `std::max(resume, slot_tokens)`. With
`slot_tokens=6000` the harness let the parked side (5 000) win; production lets the **slot** (6 000) win, because
`5000 > 6000` is false. The harness also mounted the slot only when `slot_tokens > resume`, while production
mounts it whenever `slot_source >= 0`, and it did not model the borrow at all.

**The fix.** Both transcriptions (`cache_diag_regress_test.cpp` and `cache_diag_engine_test.cpp`) now reproduce
the production order exactly:

```
borrow:      parked.tokens > std::max(resume, slot_tokens) && conversations.borrows(parked)
parked take: parked.tokens > std::max(resume, slot_tokens) && !borrow
then:        if (incoming || borrow) slot_source = -1;   (the parked side cancels the slot)
the slot:    slot_source >= 0  ->  resume = slot_tokens; from_live = true;
```

**GREEN:** `resume=6000`, `selected_source=slot`, `selected_prefix_tokens=6000`, `rejection_reason=SLOT_SOURCE`.

**The production selection was NOT changed.** This was checked mechanically: every selection line in
`generate.cpp` is byte-identical to the base.

```
=== SELECTION-CODE INVARIANT CHECK ===
  if (incoming || borrow) slot_source = -1;                    base=1 now=1 SAME
  parked.tokens > std::max(resume, slot_tokens)                base=2 now=2 SAME
  resume = slot_tokens;                                        base=1 now=1 SAME
  if (resume > 0) {                                            base=1 now=1 SAME
  cdiag.selected = strata::program::cache_diag::Source::slot;  base=1 now=1 SAME

=== the only changed lines in generate.cpp ===
-                e.deeper_rejection_reason = deeper_reason;
-                e.deeper_candidate_tokens = deeper_tokens;
+                if (deeper_tokens > selected_prefix) {
+                    e.deeper_rejection_reason = deeper_reason;
+                    e.deeper_candidate_tokens = deeper_tokens;
+                }
```

### Gate 1 - the RED to GREEN evidence, both ways

The same 55 checks were run against the pre-fix collector semantics and against the fixed one:

```
$ /tmp/red_test          # the NEW tests, the OLD collector
cache_diag_regress_test: 55 checks passed, 6 failed
FAIL: R6: the SLOT wins: 6000 tokens, not the parked 5000
FAIL: R6: the event names the SLOT, not the parked side
FAIL: R6: the reported prefix is the slot's 6000 tokens
FAIL: R6: the reason is the slot
FAIL: R4: a SHORTER rejected candidate is not a deeper one: deeper_candidate_tokens is 0
FAIL: R4: a SHORTER refused candidate leaves deeper_rejection_reason UNKNOWN

$ ./build-host/cache_diag_regress_test    # the NEW tests, the FIXED collector
cache_diag_regress_test: 55 checks passed
```

R5's three cases passed before and after: the image boundary was already correct, and the corrected fixture
locks it in.


regression test, so the boundary cannot silently move.



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
| `src/program/cache_diag_regress_test.cpp` | **new.** the counterexamples as regression tests (R1, R2, R4, R5, R6: 55 checks) |
| `src/program/cache_diag_engine_test.cpp` | the collector transcription follows the production one; the R4/R5/R6 cases are covered (74 -> 99 checks) |
| `src/program/cache_diag_test.cpp` | the deeper-refusal scenario; the test renders the event with the **production** `Writer` instead of a copy of its format (77 -> 86 checks) |
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
cache_diag_test: 86 checks passed

$ clang++ -std=c++20 -O2 -Iinclude src/program/cache_diag_engine_test.cpp -o build-host/cache_diag_engine_test
$ ./build-host/cache_diag_engine_test
cache_diag_engine_test: 99 checks passed

$ clang++ -std=c++20 -O2 -Iinclude src/program/cache_diag_regress_test.cpp -o build-host/cache_diag_regress_test
$ ./build-host/cache_diag_regress_test
cache_diag_regress_test: 55 checks passed

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

### Through the project's own CMake and ctest

```
$ cmake -S . -B build-host-cmake -DCMAKE_BUILD_TYPE=Release -DSTRATA_BUILD_TESTS=OFF \
        -DSTRATA_BUILD_CONVERSATION_TESTS=ON -DSTRATA_ENABLE_CUDA=OFF
-- ggml version: 0.24.0
-- ggml commit:  3cf03257f
-- Configuring done (495.7s)
-- Generating done (0.1s)
CMAKE_EXIT=0

$ cmake --build build-host-cmake --target cache_diag_test cache_diag_engine_test \
        cache_diag_regress_test cache_diag_roundtrip conversation_cache_test conv_cache_test -j 4
[100%] Built target cache_diag_test
[100%] Built target cache_diag_engine_test
[100%] Built target cache_diag_regress_test
[100%] Built target cache_diag_roundtrip
[100%] Built target conversation_cache_test
[100%] Built target conv_cache_test
BUILD_EXIT=0

$ cd build-host-cmake && ctest -R 'cache_diag|conversation_cache_test|conv_cache' --output-on-failure
1/5 Test  #1: conversation_cache_test ..........   Passed    0.22 sec
2/5 Test  #8: cache_diag_test ..................   Passed    0.00 sec
3/5 Test  #9: cache_diag_engine_test ...........   Passed    0.00 sec
4/5 Test #10: cache_diag_regress_test ..........   Passed    0.00 sec
5/5 Test #13: conv_cache_test ..................   Passed    0.16 sec

100% tests passed, 0 tests failed out of 5
```

The configure took 495.7 s because it fetches llama.cpp (`ggml` 0.24.0, commit `3cf03257f`) over the network. The
fetch succeeded. `cache_diag_regress_test` is registered by this ACT and runs under ctest.

### Gate 2 - the CUDA 12 SM 6.1 build: NOT EXECUTED, and why

The preconditions were probed rather than assumed:

```
$ uname -a
Darwin MacBook-Pro-3.local 23.6.0 Darwin Kernel Version 23.6.0: Thu Dec 19 20:47:16 PST 2024; root:xnu-10063.141.1.703.2~1/RELEASE_ARM64_T6031 arm64 arm Darwin

$ uname -m
arm64

$ command -v nvcc        -> NOT FOUND
$ command -v nvidia-smi  -> NOT FOUND
$ ls /usr/local/cuda*    -> NOT FOUND (no matches)
$ cmake --version | head -1
cmake version 4.1.6

$ df -h .
/dev/disk3s8    927G  857G   71G   93% /Volumes/UserData
```

The host is **macOS arm64**, not Linux x86-64, and there is no CUDA toolkit of any version. The mission's
configuration therefore cannot be attempted here:

```
cmake -S . -B build-cuda12-obs -DCMAKE_BUILD_TYPE=Release -DSTRATA_ENABLE_CUDA=ON \
  -DSTRATA_EXPERIMENTAL_SM60=ON -DCMAKE_CUDA_ARCHITECTURES=61 \
  -DSTRATA_BUILD_TESTS=OFF -DSTRATA_BUILD_CONVERSATION_TESTS=ON
```

would fail at the CUDA language enablement step (`CMAKE_CUDA_COMPILER` unset, no `nvcc`). **CUDA 13 was not
substituted**, as the mission requires, and no toolchain was installed or reconfigured anywhere. The
production inference VM was not touched.

This is an **environmental** limitation, not a source defect: the ACT-02 changes to `generate.cpp` are three
assignments and one `if` block inside the diagnostic's own blocks, using the production header's own types
(`Source::slot`, `Reason`, `CacheDiagEvent::deeper_rejection_reason`,
`CacheDiagEvent::deeper_candidate_tokens`). The same header compiles in the host tests. The CUDA build is
still required before this is merged.



| Item | Status | Reason |
|---|---|---|
| the `CUDA` build of `src/program/generate.cpp` | **NOT_EXECUTED** | Phase 3 / Gate 2. This machine is macOS (arm64) with no CUDA toolkit and no NVIDIA GPU. The ACT-02 changes to `generate.cpp` are inside the diagnostic blocks only, but they have NOT been through `nvcc`. |
| the native Linux x86-64 CUDA 12.x SM 6.1 build (`build-cuda12-obs`) | **NOT_EXECUTED** | Gate 2. No Linux x86-64 workspace and no CUDA 12 toolkit were available on this run's host (macOS arm64). CUDA 13 was NOT substituted, as the mission requires. |
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

## The final verdict

**PARTIAL.**

`GO_CUDA_BUILD` requires the actual CUDA 12 SM 6.1 engine compilation to succeed. It was **NOT EXECUTED** in
this run: the only available host is macOS arm64 with no CUDA toolkit, no NVIDIA GPU and no Linux x86-64
workspace. Host-only compilation is **not** accepted as a substitute, so the gate stays open.

`GO_OBSERVABLE` additionally requires the real-engine diagnostic verification and deterministic runtime parity on
a GPU. It was **NOT EXECUTED** either: no GPU and no exclusive test window.

What **is** closed:

- **Gate 0 - identity: PASS.** The repository, the branch, the exact required HEAD
  `579a51a73631eb3f388f7d4055ec5bbe072ad60e` and a clean tree with no stashes were verified. All the earlier work
  was preserved. No push, no PR, no merge.
- **Gate 1 - R4, R5, R6: PASS.** Each counterexample was reproduced RED against the pre-fix collector and is
  GREEN after the fix, with the RED and the GREEN runs both recorded above (55 checks: 6 failed before, 0 after).
- **R4** is a real production defect and was fixed in the diagnostic only: a refused candidate that was SHORTER
  than the selected one is no longer reported as the "deeper" candidate.
- **R5** needed no production change: the image boundary at index 5 was already correct, and the corrected
  fixture is now a regression test.
- **R6** was a defect in the **test harness**, not in production: the harness compared the parked side with
  `resume` instead of production's `std::max(resume, slot_tokens)`. Both transcriptions now reproduce the
  production selection exactly, and the production selection is byte-identical to the base (checked
  mechanically, line by line).
- The targeted host tests pass, through the project's own CMake and ctest: **100% tests passed, 0 failed out of 5**.

The next step is Gate 2 on an isolated Linux x86-64 workspace with CUDA 12.x (12.9 preferred), the exact
configuration in the mission, `CMAKE_CUDA_COMPILER` pointed at the installed CUDA 12 `nvcc`, and the real `strata`
target built for `CMAKE_CUDA_ARCHITECTURES=61` with `STRATA_EXPERIMENTAL_SM60=ON`. CUDA 13 must not be
substituted: Pascal (compute capability 6.1) is not a CUDA 13 target.


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
