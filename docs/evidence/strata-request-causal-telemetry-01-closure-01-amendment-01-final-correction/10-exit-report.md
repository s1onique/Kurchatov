# ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 - FINAL-CORRECTION - EXIT REPORT

## The heads

```yaml
ENTRY_HEAD: 3769eed7bc82784ce9d06be78a553b2620b38329
TESTED_CODE_HEAD: 4b788abcb0694435c9ad3ddde99f3bf0716167de
FINAL_HEAD: f1a7233bdd36f3c9b7b83fde158be8657eac7f7c
```

## The five corrections

| Gate | Closed | Where |
|---|---|---|
| F1 | the population accounting is request-local, idempotent and atomic; the unresolved population is published | `serve/reqtelemetry/store.py`, `serve/reqtelemetry/record.py`, `serve/reqtelemetry/server.py` |
| F2 | the prompt-domain multiplicity is the request's own and survives the retention | `serve/reqtelemetry/record.py`, `serve/reqtelemetry/invocation.py`, `serve/reqtelemetry/store.py` |
| F3 | one normalized terminal authority | `serve/reqtelemetry/correlation.py` |
| F4 | the dashboard renders the card again | `serve/web/telemetry.js`, `serve/web/telemetry_accounting.js` |
| F5 | the current contract has its own schema resource identity | `serve/reqtelemetry/schema.py`, `docs/telemetry/strata-request-telemetry-3.schema.json` |

## The witnesses

| Witness | Result |
|---|---|
| CONCURRENT_POPULATION_WITNESS | PASS - `native_invocations: 2, native_invocations_accounted: 1, native_invocations_missing: 1`; at quiescence `dispatched = accounted + missing` and the unresolved population is empty.  FAILS at ENTRY_HEAD (`missing: 0`) |
| DISPATCH_POPULATION_IDEMPOTENCY | PASS - the second count does not count the population again.  FAILS at ENTRY_HEAD (`native_invocations: 2`) |
| DROPPED_DOMAIN_WITNESS | PASS - the surviving receipt is not the unique request-domain dispatch; the request-level coverage is refused and the cumulative native work is still counted.  FAILS at ENTRY_HEAD (`prompt_tokens_evaluated: 10`) |
| TERMINAL_STATE_DUPLICATE_WITNESS | PASS - a changed effective terminal state is a conflict.  FAILS at ENTRY_HEAD (it was an identical duplicate) |
| PARTIAL_CLASSIFICATION_DUPLICATE_WITNESS | PASS - a changed effective partial classification is a conflict.  FAILS at ENTRY_HEAD (it was an identical duplicate) |
| ACTUAL_STATUS_RENDER_WITNESS | PASS - the ACTUAL `renderStatus` writes "90.0%", "0.0%" and "—", and the coverage populations stay visible.  FAILS at ENTRY_HEAD (the card wrote nothing) |
| DISTINCT_SCHEMA_IDS | PASS - the two contracts are two resources.  FAILS at ENTRY_HEAD (both were `strata-request-telemetry-2.json`) |

## The suites

| Suite | Result |
|---|---|
| the complete real-dependency suite (`python -m unittest discover -s serve -p "test_*.py" -t .`) | 1252 tests, OK (20 skipped) |
| the telemetry mutation suites (`tools/test_telemetry_mutations.py`, `tools/test_telemetry_closure01_mutations.py`, `tools/test_telemetry_amendment01_mutations.py`, `tools/test_telemetry_amendment03_mutations.py`, `tools/test_telemetry_amendment01_final_mutations.py`) | 12 + 9 + 8 + 8 + 7 tests, all OK |
| the schema tool (`tools/test_reqtelemetry_schema.py`) | all checks passed |
| the browser presentation tools (`tools/test_telemetry_web_accounting.py`, `tools/test_telemetry_web_inspector.py`, `tools/test_telemetry_web_status.py`) | 4 cases, the inspector and 3 status cases, all checked with osascript |

The JavaScript engine of this host is `osascript` (macOS); there is no `node` here.  The witness that needs the
browser's rendering runs the ACTUAL page function against a stub DOM, not a re-implementation of it.

## What was not touched

* The native engine (`include/`, `src/`, `CMakeLists.txt`): no native file changed, so the isolated CUDA build
  and the native live qualification are unchanged.  They remain INDEPENDENT qualifications.
* The production deployment, the production engine restart and the live inference qualification: not authorized
  in this segment, and not performed.
* The historical evidence of the earlier segments, the deployment repositories and `.kurchatov-acts/`: unchanged.
* The `_SeenEngines` membership filter: not redesigned (the deferred bounded-accounting maintenance item).

## The disposition

SOURCE_ACCEPTANCE_READY.  The five corrections are closed and witnessed.  CUDA compilation, the native live
qualification and the performance parity remain independent qualifications and are not claimed here.

## CORRECTION (ACT-STRATA-TELEMETRY-ATOMIC-STORE-COMMIT-01)

The `TESTED_CODE_HEAD` of this report was stale.  It named `4b788abcb0694435c9ad3ddde99f3bf0716167de`, which is
the code head of the PREVIOUS segment (the A1-A6 corrections), and not the code that was tested in this segment.

The code that was tested here - the F1-F5 corrections, the witnesses they brought and the reversal suite - is the
commit `f1a7233bdd36f3c9b7b83fde158be8657eac7f7c`, which is also this segment's `FINAL_HEAD`.  The commit
`0d57d20be3c29b07a469e672214066499c71493f` added only the evidence documents; it changed no source file.

```yaml
ENTRY_HEAD: 3769eed7bc82784ce9d06be78a553b2620b38329
TESTED_CODE_HEAD: f1a7233bdd36f3c9b7b83fde158be8657eac7f7c
FINAL_HEAD: f1a7233bdd36f3c9b7b83fde158be8657eac7f7c
EVIDENCE_HEAD: 0d57d20be3c29b07a469e672214066499c71493f
```

The witnesses, the suites and the numbers of the report above are unchanged: they were run against the tree of
`f1a7233b`.  Nothing above is rewritten; this correction only names the revision that was tested.
