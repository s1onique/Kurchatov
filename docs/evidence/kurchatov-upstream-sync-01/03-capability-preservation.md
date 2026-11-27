# 03 - Capability preservation

Every capability the Kurchatov revision owned, its source authority in the merged tree,
what upstream offers in its place, and the strategy and witness that hold it.

`LOCAL_SOURCE_AUTHORITY` names the file in the **merged** tree that now carries the
capability. `UPSTREAM_EQUIVALENT` names what upstream's pinned revision already had.

## The capability table

| Capability | LOCAL_SOURCE_AUTHORITY | UPSTREAM_EQUIVALENT | CONFLICTING_UPSTREAM_CHANGES | INTEGRATION_STRATEGY | REQUIRED_WITNESS |
|---|---|---|---|---|---|
| Native build and architecture compatibility | `engine/cmake/backends/cuda.cmake` (upstream's own) | the same file: `STRATA_EXPERIMENTAL_SM60`, the `sm_52` floor, the `sm_120` default | upstream lowered the floor from `sm_60` to `sm_52` and added Maxwell | **ADOPT_UPSTREAM_EQUIVALENT** (upstream's is a superset) | `08-build-matrix.md` |
| Pascal-specific corrections | `engine/cmake/backends/cuda.cmake` + `engine/include/strata/kernels/dp4a.hpp` (upstream's own) | the same | none conflicting | **PRESERVE_UNCHANGED** | the `sm_61` compile in `08-build-matrix.md` |
| Blackwell-specific corrections | `engine/cmake/backends/cuda.cmake` (upstream's own) | the same (`sm_120`, `sm_120a`, `sm_121`) | none conflicting | **PRESERVE_UNCHANGED** | the `sm_120` compile in `08-build-matrix.md` |
| Kurchatov build and executable identity | `terminal/serve/web/app.js` (`renderBuildId`, `buildIdText`), `terminal/serve/web/index.html` (`#build-id`), `terminal/serve/web/monitor.html`, `terminal/serve/web/monitor.js`, `terminal/serve/server.py` (`build_identity`) | upstream has the **same** identity surface (`st-header__build` CSS, `monitor.js` `build-id`) | upstream's `app.js` had no build identity; upstream's `index.html` linked the PolyStrata brand | **RECONCILE_BOTH** | `tools/test_kurchatov_identity.py` |
| Native cache diagnostics | `engine/include/strata/program/cache_diag.hpp`, `engine/src/program/cache_diag_*.cpp`, `engine/src/program/generate.cpp` (the collector) | **none** - upstream has no `STRATA_CACHE_DIAG` | upstream replaced the cache's `best()` with `holds()` and added the SSD tier | **PORT_TO_UPSTREAM_BOUNDARY** | `tools/test_cache_diag_log.py`, `cache_diag_test`, `cache_diag_engine_test`, `cache_diag_regress_test` |
| Native request telemetry | `engine/include/strata/program/reqtelemetry.hpp`, `engine/src/program/reqtelemetry_*.cpp`, `engine/src/program/generate.cpp` (19 ported hunks) | **none** - upstream has no request telemetry | upstream's `generate.cpp` grew from 15 000 to 23 800 lines; the DONE line gained fields | **PORT_TO_UPSTREAM_BOUNDARY** | `reqtelemetry_test`, `tools/test_reqtelemetry_roundtrip.py` |
| Native invocation identity propagation | `engine/src/program/generate.cpp` (`rid=`), `terminal/serve/server.py` (`request_key`, `set_request_id`) | **none** | upstream's `sampling_keys` gained the `hy4` parameter | **PORT_TO_UPSTREAM_BOUNDARY** | `test_telemetry_amendment02.py`, `test_reqtelemetry.py` |
| HTTP request lifecycle | `terminal/serve/server.py` (`_finish_telemetry`, `_seal_telemetry`, the queue paths) | upstream's own request lifecycle | upstream added `QueueCancelled`/`QueueWaitExpired`, `ContextOverflow`, the hold-aware sampler | **RECONCILE_BOTH** | `test_telemetry_amendment03.py`, `test_telemetry_amendment02.py` |
| Telemetry schema v3 | `terminal/serve/reqtelemetry/schema.py`, `terminal/serve/reqtelemetry/vocabulary.py`, `docs/telemetry/strata-request-telemetry-{2,3}.schema.json` | **none** | - | **PRESERVE_UNCHANGED** | `test_telemetry_amendment01_final.py::SchemaResourceIdentity`, `tools/test_reqtelemetry_schema.py` |
| Transactional store accounting | `terminal/serve/reqtelemetry/store.py` | **none** | - | **PRESERVE_UNCHANGED** | `test_telemetry_store_commit.py`, `test_telemetry_store_commit_correction.py` |
| Evidence writer | `terminal/serve/reqtelemetry/evidence.py` | **none** | - | **PRESERVE_UNCHANGED** | `test_telemetry_evidence_writer.py` |
| Prometheus exporter | `terminal/serve/prometheus.py` | upstream's `terminal/serve/prometheus.py` **already carries the canonical telemetry metrics** | upstream adopted the metric families | **ADOPT_UPSTREAM_EQUIVALENT** (verified equivalent) | `terminal/serve/test_prometheus.py` (6 passed) |
| Web telemetry inspector | `terminal/serve/web/telemetry.html`, `telemetry.js`, `telemetry_accounting.js`, `index.html` (the Telemetry tab), `app.js` (the tab list), `app.css` (the view rule) | upstream's own web app (`index.html`, `app.js`, `app.css`, `monitor.js`) | upstream added the Experts tab/view and the i18n spans | **RECONCILE_BOTH** | `tools/test_telemetry_web_inspector.py`, `tools/test_telemetry_web_accounting.py`, `tools/test_telemetry_web_status.py` |
| Tests and mutation witnesses | `terminal/serve/test_reqtelemetry.py`, `test_telemetry_*.py` (10 files), `tools/test_telemetry*mutations.py` (7 files) | upstream's own `terminal/serve/test_*.py` | upstream moved `serve/` to `terminal/serve/` and `src/` to `engine/src/` | **PORT_TO_UPSTREAM_BOUNDARY** (paths and the `sys.path` setup adapted) | all of them - see `07-integration-verification.md` |
| Historical evidence | `docs/evidence/strata-request-causal-telemetry-01*/`, `docs/evidence/strata-telemetry-atomic-store-commit-01*/`, `docs/forensics/*` | **none** | upstream has its own `docs/bench-results/` | **PRESERVE_UNCHANGED** (byte-identical) | the SHA256SUMS in `09-exit-report.md` |
| Local recovery workspace exclusion | `.gitignore` (`/.kurchatov-acts/`) | upstream's `.gitignore` | upstream extended the ignore list | **RECONCILE_BOTH** (both blocks kept) | `git status` shows `.kurchatov-acts/` untracked-and-ignored |

## The population invariant

The telemetry's accounting invariant is unchanged by the integration:

```
dispatched = accounted + missing + unresolved
```

It is enforced by `terminal/serve/reqtelemetry/store.py` (the terminal aggregation) and
`terminal/serve/reqtelemetry/accounting.py` (the admission rules), and it is checked by
`test_telemetry_integrity.py` (38 passed) and `test_telemetry_store_commit.py`.

## Null versus measured-zero

Unchanged: a measurement that was not taken is `null` in the record and contributes **no**
Prometheus sample. A measurement that was taken and was zero is `0`. The rules live in
`terminal/serve/reqtelemetry/accounting.py` (`admit_count`, `mark_unavailable`) and
`terminal/serve/reqtelemetry/metrics.py` (`observe_duration`), and
`test_telemetry_amendment03.py` checks both directions.

## What upstream superseded, and the equivalence that was established

* **The Prometheus exporter.** Upstream's pinned revision already carries the canonical
  telemetry metric families (`strata_requests_total`, `strata_cache_reuse_ratio`,
  `strata_telemetry_accounting_coverage`, the duration histograms with the same bucket
  edges). The local's `serve/prometheus.py` was therefore **not** ported over upstream's:
  the two would have been duplicate families with the same names. Upstream's version was
  adopted, and `terminal/serve/test_prometheus.py` (6 passed) and
  `test_telemetry_integrity.py` confirm the exposition and the admission rules.
* **The build identity in the web app.** Upstream carries the same `st-header__build`
  element, the same `monitor.js` reader and the same `build_identity()` helper. Only
  `app.js` and `index.html` lacked it; the local's implementation was ported onto
  upstream's files (the brand became `Kurchatov`, the build id stayed the deployed
  artifact's).
* **The conversation cache's `best()`.** Upstream added `holds()` beside `best()`. The
  local's `candidates()` (the diagnostics' view of the same walk) was added beside both,
  so the reported selection is still the selection the engine made.

## Deferred capabilities

| Capability | Why deferred | Authority |
|---|---|---|
| Telemetry for the **additional upstream engines** (`strata-poly`, `strata-glm`, `strata-hy4`, `strata-inkling`) | upstream added engine implementations that have no equivalent request telemetry. The ACT forbids inventing telemetry for them. Their measurements are published as **unavailable**, not as zero. | `terminal/serve/reqtelemetry/accounting.py` (`mark_unavailable`) |
| The upstream **SSD conversation-cache tier** in the cache diagnostics | upstream's SSD tier (P2) has its own admission path; the local's diagnostics were written against the RAM tier's decision boundary. The diagnostics report the RAM tier's decision; the SSD tier's refusal is visible in the engine's own log, not in the diagnostic event. | `engine/src/program/generate.cpp` (the collector) |
