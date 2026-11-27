# 05 - Upstream baseline (the pinned revision, on its own)

The pinned upstream revision `42e489d145aaf4430b54f2c58679be27d45faf17` was checked out
into its own isolated worktree (`.act-worktrees/polystrata-upstream`) and tested there,
before any Kurchatov code was merged into it.

## The upstream build and source organisation (what the integration had to fit)

| Aspect | Upstream's arrangement at the pin |
|---|---|
| Root `CMakeLists.txt` | **removed** - cut into `engine/CMakeLists.txt` + `engine/cmake/*.cmake` (`strata_geometry`, `strata_ggml`, `backends/cpu`, `backends/quant`, `backends/cuda`, `backends/hip`, `strata_gpu_engine`, `strata_poly`) |
| Root `Dockerfile` | **removed** - moved to `tools/docker/Dockerfile` and `tools/docker/Dockerfile.src` |
| Native engine | `engine/` (`src/`, `include/strata/`, `metal/`, `sycl/`, `spark/`, `third_party/strata-llama`, `third_party/strata-ggml`) |
| Serving layer | `terminal/` (`serve/`, `setup.py`, `strata.py`, `strata_cli/`, `strata_control/`, `crates/`, `tests/`, `tools/`) |
| Additional engines | `strata-poly`, `strata-glm`, `strata-hy4`, `strata-inkling` (upstream added these; the pin's HEAD commit is "Merge PR 331: Inkling 2 on AMD") |
| Engine protocol | the same `GEN`/`T`/`DONE`/`BDONE`/`BADM` line protocol; upstream added `read=`/`drafts=` key=value pairs to the `BDONE` line and a `--lookup-chain` suffix to `DONE` |
| Serving-layer split | `terminal/serve/server.py` (10 696 lines) + `terminal/serve/server_parts/` (`base`, `core`, `engines`, `http_api`, `openai_api`, `anthropic_api`, `end_tokens`) |
| Cache diagnostics | **none** - upstream has no `STRATA_CACHE_DIAG` |
| Request telemetry | **none** - upstream has no `strata.request-telemetry/*` contract |
| Monitoring and web assets | `terminal/serve/web/` (`app.js`, `app.css`, `components.css`, `tokens.css`, `index.html`, `monitor.html`, `monitor.js`, `experts.js`, `i18n.js`, `locales/`) |
| Dependency declarations | `terminal/requirements.txt`, `requirements-build.txt`, `requirements-dev.txt`, `requirements-monitor.txt`, `requirements-nvfp4-local.txt` |
| CUDA architecture handling | `engine/cmake/backends/cuda.cmake`: `CMAKE_CUDA_ARCHITECTURES` defaults to `120`; `STRATA_EXPERIMENTAL_SM60=ON` allows `sm_60`/`sm_70`; the floor is `sm_52` (Maxwell); `sm_120`/`sm_120a`/`sm_121` for Blackwell |
| Test and CI infrastructure | `engine/CMakeLists.txt` (`STRATA_BUILD_TESTS`, `STRATA_BUILD_CONVERSATION_TESTS`), `engine/CMakePresets.json` (`cpu-check`, `cpu-check-native`, `cuda-compile`, `hip-compile`), `.github/workflows/{backends,check,docker-images,docs,scripts-test,snapshot,terminal-minimal-server,terminal-portable-monitor}.yml`, `tools/check/` |

## Upstream's own test baseline

The upstream serving-layer tests were run in the upstream worktree, on the pinned
revision alone:

```
terminal/serve/test_server.py
terminal/serve/test_prometheus.py
terminal/serve/test_lifecycle.py
terminal/serve/test_request_accounting.py
terminal/serve/test_web_api_key.py
terminal/serve/test_monitor.py
```

Result on the pinned revision: **1 failed, 512 passed, 8 skipped, 707 subtests passed**
(166 s).

The single failure is:

```
terminal/serve/test_server.py::VisionTempFiles::test_no_console_window_on_windows
```

It is a **Windows-only** assertion (`winjob.py`'s console-window rule) evaluated on
macOS. It is a **baseline failure**, not an integration regression: it fails identically
on the pinned revision with no Kurchatov code present.

## The upstream engine's own build baseline

`engine/CMakeLists.txt` configures cleanly with the CPU preset's flags
(`-DSTRATA_BUILD_TESTS=ON -DSTRATA_BUILD_CONVERSATION_TESTS=ON -DSTRATA_NATIVE_EXPERTS=OFF`):

```
-- strata: compiled geometry flash_next (default)
-- strata tests: ON - cpu (gpu tests not registered: neither STRATA_ENABLE_CUDA nor STRATA_ENABLE_HIP is on)
-- Configuring done / -- Generating done
```

The engine's `STRATA_BUILD_CONVERSATION_TESTS` block (upstream's own) is where the
Kurchatov native test targets were ported.
