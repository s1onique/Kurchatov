# 07 - Integration verification

Every number below was measured in this session, on this host, on the candidate tree.

## The candidate

| Field | Value |
|---|---|
| The candidate revision | `74e89653e98d855d292c373075a5f1978df56a23` |
| Its parents | `7ad7c531dc8f7d00bd483d9baa1270a58bf2ba06` (the Kurchatov entry head) and `42e489d145aaf4430b54f2c58679be27d45faf17` (the pinned upstream head) |
| The branch | `act/kurchatov-upstream-sync-01` |

## The Kurchatov telemetry suite (the local's own)

```
terminal/serve/test_reqtelemetry.py
terminal/serve/test_telemetry_amendment01.py
terminal/serve/test_telemetry_amendment01_final.py
terminal/serve/test_telemetry_amendment02.py
terminal/serve/test_telemetry_amendment03.py
terminal/serve/test_telemetry_closure01.py
terminal/serve/test_telemetry_evidence_writer.py
terminal/serve/test_telemetry_integrity.py
terminal/serve/test_telemetry_store_commit.py
terminal/serve/test_telemetry_store_commit_correction.py
```

| Tree | Result |
|---|---|
| The Kurchatov entry revision (`.act-worktrees/kurchatov-original`) | **266 passed** (41 s), and **266 passed** again on a second run |
| The candidate (`.act-worktrees/kurchatov-integration`) | **266 passed** (40 s), and **266 passed** again on a second run |

**No new regression, and no test was weakened or removed to obtain the pass.**

## The upstream serving-layer suite (the regression check)

```
terminal/serve/test_server.py
terminal/serve/test_prometheus.py
terminal/serve/test_lifecycle.py
terminal/serve/test_request_accounting.py
terminal/serve/test_web_api_key.py
terminal/serve/test_monitor.py
```

| Tree | Result |
|---|---|
| The pinned upstream revision, alone | **1 failed, 512 passed, 8 skipped, 707 subtests passed** (191 s) |
| The candidate | **1 failed, 512 passed, 8 skipped, 707 subtests passed** (174 s) |

The one failure is the **same** test in both runs, and it is upstream's own **baseline**
failure (a Windows-only assertion evaluated on macOS):

```
terminal/serve/test_server.py::VisionTempFiles::test_no_console_window_on_windows
```

**New regression identities: none.**

## How the four integration regressions were found and fixed

The first merged candidate failed **29** of the upstream tests. Each was a real
integration defect, found by the upstream suite itself:

| Symptom | Cause | Fix |
|---|---|---|
| 4 `SlotLegAccounting` failures ("an unknown decode time is reported as 0") | the merged `server.py` re-defined `request_timings`, `request_stats`, `carry_leg` and `add_carry`, **shadowing** upstream's newer versions in `server_parts/core.py` (which keep the null-versus-zero rule) | the local's stale copies were **removed**; upstream's `server_parts` versions are now the single authority |
| 18 `SilentEngine`/`LostStep` failures (`StrataEngine has no attribute 'sampling_keys'`) | the region-6 resolution kept the local's methods and dropped upstream's `StrataEngine.sampling_keys` (the hy4-aware one) | upstream's method was **restored** beside the local's `request_key`/`set_request_id`/`request_id`/`error_figures` |
| the same 18 (second order) | the region-6 resolution dropped upstream's `StrataEngine._raise_if_fatal_gpu` | restored |
| the same 18 (third order) | the region-6 resolution dropped the `@staticmethod` decorator from the local's `request_key` | restored |

The shadowing was found with a systematic comparison of every name upstream imports from
`server_parts/` against the definitions in the merged `server.py`; the method sets of
`StrataEngine`, `Service` and `MockEngine` were compared the same way. After the fixes:

```
upstream's StrataEngine methods: 63   merged: 67   MISSING: NONE
upstream's Service methods:      96   merged: 102  MISSING: NONE
upstream's MockEngine methods:    2   merged: 4    MISSING: NONE
```

The two intentional deviations (the local's newer `conversation_cache_view` and `btrace`
win over upstream's `server_parts/engines.py` copies) are recorded in
`04-conflict-resolutions.md`.

## The native (C++) tests

Built through upstream's own `engine/CMakeLists.txt`
(`-DSTRATA_BUILD_TESTS=ON -DSTRATA_BUILD_CONVERSATION_TESTS=ON -DSTRATA_NATIVE_EXPERTS=OFF`),
C++20, the host's GCC:

```
1/4 Test #11: cache_diag_test ..................   Passed    0.20 sec
2/4 Test #12: cache_diag_engine_test ...........   Passed    0.19 sec
3/4 Test #13: cache_diag_regress_test ..........   Passed    0.23 sec
4/4 Test #14: reqtelemetry_test ................   Passed    0.21 sec
100% tests passed, 0 tests failed out of 4
```

## The writer/reader roundtrip (the native writer against the server's reader)

The engine's own C++ writer (`engine/src/program/reqtelemetry_roundtrip.cpp`) was built
and its `DONE` line was read by the server's reader:

```
python tools/test_reqtelemetry_roundtrip.py   ->  Ran 6 tests ... OK
```

## The mutation witnesses

All seven pass, and each remains non-vacuous (the reversal really breaks the witness):

```
tools/test_telemetry_mutations.py                             OK
tools/test_telemetry_amendment01_mutations.py                 OK
tools/test_telemetry_amendment01_final_mutations.py          OK
tools/test_telemetry_amendment03_mutations.py                 OK
tools/test_telemetry_closure01_mutations.py                   OK
tools/test_telemetry_store_commit_mutations.py                OK
tools/test_telemetry_store_commit_correction_mutations.py     OK
```

One witness was **adapted, not weakened**: `test_telemetry_amendment03_mutations.py`
looked for the **first** `ERR restoring a conversation checkpoint failed` in
`generate.cpp`. Upstream added a second one (the batch slot's own restore), so the
witness now looks for the site whose `ERR` line carries the telemetry
(`...failed%s`). It still asserts that the measured duration is copied into the error
path, and still reverses that line to prove the witness is not vacuous.

## The remaining tools witnesses

```
tools/test_reqtelemetry_schema.py       all checks passed
tools/test_reqtelemetry_roundtrip.py     OK (6)
tools/test_telemetry_web_accounting.py   4 cases checked with osascript
tools/test_telemetry_web_inspector.py    the invocation inspector was checked with osascript
tools/test_telemetry_web_status.py       3 cases checked with osascript
tools/test_kurchatov_identity.py         OK
tools/test_cache_diag_log.py             OK (9 passed, 1 skipped)
```

Their **paths** were adapted to the new tree (`serve/` -> `terminal/serve/`,
`src/` -> `engine/src/`, `include/` -> `engine/include/`) and their `sys.path` setup now
includes `terminal/` (where the `serve.` package lives). **No assertion was changed.**

## What was NOT verified here

* **No live native qualification.** No GPU and no CUDA toolkit were present; no engine
  was started and no request was served. The native correctness is established by the
  header-only native tests and the writer/reader roundtrip, not by a live run.
* **No `sm_61` or `sm_120` compile.** See `08-build-matrix.md`: the architecture rules
  were verified statically with CMake's own script engine, but the compiles need a CUDA
  12.x toolkit.
* **The whole upstream engine** (the CUDA/HIP/SYCL backends, the vendored
  `strata-llama`) was not compiled: this host has no CUDA toolkit and the CPU-only
  configuration is what the CPU preset builds.
