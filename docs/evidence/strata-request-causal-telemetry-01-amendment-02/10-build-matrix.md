# 10 - The build and the platform matrix

| What | Command | Result |
|---|---|---|
| the server's whole suite, with the repository's REAL dependencies | `/tmp/stratavenv/bin/python -m unittest discover -s serve -p 'test_*.py'` | see `03-test-evidence.md` |
| the telemetry's own suites | `/tmp/stratavenv/bin/python -m unittest serve.test_reqtelemetry serve.test_telemetry_integrity serve.test_telemetry_amendment02` | 121 + 34 tests, OK |
| the schema (the file and the code are the same contract) | `/tmp/stratavenv/bin/python tools/test_reqtelemetry_schema.py` | all checks passed |
| the non-vacuity witnesses | `/tmp/stratavenv/bin/python tools/test_telemetry_mutations.py` | 12 witnesses, OK |
| the browser's accounting bar | `/tmp/stratavenv/bin/python tools/test_telemetry_web_accounting.py` | 4 cases, checked with `osascript -l JavaScript` |
| the patch hygiene | `git diff --check 579f5cef..HEAD` | clean |
| the native writer/reader roundtrip | `python tools/test_reqtelemetry_roundtrip.py` | needs the engine binary: **NOT_EXECUTED** (no build here) |
| the CUDA engine (SM61, SM120) | `cmake -DSTRATA_ENABLE_CUDA=ON` | **NOT_EXECUTED**: this host has no CUDA toolkit and no GPU |

## What this host cannot do

* it has no CUDA toolkit and no GPU: the two native corrections (the cumulative work on the re-read path and the
  telemetry on the terminal ERR line) are **source-corrected but not compiled here**.  They are marked
  `NOT_EXECUTED` everywhere they appear;
* a macOS build that excludes the CUDA code is not proof of Linux/CUDA compatibility, and a mock engine is not
  proof of native cache attribution.  Both remain the work of the live-qualification ACT;
* the live cache controls (T01-T07 of the predecessor) and the performance parity are **NOT_EXECUTED** here: they
  need the engine and a GPU.

## The native corrections, in full

The native diff is `04-native-production.diff`: 39 lines, two measurement sites, no change to the cache policy,
the checkpoint policy, the scheduler, the sampling or the model's execution.
