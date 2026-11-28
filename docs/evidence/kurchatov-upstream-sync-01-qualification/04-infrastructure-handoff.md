# 04 - The infrastructure handoff (W5)

ACT: **ACT-KURCHATOV-UPSTREAM-SYNC-01**, execution segment `QUALIFICATION-HANDOFF`
Candidate revision: `859d62c4a7f6bf3b1942ff1c6e61e4405f91623a`

This document prepares the **successor infrastructure ACT**. It names the mandatory requirements and, for
each one, the **evidence in this repository** that the successor must satisfy it. The separate
infrastructure repository is **not mutated** in this segment: this document is the handoff, not the change.

The sibling infrastructure repository is
`/Volumes/UserData/Users/chistyakov/Projects/SPbNIX/not-so-awesome-argocd-infra-kurchatov`. Its
`ansible/roles/kurchatov_cuda_build/` is the role that builds the Kurchatov engine today, and it is the
role the successor ACT extends. Its own defaults already pin the revision by its immutable SHA
(`kurchatov_cuda_build_commit`), keep the candidate in a workspace outside the deployment's own directory,
and prove afterwards that the running service was not disturbed.

## 1. The mandatory requirements of the successor ACT

| # | Requirement | What the successor must do | The evidence in this repository |
| --- | --- | --- | --- |
| 1 | **Exact-revision source build from the new layout** | build from a checkout of the **exact** candidate revision, fetched by its immutable SHA, out of the tree the merge produced: the engine at `engine/`, the serving layer at `terminal/serve/`, the build cut into `engine/CMakeLists.txt` + `engine/cmake/`, the container at `tools/docker/` | the merge relocated the tree; the paths are `engine/CMakeLists.txt`, `engine/cmake/backends/cuda.cmake`, `engine/CMakePresets.json`, `terminal/serve/` and `tools/docker/` |
| 2 | **Separate Pascal and Blackwell build profiles** | two profiles, with the flags this ACT measured | `engine/CMakePresets.json` and `.github/workflows/backends.yml` already carry both - see section 2 |
| 3 | **A source Dockerfile or equivalent explicitly qualified build path** | the container build must be the **source** build, and it must be the path this ACT qualified | `tools/docker/Dockerfile.src` is that path; `tools/docker/Dockerfile.src.dockerignore` is its build context policy |
| 4 | **Never download an upstream release executable in place of the Kurchatov executable** | the successor must **not** use the inherited release-fetch path | **this is the inherited defect** - see section 3 |
| 5 | **Exclude the ACT artifacts, the credentials and the generated artifacts from the build context** | the build context must carry no `.kurchatov-acts/`, no `.act-worktrees/`, no local credentials and no generated artifacts | `.gitignore:109`-`:110` already excludes the two ACT folders; `tools/docker/Dockerfile.src.dockerignore` is the rest - see section 4 |
| 6 | **Preserve the existing model storage and the configuration** | the successor must not move the models and must not rewrite the run configuration | the models live outside the checkout, in the data folder; the run config is the deployment's own file |
| 7 | **Verify the native executable's source identity end to end** | the artifact must carry the revision's identity, and the check must run from the source to the binary | `engine/CMakeLists.txt` carries the project version; the build identity is in the artifact's own `BUILD.json` - see section 5 |
| 8 | **Inspect the inherited GitHub Actions workflows and the publication destinations** | the successor must know what the inherited workflows publish, and where | section 6 |
| 9 | **Preserve the incumbent artifacts and the rollback capability** | the successor must not remove what is deployed and must be able to roll back | the incumbent role's own preservation transaction (`/opt/.polystrata-engine-preserve/`) |

## 2. The two build profiles, as the repository already declares them

The two profiles of requirement 2 are **already in the repository**, in upstream's own build organization.
This ACT built the Pascal one for real (section 03 of this evidence) and read the Blackwell one out of the
same source.

`.github/workflows/backends.yml:71`-`:75` declares the matrix:

