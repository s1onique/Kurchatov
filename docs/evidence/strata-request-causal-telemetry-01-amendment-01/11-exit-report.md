# 11 - The exit report (ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-01)

```
ACT_ID:         ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-01
PREDECESSOR:   ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01
REPOSITORY:     s1onique/Kurchatov
TARGET_ENGINE:  strata
PRIORITY:       P0
ENTRY_HEAD:     c45ec82846b2671673ff712009c8a85e1f034e2e
FINAL_HEAD:     2b2a9463a6e43ff909eb20d157e44a7b24727466
BRANCH:         main
TRACKED_DIRT:   none (the only untracked path is the pre-existing .kurchatov-acts/, untouched)
COMMITS_CREATED: 5 (the list is below)
```

## The gates

```
G1_PROMETHEUS_INTEGRITY     PASS  (real cumulative buckets; the milliseconds are converted once, in
                                   serve/reqtelemetry/metrics.py; the edges have one authority; a negative or
                                   non-finite duration is not observed)
G2_REQUEST_CORRELATION      PASS  (a foreign receipt is not attached and does not reach the aggregates; a
                                   receipt without an id leaves the correlation explicitly unavailable; the
                                   invocation's ordinal is in the invocation id)
G3_NULL_AND_CONSERVATION    PASS  (a null reuse gives 'unknown'; the identity has three states; the non-prefix
                                   reuse is a documented structural zero)
G4_PRODUCTION_WIRING        PASS  (the matrix of 02-field-wiring-matrix.md; the distinct quantities are
                                   measured where they happen; the durations are monotonic)
G5_HTTP_LIFECYCLE           PASS  (one authoritative terminal finalization per accepted physical HTTP request;
                                   accepted = completed + cancelled + failed + rejected; inflight = 0)
G6_AGGREGATION_AND_BOUNDS   PASS  (the ratio's numerator and denominator come from the same population; the
                                   coverage is published; the eviction counter is per engine instance; the
                                   evidence writer's drops and failures are published; the queue is bounded by
                                   records and bytes; the telemetry off allocates nothing)
G7_HTTP_AND_BROWSER_CONTRACT PASS (the inputs are validated; an expired or foreign cursor is refused; the
                                   filters that name nothing are errors)
G8_NATIVE_SOURCE_AUDIT      PARTIAL (the complete native diff is published - native-diff.txt - and the
                                   encoder's test and the roundtrip pass; the LIVE native behaviour was not
                                   re-qualified here: no engine, no GPU)
G9_MODULARITY_AND_HYGIENE   PASS  (serve/reqtelemetry/ - nine modules, one responsibility each; the import
                                   surface of serve.reqtelemetry is unchanged; git diff --check is clean)
G10_NON_VACUITY              PASS  (eight mutations, each one makes its witness fail)
```

## The rest of the exit contract

```
DEFECTS_REPRODUCED:  13 (G1a, G1b, G2, G3a, G3b, G3c, G4, G4b, G4c, G5, G6, G6b, G6c, G7, G9)
DEFECTS_CORRECTED:  all of them that are source-correctable
MUTATION_WITNESSES:  8 (tools/test_telemetry_mutations.py)
FULL_SUITE_RESULT:  see 05-suite-results.md - the corrected tree has no failure that the baseline does not have
PATCH_HYGIENE:       git diff --check c45ec828..HEAD is clean

CUDA_BUILD:          NOT_EXECUTED (no CUDA toolkit on this host)
PASCAL_LIVE:         NOT_EXECUTED
BLACKWELL_LIVE:      NOT_EXECUTED
PERFORMANCE_PARITY:  NOT_EXECUTED (no GPU here)

PRODUCTION_STATE_CHANGED: NO
UNRESOLVED_DEFECTS:       none known in the parts that were executed
EVIDENCE_LOCATION:        docs/evidence/strata-request-causal-telemetry-01-amendment-01/
FINAL_DISPOSITION:        SOURCE_CORRECTED_NATIVE_BUILD_PENDING
```

## Why SOURCE_CORRECTED_NATIVE_BUILD_PENDING

Every source-correctable gate passes and there is no known critical correctness defect in the parts that were
executed. The disposition does **not** authorize a deployment and it does not imply a native qualification: the
CUDA build (SM61, SM120), the native cache controls and the performance parity are NOT_EXECUTED here, because
this host has no CUDA toolkit and no GPU. The subsequent live qualification ACT is separately authorized.

## The environment's limit, stated plainly

The `regex` wheel is not installed on this host and there is no network. The suite was run with a **local-only**
stand-in (in `/tmp`, never committed). The nine tests that fail because of it fail **in the unmodified entry
commit as well** - the baseline run of 05-suite-results.md shows them. On a machine with the real wheel (the
repository's own setup installs it), the predecessor's evidence shows the whole suite passing.

## What was NOT changed

| | |
|---|---|
| the cache selection, the retention, the eviction policy | the telemetry observes the decision; it does not make it |
| the checkpoints, the conversation cache | same |
| the sampling, the quantization, the kernels, the scheduler | outside the ACT's scope |
| the native engine's source | byte-identical to the entry commit (the diff is published) |
| the `/metrics` JSON shape, the vLLM names, the llama.cpp names | the Prometheus work is additive |
| the API monitor | it captures content; the telemetry is metadata-only and independent of it |
| the deployment repository (`.kurchatov-acts/`) | it was there at entry; it was not read, not written and not committed |
| `strata-poly`, the ClineMM and Basalt workstreams | outside the ACT's scope |
| the production instance | no rebuild, no restart, no configuration change |

## The commit sequence

| # | The commit | What it holds |
|---|---|---|
| 1 | `a866dd47` the measurements are real, and the null is not a zero | `serve/reqtelemetry/` (the package, the split), `serve/prometheus.py`, `docs/telemetry/strata-request-telemetry-1.schema.json` |
| 2 | `f1229351` the request's life belongs to the HTTP request | `serve/server.py` |
| 3 | `c903c7f2` the view does not draw a zero | `serve/web/telemetry.js` |
| 4 | `332488bb` the witnesses of the corrections | `serve/test_telemetry_integrity.py`, `tools/test_telemetry_mutations.py`, `serve/test_reqtelemetry.py`, `tools/test_reqtelemetry_roundtrip.py` |
| 5 | `2b2a9463` the documentation of the corrections | `docs/TELEMETRY.md`, `docs/DETAILS.md` |

The evidence package itself is committed on top of them (as the predecessor did): the tree it describes is
`2b2a9463a6e43ff909eb20d157e44a7b24727466`.

## How to check this amendment

On a machine with the dependencies (`jinja2`, `psutil`, `regex`):

```bash
python -m unittest serve.test_reqtelemetry serve.test_telemetry_integrity   # the telemetry's own suites
python -m unittest serve.test_prometheus                                   # the exporter
python -m unittest discover -s serve -p 'test_*.py'                        # the whole server suite
python tools/test_reqtelemetry_schema.py                                   # the schema on disk is the schema in the code
python tools/test_reqtelemetry_roundtrip.py                                # the engine's writer against the server's reader
python tools/test_telemetry_mutations.py                                   # the non-vacuity: eight reversals
```

And the native parts (no CUDA needed):

```bash
g++ -std=c++20 -Iinclude -o /tmp/reqtelemetry_test src/program/reqtelemetry_test.cpp && /tmp/reqtelemetry_test
```

On a CUDA machine, the first step is the engine's build: `cmake -DSTRATA_ENABLE_CUDA=ON -B build && cmake --build build`.
That is the step this host could not take.
