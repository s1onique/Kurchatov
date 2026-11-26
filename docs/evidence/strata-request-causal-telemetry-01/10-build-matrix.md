# 10 - The build matrix (W9)

## What was built here

| Target | Command | Result |
|---|---|---|
| the native telemetry's encoding and the accounting identities | `g++ -std=c++20 -Iinclude -o /tmp/rtcache/reqtelemetry_test src/program/reqtelemetry_test.cpp` | **built**, run: `all checks passed` |
| the engine's telemetry writer (the DONE line) | `g++ -std=c++20 -Iinclude -o /tmp/rtcache/reqtelemetry_roundtrip src/program/reqtelemetry_roundtrip.cpp` | **built**, run: the DONE line with the telemetry |
| the server's test suite | `python -m unittest discover -s serve -p 'test_*.py'` | **1042 tests, OK (23 skipped)** |
| the telemetry's own suite | `python -m unittest serve.test_reqtelemetry` | **45 tests, OK** |
| the schema's check | `python tools/test_reqtelemetry_schema.py` | **OK** |
| the writer/reader roundtrip | `python tools/test_reqtelemetry_roundtrip.py` | **5 tests, OK** |

Both new C++ targets are registered in `CMakeLists.txt` (`reqtelemetry_test` as a test, `reqtelemetry_roundtrip`
as the writer the reader is checked against), in the same block as the existing cache-diagnostic targets.

## What was NOT built here

| Target | Why |
|---|---|
| `strata` (the CUDA engine, `src/program/generate.cpp`) | **no CUDA toolkit on this host** (`nvcc: command not found`). The engine's sources need `cuda_runtime.h` and the kernels. |
| the Pascal (SM61) build | the same: no `nvcc`, and no Linux/CUDA host |
| the Blackwell (SM120) build | the same |

**A macOS build that excludes the CUDA code is not proof of a Linux/CUDA build.** The engine's changes were
therefore **not compiled**, and the ACT says so plainly: the native qualification is NOT_EXECUTED.

## What the ACT's own rules require about the native changes

| Rule | How it is met |
|---|---|
| the default path stays byte-identical | `STRATA_TELEMETRY` is off by default; with it off the collector is not filled and the DONE line carries nothing extra. The writer's own test checks the switch's rule. |
| the cache policy does not change | the telemetry **observes** the decision; it does not make it. The candidate analysis is the *existing* one (`cdiag.on = cdiag_on || tele_on`), not a second analysis. |
| the model execution does not change | the sampling, the quantization and the kernels are untouched. |
| the server's behaviour does not change | the telemetry is additive: the existing endpoints keep their shapes, and the whole suite passes unchanged at 1042 tests. |

## The native code, reviewed by hand

The engine changes were **not compiled here**, so they were reviewed for scope and for the compiler's warnings:

| The change | The scope it lives in | The variables it uses |
|---|---|---|
| the telemetry's state (`tele`) | the request loop's body (the block that opens at `generate.cpp:11429`) | declared there, used in the same block |
| the restoration's outcome | the same block, assigned from the nested restore blocks | the flags are declared in the outer block |
| the telemetry's values | the same block, at the DONE line | `resume`, `n`, `pp_reached`, `reread_to`, `admit_slot`, `cdiag` - all declared in an enclosing scope |
| the DONE line's suffix | the same block | the `tele_txt` string |

`-Wall -Wextra` is on for the C++ targets (`CMakeLists.txt:259-260`), so the changes avoid an unused variable
(the lookup clock is used, for the lookup time) and an unused parameter.

**This is a hand review, not a compile.** The first thing to do on a CUDA machine is build the engine.