```yaml
matrix:
  include:
    - { cuda: '12.9', image: '12.9.1-devel-ubuntu24.04', archs: '60-real;61-real;70-real;86-real', sm60: 'ON' }
    - { cuda: '13.0', image: '13.0.2-devel-ubuntu24.04', archs: '75-real;86-real;120-real', sm60: 'OFF' }
```

and the build line at `:94` passes them:

```sh
"-DCMAKE_CUDA_ARCHITECTURES=${{ matrix.archs }}" -DSTRATA_EXPERIMENTAL_SM60=${{ matrix.sm60 }}
```

| Profile | Architecture | Toolkit | `STRATA_EXPERIMENTAL_SM60` | The rule |
| --- | --- | --- | --- | --- |
| **PASCAL** | `sm_61` | CUDA 12.9 | **ON** | `engine/cmake/backends/cuda.cmake:28` declares the option, `:53` **refuses** an architecture below sm_75 without it, `:76`-`:79` adds the compile definition |
| **BLACKWELL** | `sm_120` | CUDA 13.x | **OFF** | `sm_120` is upstream's own default; the `sm_120a` / `sm_121` targets are upstream's and are unchanged |

The engine's guard is the authority here (`engine/cmake/backends/cuda.cmake:52`-`:58`): an architecture below
sm_75 without `STRATA_EXPERIMENTAL_SM60=ON` is a **configure error**, not a warning.

**Preserve an existing qualified toolchain where appropriate.** The Pascal profile's toolchain on the
qualification host is CUDA **12.9.86** at `/usr/local/cuda-12.9`, and that exact toolchain is the one the
infrastructure repository's own `cuda_toolkit` role manages. The successor must not replace it with a
different 12.x and call the result the same profile.

## 3. The inherited defect of requirement 4

**The inherited publication path downloads an upstream release executable and publishes it.** This is
recorded here as the successor's first obligation.

`.github/workflows/docker-images.yml` builds the images **from the release's engine packages**:

```yaml
# .github/workflows/docker-images.yml:6
# For each flavor the job downloads the engine package from the release and checks it against the signed update feed
# (tools/docker/fetch-engines.py: the feed's Ed25519 signature, the archive's SHA-256, the manifest hash, the package signature,
# every file's hash), builds the image with tools/docker/build.sh and, only when "push" is on, pushes
#   ghcr.io/niko1221/strata:<version>-<flavor>   and   ghcr.io/niko1221/strata:latest-<flavor>
```

The script behind it says the same in its own words (`tools/docker/publish.sh`, the header):

> 1. `tools/docker/fetch-engines.py` downloads the engine package from the release (a GitHub release URL, or
>    `--source`) and checks it against the signed update feed

So the inherited path puts an **upstream release's binary** into a container image and publishes that image
under the Kurchatov name. Requirement 4 forbids exactly this.

**The successor's obligation:** the published image must carry the **Kurchatov executable**, built from the
Kurchatov source at the pinned revision. The source path already exists in this repository and is the
correct one: `tools/docker/Dockerfile.src` compiles the engine from the source in the image
(`tools/docker/Dockerfile.src:44`-`:56`, the `cmake` line with `-DSTRATA_EXPERIMENTAL_SM60=$sm60` and
`-DCMAKE_CUDA_ARCHITECTURES=${real};${last}-virtual`), and it takes `STRATA_COMMIT` as a build argument so
the image carries the revision's identity.

The successor must therefore **stop the release-fetch path from publishing the Kurchatov images**. The
minimal, honest change is to point the workflow at the source Dockerfile and to remove the fetch step from
the publishing path. The successor ACT decides how; this ACT records the obligation and the evidence.

## 4. The build context policy of requirement 5

