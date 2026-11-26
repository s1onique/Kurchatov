# 11 - The exit report (ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01)

## The identity of the work

```
ACT_ID:         ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01
REPOSITORY:     s1onique/Kurchatov
TARGET_ENGINE:  strata
PRIORITY:       P0
ENTRY_HEAD:     5b0e549b762d9eac8b360dc34365e7ba8557efb0
BRANCH:         main
TRACKED_DIRT:   none at entry (see 00-entry-state.md)
```

## The result

```
SOURCE_AUTHORITY_INVENTORY   DONE  (01-source-authority-inventory.md, source-backed, with the line numbers
                                   checked against the entry commit)
NATIVE_TELEMETRY             DONE  (the engine measures the cache state and the model execution and reports it
                                   on the request's own DONE line; NOT COMPILED here - no CUDA toolkit)
REQUEST_CORRELATION          DONE  (the request's own id travels with the request: rid= on the GEN line, echoed
                                   back on the DONE line; a thread-local, so parallel slots each carry their own)
HTTP_API                     DONE  (/v1/telemetry/status, /summary, /requests, /requests/{id}; read-only,
                                   bounded, metadata-only, on the existing port)
WEB_INTERFACE                DONE  (/telemetry: the overview, the recent-request table, the request inspector)
PROMETHEUS_COMPATIBILITY     DONE  (additive only: the JSON /metrics, the content negotiation, the vLLM names
                                   and the llama.cpp names are untouched)
STRUCTURED_EVIDENCE          DONE  (the JSONL log: metadata only, a background writer, a bounded queue, the
                                   drops counted, flushed on the way down)
PRIVACY                      DONE  (no prompt, no answer, no reasoning, no header, no key, no token id, no hash;
                                   the evidence is checked against the schema's key list)
AUTHENTICATION               DONE  (the request-level endpoints fail closed without a key on a shared listener)
RETENTION_BOUNDS             DONE  (a record count AND a byte ceiling; the counters never fall when a record is
                                   evicted)

CACHE_ACCOUNTING_CONTROLS    PARTIAL  (the record's rules and the witnesses are proven; the native cache
                                         controls are NOT_EXECUTED - no CUDA toolkit, no GPU)
CANCELLATION_CONTROLS        PARTIAL  (the server's lifecycle is proven; the native cancellation is NOT_EXECUTED)
CONCURRENCY_CONTROLS         PARTIAL  (the design is proven - the id is a thread-local, the store is locked; the
                                         native parallel case is NOT_EXECUTED)
NON_VACUITY_WITNESSES        DONE  (five mutations, each applied to a copy and reverted; each one fails its
                                   witness - see 04-test-evidence.md)
T19_WITNESS                  DONE  (the engine's own writer program gates its DONE line the way the engine
                                   does, and the roundtrip test drives it with the switch off)
PROTOCOL_PARITY              DONE  (the streaming path is unchanged; the whole existing suite passes)
PERFORMANCE_PARITY           NOT_EXECUTED  (no GPU on this host)

PASCAL_BUILD                 NOT_EXECUTED  (no CUDA toolkit, no Linux/CUDA host)
PASCAL_LIVE                  NOT_EXECUTED
BLACKWELL_BUILD              NOT_EXECUTED
BLACKWELL_LIVE               NOT_EXECUTED

PRODUCTION_STATE_CHANGED     NO  (the deployment repository was not touched; no engine was restarted; the
                                   running Kurchatov instance was not rebuilt or restarted)
UNRESOLVED_DEFECTS           none known in the parts that were executed
DEFERRED_WORK                the native qualification and the performance parity (see below)
EVIDENCE_LOCATION            docs/evidence/strata-request-causal-telemetry-01/
FINAL_DISPOSITION             PARTIAL_NATIVE_QUALIFICATION
```

## Why PARTIAL_NATIVE_QUALIFICATION and not READY_FOR_LIVE_QUALIFICATION

`READY_FOR_LIVE_QUALIFICATION` requires "passing applicable deterministic tests" and "successful required
source/build checks". The **required build check** (the CUDA engine) did not run: this host has no CUDA toolkit
and no GPU. The implementation is complete and the deterministic checks pass, but the engine's own build was not
verified here.

