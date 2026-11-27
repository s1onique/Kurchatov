# ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 - exit report

```yaml
ACT_ID: ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01
ENTRY_HEAD: 586a720781b990c5801b346653b1887525ca1009
TESTED_CODE_HEAD: c02dc33d6d454fc310348b8e3d29a26742218fed
FINAL_HEAD: c02dc33d6d454fc310348b8e3d29a26742218fed

C1_WRITER_ACCEPTANCE: CORRECTED - the acceptance boundary is the ENQUEUE; every acceptance condition is
  revalidated under the enqueue lock.  The raced write is refused: write_result false, accepted_records 0,
  shutdown_refusals 1, outstanding_records 0.  Witness:
  serve/test_reqtelemetry.py Evidence.test_a_write_that_races_the_shutdown_is_refused_at_the_enqueue
  (deterministic barriers, no sleep).
C2_COVERAGE_DENOMINATORS: CORRECTED - the invocation population is the DISPATCHED one (a dropped receipt is
  missing evidence, so the coverage falls), and the physical request's coverage is measured against the requests
  that reached a terminal outcome (a lost terminal receipt lowers the coverage instead of shrinking the
  denominator).  Witnesses: 10 dispatched / 8 retained / 2 dropped -> coverage 0.8; 2 requests / 1 complete
  accounting receipt -> request_coverage 0.5.
C3_INVOCATION_TERMINALIZATION: CORRECTED - every native dispatch is terminalized on its OWN evidence (the
  segment carries the id of the dispatch that produced it; the expected identity comes from the dispatch
  boundary).  The earlier invocations' positional DONE fields are no longer discarded.  An accepted terminal
  receipt is never silently overwritten: an identical duplicate is ignored, a conflicting duplicate produces
  explicit instrumentation evidence.
C4_PROMPT_DOMAINS: CORRECTED - the prompt's LENGTH is not its identity: the dispatch boundary NAMES the domain
  of each dispatch ("request", "continuation", "other") - no content and no hash - and the coverage is computed
  from that name.
C5_BOUNDED_ACCOUNTING: CORRECTED - a retired engine's counter domain is not forgotten (only the DELTA of a late
  observation is counted; an unrecoverable attribution is refused and counted as unavailable), and the
  invocation byte bound is revalidated after the terminal measurements were added (a receipt that cannot fit is
  refused, the dropped bytes are published).
C6_NON_VACUITY: CORRECTED - every correction has an in-memory reversal that makes its witness fail
  (tools/test_telemetry_closure01_mutations.py, and the writer's own reversal in serve/test_reqtelemetry.py).
C7_EVIDENCE_HYGIENE: DONE - the review payload is the source-only diff against ENTRY_HEAD (01-source-only.diff);
  the historical acceptance reports were not rewritten; this package is a successor reference to them.

D1_TYPED_MEASUREMENT_ADMISSION: CORRECTED - shared typed admission (counts are whole non-negative integers,
  durations are finite and non-negative), shared by the record and the receipt; invalid values are refused, never
  clamped; the native -1 sentinel keeps its own meaning; the validity is class-aware.
D2_DISPATCH_IDENTITY_AUTHORITY: CORRECTED - OMITTED is distinguished from EXPLICITLY UNKNOWN; the terminal path
  never creates a dispatch and never resurrects a dropped receipt; the production fallback to the last retained
  receipt is gone.
D3_HTTP_MEASUREMENT_AUTHORITY: CORRECTED - the HTTP-owned counters are admitted on their own terms; a broken
  native accounting no longer suppresses them, and the store agrees with the record's own admission.
D4_NATIVE_TERMINAL_RECORD: CORRECTED - the receipt publishes its native finish reason, its effective output
  budget and its terminal state; an invocation whose evidence never arrived is "unknown", never "running".
D5_COMPLETE_INVOCATION_BOUNDS: CORRECTED - an oversized single receipt is refused, the byte bound is revalidated
  after the terminal population, the dropped bytes are published, and a serialization failure is not a zero-byte
  receipt.
D6_MEASUREMENT_QUALITY_CONSISTENCY: CORRECTED - the receipt derives its own disposition, the record publishes
  `native_correlation_complete`, the inspector shows the invocation-level evidence through the existing facts
  list, and the TTFT tooltip describes the HTTP-write boundary.
D7_WRITER_COUNTER_DOMAINS: CORRECTED - `pending_records` is its own domain and the published identity holds at
  every moment (submitted = accepted + refused + pending; at quiescence submitted = accepted + refused).
D8_NON_VACUITY: CORRECTED - the named reversals are in tools/test_telemetry_closure01_mutations.py and in
  serve/test_reqtelemetry.py.

STRICT_JSON_HTTP: PASS - every published record is `json.dumps(record, allow_nan=False)` clean.
STRICT_JSON_JSONL: PASS - the evidence writer serializes the same records.
SCHEMA_VALIDATION_INVALID_INPUT_CONTROLS: PASS - the invalid inputs are refused, so the record validates; the
  schema on disk is the schema in the code (tools/test_reqtelemetry_schema.py).

DISPATCHES_CREATED_BY_TERMINAL_PROCESSING: 0
STALE_IDENTITY_INHERITANCE: 0 - an explicitly unknown identity stays unknown.
MAXIMUM_RETAINED_INVOCATION_BYTES: 32768 (the documented byte budget; the retained receipts are re-validated
  against it after the terminal measurements).  It is a SERIALIZED-BYTE budget, not a hard Python RSS bound.
OVERSIZED_SINGLE_RECEIPT_REFUSALS: 1 per refused receipt (counted in `invocations_dropped`).

NATIVE_FINISH_REASON_WITNESS: PASS - the two invocations of one request publish "length" and "stop".
EFFECTIVE_OUTPUT_BUDGET_WITNESS: PASS - each dispatch publishes the budget it was given.
HTTP_NATIVE_ADMISSION_INDEPENDENCE: PASS - a violated native accounting no longer suppresses the HTTP counter.

REAL_DEPENDENCY_FULL_SUITE: PASS - /tmp/stratavenv/bin/python -m unittest discover -s serve -p 'test_*.py':
  1199 tests, OK (20 skipped).  The telemetry suites alone (amendment-02, amendment-03, reqtelemetry, integrity,
  closure-01): 193 tests, OK.
HOST_NATIVE_TESTS: NOT_EXECUTED - no native source was changed; the native round-trip test was not run here.
CUDA_SM61_BUILD: NOT_EXECUTED - no CUDA toolkit on this host; no CUDA source was changed.
CUDA_SM120_BUILD: NOT_EXECUTED - no CUDA toolkit on this host; no CUDA source was changed.

PRODUCTION_STATE_CHANGED: false
UNRESOLVED_DEFECTS: none of C1-C7 or D1-D8 remains open in the source.  The following are NOT claimed:
  * no live native qualification (no GPU and no CUDA toolkit on this host);
  * the Prometheus exporter does not yet publish the writer's refusal domains separately (the counters are
    published by /v1/telemetry/status and /v1/telemetry/summary, which is where the operator reads them);
  * no further native host simulation was added - the review asked NOT to add one.
EVIDENCE_LOCATION: docs/evidence/strata-request-causal-telemetry-01-closure-01/
FINAL_DISPOSITION: SOURCE_ACCEPTANCE_READY
```

