# 06 - Kurchatov baseline (the entry revision, on its own)

The entry revision `7ad7c531dc8f7d00bd483d9baa1270a58bf2ba06` was checked out into its
own isolated worktree (`.act-worktrees/kurchatov-original`) and tested there, before the
upstream merge.

## The local's own layout (what upstream reorganised)

| Aspect | The local's arrangement |
|---|---|
| Root `CMakeLists.txt` | one 163 kB file; the `STRATA_BUILD_CONVERSATION_TESTS` block carried the cache diagnostics' and the telemetry's native test targets |
| Root `Dockerfile`, `setup.py`, `serve/`, `src/`, `include/`, `tools/`, `tests/` | the pre-reorganisation layout |
| Native engine | `src/` + `include/strata/` + `metal/` + `sycl/` |
| Serving layer | `serve/` (one `server.py` of 8 890 lines) + the root `setup.py` |
| Request telemetry | `serve/reqtelemetry/` (11 modules) + `serve/server.py`'s wiring + the web inspector |
| Cache diagnostics | `include/strata/program/cache_diag.hpp`, `src/program/cache_diag_*.cpp`, `src/program/generate.cpp`'s collector |

## The local's own test baseline

The Kurchatov request-telemetry suite, on the entry revision alone:

```
serve/test_reqtelemetry.py
serve/test_telemetry_amendment01.py
serve/test_telemetry_amendment01_final.py
serve/test_telemetry_amendment02.py
serve/test_telemetry_amendment03.py
serve/test_telemetry_closure01.py
serve/test_telemetry_evidence_writer.py
serve/test_telemetry_integrity.py
serve/test_telemetry_store_commit.py
serve/test_telemetry_store_commit_correction.py
```

Result on the entry revision: **266 passed** (41 s), and **266 passed** again on a
second run (the suite is stable; the entry revision had no order-dependent failure).

## The local's native baseline

The four header-only native tests were compiled with the entry revision's own sources
and run:

| Target | Result |
|---|---|
| `reqtelemetry_test` | all checks passed |
| `cache_diag_test` | all checks passed |
| `cache_diag_engine_test` | all checks passed |
| `cache_diag_regress_test` | all checks passed |

## The local's mutation witnesses

All seven mutation witnesses passed on the entry revision:

```
tools/test_telemetry_mutations.py                             OK
tools/test_telemetry_amendment01_mutations.py                 OK
tools/test_telemetry_amendment01_final_mutations.py          OK
tools/test_telemetry_amendment03_mutations.py                 OK
tools/test_telemetry_closure01_mutations.py                   OK
tools/test_telemetry_store_commit_mutations.py                OK
tools/test_telemetry_store_commit_correction_mutations.py     OK
```

## The predecessor's `FAIL_BASELINE_EQUIVALENT`

The predecessor ACT's result was `FAIL_BASELINE_EQUIVALENT`: a **historical** statement
that the predecessor's own baseline did not fully pass. It is recorded here as history
and is **not** treated as a passing suite. The numbers above are this ACT's own
measurements of the entry revision, taken in this session.
