# 03 - The native build (W2)

ACT: **ACT-KURCHATOV-UPSTREAM-SYNC-01**, execution segment `QUALIFICATION-HANDOFF`
Candidate revision built: `859d62c4a7f6bf3b1942ff1c6e61e4405f91623a`
Accepted merge head: `74e89653e98d855d292c373075a5f1978df56a23`
Pinned upstream head: `42e489d145aaf4430b54f2c58679be27d45faf17`

The build is of the **exact candidate revision**, out of upstream's own build organization
(`engine/CMakeLists.txt`, `engine/cmake/backends/cuda.cmake`, `engine/CMakePresets.json`), on a real GPU
host, and it produced the **full native executable** - not only the standalone telemetry tests.

## 1. The host

| What | The value |
| --- | --- |
| the host | `ubuntu-inference-01`, `192.168.50.239`, Ubuntu 24.04.5 |
| the card | **Tesla P40**, compute capability **6.1** (Pascal, `sm_61`), driver `580.178.04` |
| the CUDA compiler | `/usr/local/cuda-12.9/bin/nvcc`, `release 12.9, V12.9.86`, `Build cuda_12.9.r12.9/compiler.36037853_0` |
| the host compiler | `c++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0` (GNU) |
| CMake / Ninja | `cmake version 3.28.3` / `ninja 1.11.1` |
| the toolkit's `sm_61` support | **present** (`nvcc --list-gpu-code` names `sm_61`) |
| vCPUs / RAM | 8 / 46 GiB |

The **memory gate** was measured on the guest immediately before the build, and it is `MemAvailable` and
not `MemFree`: `MemAvailable: 11060632 kB` before the build, `MemAvailable: 8730540 kB` at its busiest
point. The build was bounded to **2 jobs** because the guest's headroom is shared with the running engine's
expert arena.

## 2. The source that was built

The candidate revision was fetched as an **archive of the exact revision** - not a branch, not a working
tree with local edits - and its digest was verified on the guest before anything was extracted:

```text
$ sha256sum candidate-859d62c4a.tar.gz
cb785c1e383994f850652e3b738bc061a8ce38fde76704089df238affbbcc4a9  candidate-859d62c4a.tar.gz
```

The same digest was taken on the controller before the transfer. The source was unpacked into a workspace
of its own, **outside** the deployment's installation directory:

```text
/opt/.kurchatov-qual/source-859d62c4a          the source
/opt/.kurchatov-qual/build-sm61-859d62c4a      the build directory
/opt/.kurchatov-qual/artifact-sm61-859d62c4a   the artifact directory
```

## 3. The configuration of the Pascal profile

```sh
cmake -S engine -B /opt/.kurchatov-qual/build-sm61-859d62c4a -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DSTRATA_ENABLE_CUDA=ON \
  -DSTRATA_EXPERIMENTAL_SM60=ON \
  -DCMAKE_CUDA_ARCHITECTURES=61 \
  -DCMAKE_CUDA_COMPILER=/usr/local/cuda-12.9/bin/nvcc \
  -DSTRATA_BUILD_TESTS=ON \
  -DSTRATA_BUILD_CONVERSATION_TESTS=ON
```

The engine's own cache, read back after the configure:

```text
CMAKE_BUILD_TYPE:STRING=Release
CMAKE_CUDA_ARCHITECTURES:UNINITIALIZED=61
CMAKE_CUDA_COMPILER:STRING=/usr/local/cuda-12.9/bin/nvcc
STRATA_BUILD_CONVERSATION_TESTS:BOOL=ON
STRATA_BUILD_TESTS:BOOL=ON
STRATA_ENABLE_CUDA:BOOL=ON
STRATA_EXPERIMENTAL_SM60:BOOL=ON
```

The configure's own report is the engine's rule speaking:

```text
-- Strata: prefill_decode_golden not built: 61 has an architecture below sm_75
-- strata tests: ON - cpu, cuda
-- Build files have been written to: /opt/.kurchatov-qual/build-sm61-859d62c4a
```

`STRATA_EXPERIMENTAL_SM60=ON` is **mandatory** for this card: the engine's guard
(`engine/cmake/backends/cuda.cmake:53`) **refuses** an architecture below sm_75 without it, and refuses the
configure outright.

The build:

```sh
ninja -C /opt/.kurchatov-qual/build-sm61-859d62c4a -j 2 \
  strata reqtelemetry_test reqtelemetry_roundtrip \
  cache_diag_test cache_diag_engine_test cache_diag_regress_test cache_diag_roundtrip \
  conv_cache_test conversation_cache_test
```

## 4. The result

**189 of 189 targets, 0 failures.** The full native executable was produced:

```text
$ ls -la strata
-rwxrwxr-x 1 ubuntu ubuntu 91665880 strata
$ sha256sum strata
0f5686d872b78b5451813d3c6d9ac4c5c70b8194d05c39be95db92821bf8cb23  strata
```

### 4.1 The binary's own embedded architecture targets

