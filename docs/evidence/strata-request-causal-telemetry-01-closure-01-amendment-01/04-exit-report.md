# The exit report of ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01

```yaml
ACT_ID: ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01
ENTRY_HEAD: a0daa4c710bf3502342dcc14ee72d595b4a062c6
TESTED_CODE_HEAD: d9a7d61af9688f6f4e81f8093aa58ef63ce65ef2
FINAL_HEAD: 49012a2d90b2df44dc3c431c597282a3eef283ba
CODE_TREE_BINDING: d9a7d61af9688f6f4e81f8093aa58ef63ce65ef2

A1_INDEPENDENT_NATIVE_POPULATION: NOT_ADDRESSED
A2_PROMPT_DOMAIN_CONSERVATION: NOT_ADDRESSED
A3_IMMUTABLE_TERMINAL_EVIDENCE: NOT_ADDRESSED
A4_ENGINE_COUNTER_DOMAIN_RETIREMENT: NOT_ADDRESSED
A5_SERIALIZATION_AND_RETENTION: PARTIAL (A5a CLOSED; A5b, A5c NOT_ADDRESSED)
A6_BROWSER_PRESENTATION: NOT_ADDRESSED
A7_NON_VACUITY_AND_EVIDENCE: PARTIAL (the A5a reversal is executed; the other nine reversals are NOT implemented)

LOST_PARENT_NATIVE_COVERAGE: NOT_EXECUTED
REPEATED_PROMPT_COVERAGE: NOT_EXECUTED
CONFLICTING_DUPLICATE_MUTATIONS: NOT_EXECUTED
FOREIGN_DUPLICATE_MUTATIONS: NOT_EXECUTED
FORGOTTEN_ENGINE_COUNTER_DELTA: NOT_EXECUTED
STRICT_JSONL: PASS
STRICT_JSON_HTTP: PASS (the payload witness; the live HTTP witness is SKIPPED - jinja2 is not installed)
WIRE_SCHEMA_VERSION: UNCHANGED (strata.request-telemetry/2 - A5c was not addressed)
INVOCATION_INSPECTOR_WITNESS: NOT_EXECUTED

REAL_DEPENDENCY_FULL_SUITE: BLOCKED (jinja2 is not installed; 61 pre-existing import errors, unchanged by this run)
HOST_NATIVE_ROUNDTRIP: NOT_EXECUTED (the engine binary is not built here)
MUTATION_RESULTS: PASS (the NONFINITE_JSONL_ACCEPTED reversal fails the witness when reversed)
CUDA_SM61_BUILD: NOT_EXECUTED
CUDA_SM120_BUILD: NOT_EXECUTED

PRODUCTION_STATE_CHANGED: NO (no deployment, no restart, no live inference)
UNRESOLVED_DEFECTS: A1, A2, A3, A4, A5b, A5c, A6 and the remaining A7 reversals
EVIDENCE_LOCATION: docs/evidence/strata-request-causal-telemetry-01-closure-01-amendment-01/
FINAL_DISPOSITION: PARTIAL_CORRECTION
```

## Why the disposition is PARTIAL_CORRECTION and not SOURCE_ACCEPTANCE_READY

The amendment names seven gates.  The runtime authority scoped this run's mutation to the evidence writer module
and its writer test file, so only A5a could be closed.  The other gates (A1, A2, A3, A4, A5b, A5c, A6) and
nine of the ten named targeted reversals were NOT implemented and were NOT executed.  They are reported as
NOT_EXECUTED rather than claimed.

## What was executed

```
$ python -m unittest serve.test_telemetry_evidence_writer -v
Ran 12 tests in 0.105s
OK (skipped=1)                      # the live HTTP witness skips: jinja2 is not installed

$ python tools/test_reqtelemetry_schema.py
test_reqtelemetry_schema: all checks passed

$ python tools/test_telemetry_web_accounting.py
test_telemetry_web_accounting: 4 cases checked with osascript

$ python -m unittest discover -s serve -p "test_*.py"
Ran 93 tests, FAILED (errors=61)    # the same 61 import errors as before the change (jinja2), and 12 more tests run
```

The non-vacuity reversal was executed in memory (the writer's serializer replaced by one that ignores
`allow_nan`): 6 of the writer's witnesses FAIL without the correction and pass with it.
