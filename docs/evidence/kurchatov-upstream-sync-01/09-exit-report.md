# 09 - Exit report

ACT: **ACT-KURCHATOV-UPSTREAM-SYNC-01**

```yaml
ACT_ID: ACT-KURCHATOV-UPSTREAM-SYNC-01
ENTRY_HEAD: 7ad7c531dc8f7d00bd483d9baa1270a58bf2ba06
PINNED_UPSTREAM_HEAD: 42e489d145aaf4430b54f2c58679be27d45faf17
ACTUAL_UPSTREAM_HEAD: 42e489d145aaf4430b54f2c58679be27d45faf17   # the tip IS the pin: no drift
MERGE_BASE: 3e1642161198c50ff1abed4046f4e4f476099dbb
INTEGRATION_BRANCH: act/kurchatov-upstream-sync-01
TESTED_CODE_HEAD: 74e89653e98d855d292c373075a5f1978df56a23
FINAL_HEAD: 74e89653e98d855d292c373075a5f1978df56a23

KURCHATOV_HISTORY_PRESERVED: true     # git merge-base --is-ancestor PASS
UPSTREAM_HISTORY_INTEGRATED: true      # git merge-base --is-ancestor PASS
RECOVERY_BUNDLE_VERIFIED: true         # git bundle verify -> "is okay ... complete history"
CONFLICTS_RESOLVED: 44 of 44 (28 mechanical renames, 16 by decision)

PASCAL_COMPATIBILITY: preserved - STRATA_EXPERIMENTAL_SM60 accepts sm_61; the sm_52 floor
                       is upstream's and is BELOW the local's sm_60, so nothing was lost
BLACKWELL_COMPATIBILITY: preserved - upstream's sm_120/sm_120a/sm_121 targets, unchanged
KURCHATOV_BUILD_IDENTITY: preserved - the brand and the deployed build's id, verified by
                       tools/test_kurchatov_identity.py

CACHE_DIAGNOSTICS: preserved - cache_diag_test, cache_diag_engine_test,
                   cache_diag_regress_test (3/3 ctest) and tools/test_cache_diag_log.py (9 passed)
NATIVE_TELEMETRY: preserved - reqtelemetry_test (ctest), the DONE line's encoding and the
                   token accounting's identities, on the host
INVOCATION_CORRELATION: preserved - the rid= key on the request's own DONE line, the
                   per-thread request id and the per-dispatch invocation id
TELEMETRY_SCHEMA_V3: preserved - strata.request-telemetry/3, checked against the schema file
HTTP_LIFECYCLE: preserved - the physical HTTP request's own terminal boundary
STORE_ACCOUNTING: preserved - the transactional commit and the one-shot terminal aggregation
PROMETHEUS_COMPATIBILITY: preserved - upstream's exporter already carried the canonical
                   families; the process-scoped labels and the admission rules are checked
WEB_INSPECTOR: preserved - the telemetry tab, the inspector page and its accounting helper

UPSTREAM_BASELINE: 1 failed, 512 passed, 8 skipped, 707 subtests passed (the one failure is
                   upstream's own Windows-only assertion on macOS)
KURCHATOV_BASELINE: 266 passed (the entry revision's own suite, measured twice)
INTEGRATION_TESTS: 266 passed (the Kurchatov suite, twice); 1 failed, 512 passed (the
                   upstream suite, identical to its baseline); 4/4 ctest; 6 roundtrip;
                   7/7 mutation witnesses; 7/7 tools witnesses
NEW_REGRESSION_IDENTITIES: none (four integration defects were found and fixed during the
                   merge; the final state has no new failure)
MUTATION_RESULTS: 7 of 7 OK (each still non-vacuous)

SM61_BUILD: NOT RUN - this host has no CUDA toolkit (nvcc is absent). The architecture
            rules were verified statically with CMake's own script engine: sm_61 is
            ACCEPTED with STRATA_EXPERIMENTAL_SM60=ON and REFUSED without it.
SM120_BUILD: NOT RUN - the same host limitation. sm_120 is ACCEPTED (upstream's default).
LIVE_NATIVE_QUALIFICATION: NOT PERFORMED - no GPU, no CUDA toolkit, no engine started, no
            request served. The native correctness rests on the header-only native tests and
            the writer/reader roundtrip, NOT on a live run.

DEPLOYMENT_COMPATIBILITY: the engine's and the serving layer's own build and tests are
            unaffected (they are built and run from the merged tree's paths). The
            DEPLOYMENT PIPELINE points at paths upstream moved (the root setup.py ->
            terminal/setup.py, the root Dockerfile -> tools/docker/).
REQUIRED_SUCCESSOR_INFRA_ACT: true - re-point the deployment pipeline at terminal/setup.py
            and tools/docker/. This ACT did not touch the separate infrastructure repository.

MAIN_CHANGED: false - main and origin/main are both still 7ad7c531dc8f7d00bd483d9baa1270a58bf2ba06
REMOTE_PUSHED: false
PRODUCTION_STATE_CHANGED: false - no deployment, no engine restart

DEFERRED_CAPABILITIES:
  - telemetry for upstream's additional engines (strata-poly, strata-glm, strata-hy4,
    strata-inkling): their measurements are published as unavailable, never as zero
  - the upstream SSD conversation-cache tier in the cache diagnostics: the diagnostics
    report the RAM tier's decision boundary
UNRESOLVED_DEFECTS: none critical. The two deferred capabilities above are explicit.
EVIDENCE_LOCATION: docs/evidence/kurchatov-upstream-sync-01/
FINAL_DISPOSITION: UPSTREAM_INTEGRATION_READY_FOR_REVIEW
```