The targets are read out of the **linked executable**, not out of the build command - the check that catches
a substituted binary:

```text
$ /usr/local/cuda-12.9/bin/cuobjdump --list-elf .../strata | head -3
ELF file    1: strata.1.sm_61.cubin
ELF file    2: strata.2.sm_61.cubin
ELF file    3: strata.3.sm_61.cubin
$ /usr/local/cuda-12.9/bin/cuobjdump --list-elf .../strata | grep -oE "sm_[0-9]+[a-z]?" | sort -u
sm_61
```

**`sm_61` and nothing else.** The binary carries no code for any other architecture.

### 4.2 The native test targets

The **selected** native suites, run on the real card:

```text
$ ctest -R "reqtelemetry|cache_diag|conv_cache|conversation_cache" --output-on-failure
    Start   1: conversation_cache_test
1/6 Test   #1: conversation_cache_test ..........   Passed    0.64 sec
    Start   11: cache_diag_test
2/6 Test  #11: cache_diag_test ..................   Passed    0.00 sec
    Start   12: cache_diag_engine_test
3/6 Test  #12: cache_diag_engine_test ...........   Passed    0.01 sec
    Start   13: cache_diag_regress_test
4/6 Test  #13: cache_diag_regress_test ..........   Passed    0.00 sec
    Start   14: reqtelemetry_test
5/6 Test  #14: reqtelemetry_test ................   Passed    0.00 sec
    Start 232: conv_cache_test
6/6 Test #232: conv_cache_test ..................   Passed    0.00 sec

100% tests passed, 0 tests failed out of 6
```

The two roundtrips, run directly:

```text
$ ./reqtelemetry_roundtrip
enabled=0
DONE 7 100 41.5 210.0 stop 24 31 60 9 10 1 2 1.5 40 0 chunk=0 experts_streamed=0
ROUNDTRIP_EXIT=0
$ ./cache_diag_roundtrip
enabled=0
CD_EXIT=0
```

### 4.3 The non-interference proof

The build was **isolated**: the running service was never stopped, and its identity is unchanged.

| | Before the build | After the build |
| --- | --- | --- |
| `MainPID` | `2180973` | `2180973` |
| `NRestarts` | `0` | `0` |
| `ExecMainStartTimestamp` | `Thu 2026-11-26 06:28:05 UTC` | `Thu 2026-11-26 06:28:05 UTC` |
| `ActiveState` / `SubState` | `active` / `running` | `active` / `running` |

The same process, the same start, no restart. The deployment was not disturbed by the build.

## 5. The Blackwell profile

The Blackwell profile was **not built**: this host has no Blackwell card and no CUDA 13.x toolkit, and
**ISOLATED_CUDA_BUILD_PERMITTED** covers an isolated build, not a claim about hardware that is not here.
What this ACT does about it is the honest thing: it reads the profile out of the **repository's own
declaration** and records it, and it does not claim a build that was not executed.

```text
.github/workflows/backends.yml:74
  - { cuda: '13.0', image: '13.0.2-devel-ubuntu24.04', archs: '75-real;86-real;120-real', sm60: 'OFF' }
```

| Profile | Architecture | Toolkit | `STRATA_EXPERIMENTAL_SM60` | State |
| --- | --- | --- | --- | --- |
| **PASCAL** | `sm_61` | CUDA **12.9** | **ON** | **BUILT** - 189/189, `sm_61` embedded, 6/6 ctest, 2/2 roundtrips |
| **BLACKWELL** | `sm_120` | CUDA **13.x** | **OFF** | **NOT BUILT** - no Blackwell card and no CUDA 13.x toolkit on this host; the profile is the repository's own declaration (`.github/workflows/backends.yml:74`), verified by reading it, not by compiling it |

The Blackwell build is the successor infrastructure ACT's obligation on a Blackwell host; this ACT states
the obligation and does not fake the result.

## 6. The build flags, the compiler identity and the checksum, in one place

```yaml
SM61_BUILD:
  REVISION: 859d62c4a7f6bf3b1942ff1c6e61e4405f91623a
  SOURCE_DIGEST: cb785c1e383994f850652e3b738bc061a8ce38fde76704089df238affbbcc4a9  (the archive, verified on both sides)
  HOST: ubuntu-inference-01 192.168.50.239, Tesla P40, compute capability 6.1, driver 580.178.04
  TOOLKIT: CUDA 12.9.86 (release 12.9, V12.9.86) at /usr/local/cuda-12.9
  HOST_COMPILER: GNU c++ 13.3.0 (Ubuntu 13.3.0-6ubuntu2~24.04.1)
  CMAKE: 3.28.3, Ninja 1.11.1
  FLAGS: -DCMAKE_BUILD_TYPE=Release -DSTRATA_ENABLE_CUDA=ON -DSTRATA_EXPERIMENTAL_SM60=ON
         -DCMAKE_CUDA_ARCHITECTURES=61 -DCMAKE_CUDA_COMPILER=/usr/local/cuda-12.9/bin/nvcc
         -DSTRATA_BUILD_TESTS=ON -DSTRATA_BUILD_CONVERSATION_TESTS=ON
  TARGETS: 189 of 189, 0 failed
  BINARY: strata, 91665880 bytes, sha256 0f5686d872b78b5451813d3c6d9ac4c5c70b8194d05c39be95db92821bf8cb23
  EMBEDDED_ARCHITECTURES: sm_61 (only), read out of the linked executable with cuobjdump
  CTEST: 6 of 6 passed (the selected native suites)
  ROUNDTRIPS: reqtelemetry_roundtrip 0, cache_diag_roundtrip 0
  NON_INTERFERENCE: the running service's MainPID, start timestamp and restart count are unchanged
```

