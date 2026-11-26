# 00 - Entry state (ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01)

**Repository:** `s1onique/Kurchatov` (the working copy at `/Volumes/UserData/Users/chistyakov/Projects/SPbNIX/Kurchatov`)
**Branch:** `main`
**ENTRY_HEAD:** `5b0e549b762d9eac8b360dc34365e7ba8557efb0` ("serve: the cache's diagnostics take the engine's int64_t prompt")
**Target engine:** `strata` (`src/program/generate.cpp`)
**Date of the work:** 2026-11-26

## The tree at entry

```
$ git rev-parse --abbrev-ref HEAD
main
$ git rev-parse HEAD
5b0e549b762d9eac8b360dc34365e7ba8557efb0
$ git --no-pager status --short
?? .kurchatov-acts/
?? serve/reqtelemetry.py
```

The tracked tree was **clean**: no tracked file was modified at entry. Two untracked entries existed:

| Path | What it is | What this ACT did with it |
|---|---|---|
| `.kurchatov-acts/` | the ACT bundles and the bare mirror of the deployment repository (pre-existing, unrelated) | **left alone**; not read, not written, not committed |
| `serve/reqtelemetry.py` | the first (empty) file of this ACT, already present at entry | **written** (it is this ACT's contract module) |

Nothing was reset, rebased, stashed, cleaned or switched. No unrelated user work was touched: the only tracked
files this ACT changes are listed in `11-exit-report.md`.

## The environment this ACT was executed in

| | |
|---|---|
| Host | macOS (Darwin), `x86_64` / arm64 toolchain (`clang` 21.1.8 as the driver) |
| Python | 3.12.14 (a venv at `/tmp/stratavenv` with `jinja2`, `psutil`, `regex`, `numpy`, `pyyaml`) |
| CUDA toolkit | **absent** (`nvcc: command not found`) |
| GPU | **absent** |

**What this means for the qualification.** The native engine (`src/program/generate.cpp`) needs the CUDA toolkit,
so it could not be compiled here, and no GPU was available to run it. The consequences are recorded honestly in
`10-build-matrix.md` and `11-exit-report.md`:

* the host-compilable native parts (the new header `include/strata/program/reqtelemetry.hpp` and its tests) **were**
  compiled and run;
* the CUDA engine **was not** compiled and **was not** run: the native cache controls (T01-T07, T14) are
  **NOT_EXECUTED**, not PASS;
* the performance parity (W8) is **NOT_EXECUTED**: there is no GPU here to measure on.

Nothing in this evidence package claims a native result that was not observed.