## The review payload

### 1. The integration capability delta relative to the pinned upstream

**165 files changed, 44 915 insertions(+), 65 deletions(-)** (150 added, 15 modified).

The complete file list is in `candidate-vs-upstream.namestatus`; the summary is in
`02-divergence-inventory.md`. In one paragraph: the delta is the Kurchatov
request-causal telemetry (its 11 Python modules, its 10 test modules, its web inspector,
its 7 mutation witnesses, its schema files, its documentation and its historical
evidence), the native half of it (the cache diagnostics' header and four programs, the
telemetry's header and two programs, the 19 ported hunks in `engine/src/program/generate.cpp`
and the `candidates()` method in `engine/include/strata/core/conversation_cache.hpp`), and
the six native test targets in `engine/CMakeLists.txt`.

### 2. The conflict-resolution summary

44 conflicted paths: 28 were mechanical **file-location** conflicts (upstream renamed
`src/`, `serve/`, `include/`; Git's rename detection matched the local's files to their
new homes and the content was identical), and 16 needed a decision. Every decision is in
`04-conflict-resolutions.md` and `04a-server-py-resolutions.md`, each with the local
capability, the upstream change, the resolution, the preserved behavior and the
verification.

The four decisions that changed behaviour rather than a path:

* **the Prometheus exporter** - upstream's version was adopted (it already carried the
  canonical telemetry families), after establishing that equivalence;
* **the serving layer's request-timing helpers** - upstream's newer versions in
  `server_parts/core.py` were adopted (they keep the null-versus-zero rule), after the
  local's stale copies shadowed them;
* **`conversation_cache_view` and `btrace`** - the local's newer versions were kept
  (they carry the cache diagnostics and the engine's `EOS_IDS`/`FATAL_PREFIXES` split),
  so upstream's imports of those two names were dropped;
* **the SYCL engine's `generate.cpp`** - upstream's version was taken; the local never
  changed that file (its blob is identical to the merge base's).

### 3. The exact candidate revision

```text
74e89653e98d855d292c373075a5f1978df56a23
  parents: 7ad7c531dc8f7d00bd483d9baa1270a58bf2ba06  (the Kurchatov entry head)
           42e489d145aaf4430b54f2c58679be27d45faf17  (the pinned upstream head)
  branch:  act/kurchatov-upstream-sync-01
```

### 4. A compact inventory of upstream's changes relative to the old Kurchatov revision

Upstream changed **8 029 paths** against the common ancestor - the reorganization
described in `01-source-identities.md` (the native engine to `engine/`, the serving layer
to `terminal/`, the build cut into `engine/CMakeLists.txt` + `engine/cmake/`, the
container to `tools/docker/`, plus four new engine implementations, the serving layer's
own split into `server_parts/`, the i18n web app, the SSD conversation-cache tier and the
whole 6 911-commit history behind them). That change is upstream's history and is **not**
reproduced here: the review payload is the **surviving local capability delta** above.

## The three gates

```text
git merge-base --is-ancestor 7ad7c531dc8f7d00bd483d9baa1270a58bf2ba06 74e89653e...  -> PASS
git merge-base --is-ancestor 42e489d145aaf4430b54f2c58679be27d45faf17 74e89653e...  -> PASS
git diff --check 42e489d145aaf4430b54f2c58679be27d45faf17 74e89653e...               -> PASS (clean)
```

## The disposition

**UPSTREAM_INTEGRATION_READY_FOR_REVIEW.**

Both input histories are preserved in the candidate's ancestry; the required Kurchatov
capabilities are conserved with a witness for each; the conflict-resolution evidence is
complete (44 of 44); there are no unexplained integration regressions (the upstream
suite's result is identical to its baseline); there is no known unresolved critical
measurement-authority defect; and the tested source tree is bound to the committed
candidate.

It does **not** imply live native qualification (there was no GPU and no CUDA toolkit),
deployment, or authorization to advance `main`.