```yaml
SM120_BUILD:
  NOT BUILT - this host has no Blackwell card and no CUDA 13.x toolkit.
  The profile is the repository's own declaration: .github/workflows/backends.yml:74
    { cuda: '13.0', image: '13.0.2-devel-ubuntu24.04', archs: '75-real;86-real;120-real', sm60: 'OFF' }
  No build, no checksum and no claim is made for it.
```

## 7. What was NOT done on the host

* **No engine was started.** The build produced the executable; it was not run against a model, and no
  request was served by it. The native correctness rests on the native test targets and the roundtrips.
* **The running service was not stopped, not restarted, and not replaced.** The candidate lives in its own
  workspace outside the deployment's installation directory, and the incumbent engine's bytes are untouched.
* **No package was installed.** The CUDA 12.9 toolkit was already on the host; the build read it and
  installed nothing.
* **Nothing was published and nothing was pushed.**

## 8. The upstream link defect that the full-target build found

Building **every** target of the tree (not only the release engine) found **one** link failure, in the
auxiliary diagnostic executable `strata-device`:

```text
/usr/bin/ld: libstrata_core.a(pinned.cu.o): in function
  'strata::core::(anonymous namespace)::place_arena_numa_slices(...)':
tmpxft_0028c54f_00000000-6_pinned.cudafe1.cpp:(.text+0x45a2):
  undefined reference to `strata::kernels::cpu::expert_layout()'
```

### 8.1 It is upstream's defect, not the merge's

Every file in the failing link chain is **byte-identical to the pinned upstream's**:

```text
IDENTICAL_TO_UPSTREAM  engine/src/core/pinned.cu
IDENTICAL_TO_UPSTREAM  engine/src/core/device_main.cpp
IDENTICAL_TO_UPSTREAM  engine/src/kernels/cpu/expert_layout.cpp
IDENTICAL_TO_UPSTREAM  engine/include/strata/kernels/cpu/expert_layout.hpp
IDENTICAL_TO_UPSTREAM  engine/cmake/strata_gpu_engine.cmake
IDENTICAL_TO_UPSTREAM  engine/cmake/backends/cuda.cmake
```

The merge changed **none** of them, so the merge introduced nothing here. This is a **static finding from
reading the code**, confirmed by the linker's own message: `expert_layout()` is defined in
`engine/src/kernels/cpu/expert_layout.cpp:24`, and that translation unit is not in the `strata-device`
target's link line (`engine/cmake/strata_gpu_engine.cmake:23`-`:24` links only `strata_core`).

### 8.2 It is not in the release engine

The release build's target list is `strata` and `strata_kq` and nothing else
(`tools/packaging/engine_targets.sh`), and the upstream CI's own CUDA matrix builds the `strata` target
(`.github/workflows/backends.yml:63`-`:94`). `strata-device` is a **diagnostic** executable
(`--selftest`, `engine/cmake/strata_gpu_engine.cmake:1346`), not the engine that serves.

So the defect is **outside** the release engine's build and outside the engine this ACT qualified. The
release engine `strata` **built and linked successfully** (section 4), and it carries `sm_61` and nothing
else.

### 8.3 The complete set of failed targets

The full-target build was continued with `-k 0` (keep going after a failure), so that the whole tree's
failures could be counted instead of only the first one. The **complete** set of failed targets is four,
and **none of them is the release engine**:

```text
FAILED: pinned_shared_test
FAILED: strata-concurrent
FAILED: strata-load
FAILED: strata-overlap
```

All four are the `strata-device` executable and the test targets that run it. The release engine is
untouched, and its bytes are the bytes of the qualified build:

```text
$ sha256sum .../strata
0f5686d872b78b5451813d3c6d9ac4c5c70b8194d05c39be95db92821bf8cb23  strata
```

The same digest as the qualified build in section 4 - the later full-target build did not change it.

### 8.4 What this ACT does about it

It **records** it. The fix is upstream's: either the `strata-device` target must link
`strata_kernels_cpu` (where `expert_layout()` lives), or `pinned.cu` must not call into the CPU kernels'
layout. This ACT does not patch upstream's build for an auxiliary diagnostic target, does not change the
merge, and does not claim the full-target build is clean.

The finding is left in the **unresolved defects** of the exit report, marked as an **upstream** defect in
an auxiliary target, so that it is not mistaken for a regression of the merge.