`ACCEPTED_NATIVE_QUALIFIED` additionally requires "successful native cache controls and performance parity on
every required and authorized target platform" - neither was possible here.

`PARTIAL_NATIVE_QUALIFICATION` is the honest disposition: **which platforms and controls remain unqualified**
is exactly what this ACT leaves open.

| Unqualified | Why | What qualifies it |
|---|---|---|
| the CUDA engine's build (SM61, SM120) | no `nvcc` here | a Linux/CUDA machine: `cmake -DSTRATA_ENABLE_CUDA=ON` |
| T01-T07, T13, T14 (the native cache controls) | no GPU here | the same, with the engine built |
| T19's byte-identical DONE line | no engine to run | the same |
| W8 (the performance parity) | no GPU here | the same, with the two arms |
| the browser rendering of the telemetry page | no browser here | a manual look |

## The commit sequence

The changes are one commit per concern, in the order below, so a reviewer can read them one at a time.

| # | The commit | What it holds |
|---|---|---|
| 1 | the native telemetry's encoding and its tests | `include/strata/program/reqtelemetry.hpp`, `src/program/reqtelemetry_test.cpp`, `src/program/reqtelemetry_roundtrip.cpp`, `CMakeLists.txt` |
| 2 | the engine reports the telemetry on the request's own DONE line | `src/program/generate.cpp` |
| 3 | the canonical record, the store and the evidence log | `serve/reqtelemetry.py` |
| 4 | the server's side: the record, the API, the Prometheus extension | `serve/server.py`, `serve/prometheus.py` |
| 5 | the web view | `serve/web/telemetry.html`, `serve/web/telemetry.js`, `serve/web/index.html`, `serve/web/app.js`, `serve/web/app.css` |
| 6 | the tests | `serve/test_reqtelemetry.py`, `tools/test_reqtelemetry_roundtrip.py`, `tools/test_reqtelemetry_schema.py` |
| 7 | the documentation and the evidence | `docs/TELEMETRY.md`, `docs/telemetry/`, `docs/evidence/strata-request-causal-telemetry-01/` |
| 8 | the tests' isolation fix and the checksums | `serve/test_reqtelemetry.py`, `docs/evidence/.../SHA256SUMS` |

## What was NOT changed

| | |
|---|---|
| the cache selection, the retention, the eviction policy | the telemetry observes the decision; it does not make it |
| the checkpoints, the conversation cache | same |
| the sampling, the quantization, the kernels | outside the ACT's scope |
| the `/metrics` JSON shape, the vLLM names, the llama.cpp names | the Prometheus work is additive |
| the API monitor | it captures content; the telemetry is metadata-only and independent of it |
| the deployment repository (`.kurchatov-acts/`) | it was there at entry; it was not read, not written and not committed |
| `strata-poly`, the ClineMM and Basalt workstreams | outside the ACT's scope |
| the production instance | no rebuild, no restart, no configuration change |

## How to check this ACT

On a machine with the dependencies (`jinja2`, `psutil`, `regex`):

```bash
python -m unittest serve.test_reqtelemetry -v      # the telemetry's own suite
python -m unittest serve.test_prometheus -v         # the exporter (unchanged behaviour, new families)
python -m unittest discover -s serve -p 'test_*.py' # the whole server suite
python tools/test_reqtelemetry_schema.py            # the schema on disk is the schema in the code
python tools/test_reqtelemetry_roundtrip.py         # the engine's writer against the server's reader
```

And the native parts (no CUDA needed):

```bash
g++ -std=c++20 -Iinclude -o /tmp/reqtelemetry_test src/program/reqtelemetry_test.cpp && /tmp/reqtelemetry_test
g++ -std=c++20 -Iinclude -o /tmp/reqtelemetry_roundtrip src/program/reqtelemetry_roundtrip.cpp
```

On a CUDA machine, the first thing is to build the engine: `cmake -DSTRATA_ENABLE_CUDA=ON -B build && cmake --build build`.
That is the step this host could not take.