The build context of the source image is `tools/docker/Dockerfile.src.dockerignore`. It already excludes the
generated artifacts: `.git`, `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, the built engine folders
(`/terminal/engine/`, `/terminal/engine-cuda12/`, `/engine-cuda12/`, `/engine-sycl/`), the build directories
(`/build/`, `/build*/`), `/dist/`, `/packs/`, `/mtp/`, `/models/`, `/Strata-data/`, the runtime data
(`/data/install/`, `/data/state/`, `/data/home/`, `/data/Strata-data/`), the vendored llama.cpp
(`engine/third_party/llama.cpp/`, `terminal/third_party/llama.cpp/`), the archives
(`engine/third_party/*.zip`), `*.done`, `*.log`, `strata-*.json`, `strata-*.txt`, `run-*.sh` and
`run-*.bat`.

**What the successor must add**, because the merged tree introduced them and the inherited list predates
them:

| Path | Why it must be excluded |
| --- | --- |
| `/.kurchatov-acts/` | the local ACT execution artifacts; they are already in `.gitignore:109`, and a build context must never carry them |
| `/.act-worktrees/` | the ACT worktrees; already in `.gitignore:110` |
| the local credentials | the API key and the sops secrets never belong in a build context |
| the generated artifacts of the new layout | the `engine/` and `terminal/` build outputs that the merged layout can produce in place |

The rule the successor must follow is the general one: **the build context carries the source and nothing
else**. A file that the build does not read must not be in it, and a file that the build reads must be in
it - the engine's source and the vendored third party are in, and everything the operator produced is out.

## 5. The source identity of requirement 7

The native executable's identity must be verifiable **end to end**: from the source that was checked out,
through the compiler that built it, to the bytes that run.

The identity has three parts, and the successor must check all three:

| Part | Where it comes from | What the successor checks |
| --- | --- | --- |
| the revision | the checkout's own `git rev-parse HEAD` | it equals the pinned SHA, and the worktree is clean |
| the source fingerprint | the upstream's own `source_hash(ENGINE_SOURCES)`, computed by the upstream's own `setup.py` | it is the fingerprint of the *same* checkout the binary was built from |
| the compiler and the architecture | the compiler that ran, and the **device code the binary carries** | the binary's own embedded architecture targets are the ones the profile declares |

The third part is the one that catches a substituted binary: the architecture targets are read out of the
**linked executable**, not out of the build command. Section 03 of this evidence records how that was done
for the Pascal profile, and the successor must do the same for Blackwell.

The infrastructure role's own `BUILD.json` template already carries the first two
(`kurchatov_cuda_build_commit`, `kurchatov_cuda_build_source_hash`) and the architecture
(`kurchatov_cuda_build_cuda_architecture`); the successor must add the **verification** that the binary's
own embedded targets match, which is what requirement 7 asks for.

## 6. The inherited workflows and the publication destinations of requirement 8

The merged tree carries upstream's workflows in `.github/workflows/`. The successor must know what each of
them does, because one of them publishes.

| Workflow | What it does | The successor's obligation |
| --- | --- | --- |
| `docker-images.yml` | **builds the images from the release's engine packages and pushes them to `ghcr.io/niko1221/strata`** (`:6`, `:9`, `:104`) | the publication destination is **upstream's own registry**; requirement 4 forbids publishing an upstream binary under the Kurchatov name. The successor must change the path **and** decide the destination |
| `backends.yml` | compiles the engine for the CUDA matrices (`:63`-`:94`), the HIP, the SYCL and the Metal backends | the two CUDA profiles of requirement 2 live here; the successor may reuse them or drive the equivalent profiles itself |
| `check.yml`, `scripts-test.yml`, `docs.yml`, `snapshot.yml`, `terminal-minimal-server.yml`, `terminal-portable-monitor.yml`, `intake.yml`, `reopen.yml`, `title-area.yml` | the upstream's own checks and the repository's own automation | the successor must not disable them by accident; they are the regression surface of the merge |

The publication destination that the successor must decide: the inherited one is
`ghcr.io/niko1221/strata` (`docker-images.yml:44`, `tools/docker/publish.sh`'s default). A Kurchatov image
carrying a Kurchatov executable must not be pushed into **upstream's** namespace.

## 7. What this ACT did not do

* It **did not** mutate the separate infrastructure repository. Every path under
  `not-so-awesome-argocd-infra-kurchatov/` is unchanged; the successor ACT owns that change.
* It **did not** publish anything, push anything, or activate anything.
* It **did not** change a single upstream default and **did not** remove a feature: the envelope of
  section 01 of `01-qualification-envelope.md` is a *deployment profile*, not a change to the tree.
