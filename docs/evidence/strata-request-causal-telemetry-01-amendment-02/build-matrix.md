# 10 - The build and the platform matrix

| What | Command | Result |
|---|---|---|
| the server's whole suite, with the repository's REAL dependencies | `/tmp/stratavenv/bin/python -m unittest discover -s serve -p 'test_*.py'` | see `test-evidence.md` |
| the telemetry's own suites | `/tmp/stratavenv/bin/python -m unittest serve.test_reqtelemetry serve.test_telemetry_integrity serve.test_telemetry_amendment02` | 121 + 34 tests, OK |
| the schema (the file and the code are the same contract) | `/tmp/stratavenv/bin/python tools/test_reqtelemetry_schema.py` | all checks passed |
| the non-vacuity witnesses | `/tmp/stratavenv/bin/python tools/test_telemetry_mutations.py` | 12 witnesses, OK |
| the browser's accounting bar | `/tmp/stratavenv/bin/python tools/test_telemetry_web_accounting.py` | 4 cases, checked with `osascript -l JavaScript` |
| the patch hygiene | `git diff --check 579f5cef..HEAD` | clean |
| the native writer/reader roundtrip | `python tools/test_reqtelemetry_roundtrip.py` (with the writer built, see below) | **6 tests, OK** - the real native writer's DONE line read by the real server reader |
| the native encoder's own test | `clang++ -std=c++17 -O1 -Iinclude src/program/reqtelemetry_test.cpp -o /tmp/reqtelemetry_test && /tmp/reqtelemetry_test` | `reqtelemetry_test: all checks passed` (exit 0) |
| the CUDA engine (SM61, SM120) | `cmake -DSTRATA_ENABLE_CUDA=ON` | **NOT_EXECUTED**: this host has no CUDA toolkit and no GPU |

## The native host checks (executed here)

The CMake configure fetches `llama.cpp` through `FetchContent`, and this host has no network access, so the whole
project cannot be configured here.  The two native telemetry programs are standalone (they need only
`include/strata/program/reqtelemetry.hpp`), so they are compiled directly:

```bash
clang++ -std=c++17 -O1 -Iinclude src/program/reqtelemetry_test.cpp -o /tmp/reqtelemetry_test
/tmp/reqtelemetry_test                                  # reqtelemetry_test: all checks passed (exit 0)

clang++ -std=c++17 -O1 -Iinclude src/program/reqtelemetry_roundtrip.cpp \
        -o /tmp/rtcache/reqtelemetry_roundtrip
/tmp/stratavenv/bin/python tools/test_reqtelemetry_roundtrip.py    # 6 tests, OK
```

The roundtrip drives the SERVER's reader with a DONE line the ENGINE's own writer produced, so the two halves
cannot drift apart; it also checks the switch-off case (T19: with `STRATA_TELEMETRY=0` the DONE line carries no
telemetry key at all).

## The native edits, checked without a CUDA compiler

The two native corrections live in `src/program/generate.cpp`, which cannot be compiled here (it needs the CUDA
headers).  What CAN be checked here is that every name they use is in scope at the place they use it: the brace
depth of the file (comments and string literals stripped) is compared at the declaration and at the use.

| Name | Declared at | Scope open at the use? |
|---|---|---|
| `tele` (the request's telemetry) | line 12089 | yes (the ERR site is deeper in the same scope) |
| `tele_on` (the telemetry switch) | line 8885 | yes |
| `tele_restore_attempted` / `tele_restore_succeeded` | lines 12097 / 12098 | yes |

That is a scope check, not a compile: the CUDA build is still `NOT_EXECUTED`.

## What this host cannot do

* it has no CUDA toolkit and no GPU: the two native corrections (the cumulative work on the re-read path and the
  telemetry on the terminal ERR line) are **source-corrected but not compiled here**.  They are marked
  `NOT_EXECUTED` everywhere they appear;
* a macOS build that excludes the CUDA code is not proof of Linux/CUDA compatibility, and a mock engine is not
  proof of native cache attribution.  Both remain the work of the live-qualification ACT;
* the live cache controls (T01-T07 of the predecessor) and the performance parity are **NOT_EXECUTED** here: they
  need the engine and a GPU.

## The native corrections, in full

The native diff is `01-native-production.diff`: 39 lines, two measurement sites, no change to the cache policy,
the checkpoint policy, the scheduler, the sampling or the model's execution.