## The commands that were run

```bash
# the defect against ENTRY_HEAD (the writer reverted, the witness kept)
git checkout 586a7207 -- serve/reqtelemetry/evidence.py
/tmp/stratavenv/bin/python -m unittest \
  serve.test_reqtelemetry.Evidence.test_a_write_that_races_the_shutdown_is_refused_at_the_enqueue
#   -> FAIL: AssertionError: True is not false : the raced write was accepted

# the corrected tree
/tmp/stratavenv/bin/python -m unittest serve.test_reqtelemetry.Evidence -v        # 6 tests, OK
/tmp/stratavenv/bin/python -m unittest serve.test_telemetry_closure01            # 34 tests, OK
/tmp/stratavenv/bin/python tools/test_telemetry_closure01_mutations.py           # 9 reversals, OK
/tmp/stratavenv/bin/python tools/test_reqtelemetry_schema.py                     # all checks passed
/tmp/stratavenv/bin/python tools/test_telemetry_amendment03_mutations.py         # 8 tests, OK
/tmp/stratavenv/bin/python tools/test_telemetry_web_accounting.py                # 4 cases checked
/tmp/stratavenv/bin/python -m unittest discover -s serve -p 'test_*.py'          # 1199 tests, OK (20 skipped)
```

The host interpreter has no `jinja2`; the repository's own virtual environment (`/tmp/stratavenv`) carries the
real dependencies, so the full suite ran with them.

## What was changed

* `serve/reqtelemetry/evidence.py` - the acceptance boundary is the enqueue (C1) and the writer's counter domains
  are exact (D7).
* `serve/reqtelemetry/accounting.py` - the shared typed measurement admission (D1) and the class-aware validity.
* `serve/reqtelemetry/invocation.py` - the typed admission in the receipt, the native finish reason, the prompt
  domain, the terminal state, the duplicate handling (C3, C4, D1, D4).
* `serve/reqtelemetry/record.py` - the dispatch identity authority (D2a), the explicit compatibility path
  (D2b), the invocation byte bounds (C5b, D5), the correlation completeness (D6).
* `serve/reqtelemetry/correlation.py` - the terminal path never creates a dispatch (D2b), the duplicate handling
  (C3), the native sentinel (D1).
* `serve/reqtelemetry/store.py` - the coverage denominators (C2), the HTTP authority (D3), the retired engine's
  counter domain (C5a), the prompt domains (C4).
* `serve/reqtelemetry/schema.py` and `docs/telemetry/strata-request-telemetry-2.schema.json` - the contract of
  the new fields (the file on disk and the code are the same contract).
* `serve/server.py` - the per-invocation terminalization (C3, D4), the prompt domain and the effective budget at
  the dispatch boundary (C4, D4).
* `serve/web/telemetry.js`, `serve/web/telemetry.html` - the invocation-level evidence in the EXISTING inspector
  and the TTFT tooltip (D6).
* `serve/test_reqtelemetry.py`, `serve/test_telemetry_closure01.py`, `tools/test_telemetry_closure01_mutations.py`
  - the witnesses and the reversals.

No telemetry capability was added, no framework, scheduler or cache-policy change was made, and the inference
path is untouched.
