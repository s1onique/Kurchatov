# 08 - Build matrix

## What was built and run in this session

| Build | Configuration | Result |
|---|---|---|
| The engine's CPU build | `cmake -S engine -B <build> -DCMAKE_BUILD_TYPE=Release -DSTRATA_BUILD_TESTS=ON -DSTRATA_BUILD_CONVERSATION_TESTS=ON -DSTRATA_NATIVE_EXPERTS=OFF` | configured and generated cleanly |
| The Kurchatov native test targets | `cache_diag_test`, `cache_diag_engine_test`, `cache_diag_regress_test`, `reqtelemetry_test` (built through `engine/CMakeLists.txt`) | built, and **4/4 passed** under `ctest` |
| The native writer/reader roundtrip | `reqtelemetry_roundtrip` (the engine's own C++ writer) + `tools/test_reqtelemetry_roundtrip.py` (the server's reader) | **6 passed** |
| The cache diagnostics' reader | `tools/test_cache_diag_log.py` | **9 passed, 1 skipped** |
| The serving layer | the whole Kurchatov telemetry suite | **266 passed** (twice) |
| The upstream serving layer | the upstream regression set | see `07-integration-verification.md` |

The four native targets are **registered with ctest** through upstream's own
`STRATA_BUILD_CONVERSATION_TESTS` block, so they run in upstream's CI as well:

```
1/4 Test #11: cache_diag_test ..................   Passed    0.20 sec
2/4 Test #12: cache_diag_engine_test ...........   Passed    0.19 sec
3/4 Test #13: cache_diag_regress_test ..........   Passed    0.23 sec
4/4 Test #14: reqtelemetry_test ................   Passed    0.21 sec
100% tests passed, 0 tests failed out of 4
```

## The CUDA architecture requirements (SM61 and SM120)

The merged tree inherits upstream's `engine/cmake/backends/cuda.cmake`, which is the
authority for the architectures:

| Requirement | How the merged tree satisfies it | Status |
|---|---|---|
| **NVIDIA Pascal SM61** | `-DCMAKE_CUDA_ARCHITECTURES=61 -DSTRATA_EXPERIMENTAL_SM60=ON` (a CUDA 12.x toolkit: CUDA 13 dropped `sm_60`/`sm_70`) | the rules **accept** `sm_61` (see the check below) |
| **NVIDIA Blackwell SM120** | `-DCMAKE_CUDA_ARCHITECTURES=120` (upstream's default) | the rules **accept** `sm_120` |
| Both at once | `-DCMAKE_CUDA_ARCHITECTURES="61;120" -DSTRATA_EXPERIMENTAL_SM60=ON` | accepted |
| The floor | upstream's floor is `sm_52` (Maxwell), **below** the local's `sm_60`: upstream's rules are a superset | not a restriction |
| The Pascal code paths | `engine/include/strata/kernels/dp4a.hpp` replaces `__dp4a` (6.1+) and `__nanosleep` (7.0+) below their arch | unchanged from upstream |
| The Blackwell code paths | upstream's `sm_120`/`sm_120a`/`sm_121` targets (the NVFP4 / MXFP8 kernels, `STRATA_CUBLASLT_MXFP8`) | unchanged from upstream |

The architecture rules were exercised with CMake's own script engine, reproducing
upstream's guard exactly:

```
--- sm_61 without the opt-in:
REFUSED 61: below sm_75 without STRATA_EXPERIMENTAL_SM60
--- sm_61 with the opt-in (the Pascal build):
ACCEPTED 61
--- sm_120 (Blackwell) without the opt-in:
ACCEPTED 120
--- sm_61;120 together (the Pascal+Blackwell build):
ACCEPTED 61
ACCEPTED 120
```

## What was NOT built here, and why

**This host has no CUDA toolkit** (`nvcc` is not installed; there is no
`/usr/local/cuda*`). The `sm_61` and `sm_120` **compiles** therefore could **not** be run
in this session. The architecture rules were verified statically, as above.

This is a **host limitation**, not a source or toolchain blocker: upstream's own CUDA
build path, its `cuda-compile` preset (`tools/packaging/build_cuda_linux.sh`) and its
`STRATA_EXPERIMENTAL_SM60` switch are unchanged by the integration. The upstream
`engine/cmake/backends/cuda.cmake` is the merged tree's file, byte for byte.

**No live native qualification was performed.** No GPU was present, no engine was
started, and no request was served. The native telemetry's correctness is established by
the header-only native tests (which exercise the DONE line's encoding, the token
accounting's identities and the cache diagnostics' decision rules on the host) and by the
writer/reader roundtrip - **not** by a live GPU run. A live qualification needs a host
with a CUDA 12.x toolkit and the relevant card.

## Host compiler and toolchain

| Aspect | The merged tree |
|---|---|
| The C++ standard | C++20 (`engine/CMakeLists.txt`: `set(CMAKE_CXX_STANDARD 20)`) - **upstream raised it from the local's C++17**; the ported native tests need it (`ConversationCache` uses defaulted comparison operators) |
| The host compiler | GCC (the Apple clang driver on this host); the native tests compiled and ran with `-std=c++20` |
| The warning flags | upstream's `strata_warnings` INTERFACE target (unchanged) |
| The CUDA toolkit | **not forced**: the merged tree needs a CUDA 12.x toolkit for the Pascal build (upstream's rule, unchanged) and warns for `sm_120` on CUDA < 13.0 (upstream's rule, unchanged). No toolkit was upgraded by this ACT. |

## The deployment pipeline

Upstream moved the container build from the root `Dockerfile` to `tools/docker/`
(`Dockerfile`, `Dockerfile.src`) and the setup entry point from the root `setup.py` to
`terminal/setup.py`. The Kurchatov deployment pipeline therefore points at paths that no
longer exist, and the Kurchatov executable identity (the `Kurchatov` brand in the web app,
the `build-id` element) is a **source-level** property that the existing pipeline carries
unchanged.

**A successor infrastructure ACT is required** to re-point the deployment pipeline at
`terminal/setup.py` and `tools/docker/`. This ACT did not modify the separate
infrastructure repository, as the ACT requires. The engine's own build and the serving
layer's own tests are unaffected: they are built and run from the merged tree's own
paths.
