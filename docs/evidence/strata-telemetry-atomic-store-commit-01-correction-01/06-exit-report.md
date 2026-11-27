# ACT-STRATA-TELEMETRY-ATOMIC-STORE-COMMIT-01-CORRECTION-01 - EXIT REPORT

## The heads

```yaml
ENTRY_HEAD: 76d44be439aac8474d150e16ac76830900b2c1cf
TESTED_CODE_HEAD: 2b8fb59b4287023b130cc3bac3d3d9f60c6fbd02
FINAL_HEAD: 2b8fb59b4287023b130cc3bac3d3d9f60c6fbd02
```

`REVIEWED_CODE_HEAD` of the act was `075fdcf147e23c4b0cb1f5574979330da946d875` (the R1-R5 corrections).
`EXPECTED_ENTRY_HEAD` was `76d44be439aac8474d150e16ac76830900b2c1cf`.

## The correction

```yaml
ONE_SHOT_TERMINAL_AGGREGATION: CLOSED - a failed aggregation RESOLVES the dispatched population of its record
  (the dispatches are MISSING evidence).  Aggregating that record again accounted the SAME invocation a second
  time and kept the missing resolution: dispatched 1, accounted 1, missing 1 - the identity
  `dispatched = accounted + missing + unresolved` did not hold.  The store now marks the record when it
  resolves the terminal aggregation (committed, or failed) and REFUSES the record when it is offered again.
  The retry moves nothing: no counter, no record, no byte, no sequence.
STORE_OWNERSHIP: ESTABLISHED - the store that resolves a record's terminal aggregation OWNS the record.  A
  record that belongs to another store is REFUSED (ValueError): this store never returns another store's
  committed receipt, and it never aggregates a foreign record.  The successful same-object duplicate keeps
  returning the SAME receipt and counts nothing twice.
BOUNDED_DEDUPLICATION: DOCUMENTED - the content-based deduplication of the committed records is BOUNDED
  (COMMITTED_RECORDS_LIMIT = 1024 identities) and PER STORE.  It protects against the IMMEDIATE repeat of the
  same record; it is NOT a protection against an indefinite historical replay, and it is not claimed as one.
R1_RETENTION_ROLLBACK: STILL CLOSED - the eleven witnesses of the segment before are unchanged and pass.
R2_OVERSIZED_RECEIPT_ROLLBACK: STILL CLOSED
R3_MEMBERSHIP_FILTER_ROLLBACK: STILL CLOSED
R4_EXACT_RETAINED_BYTES: STILL CLOSED
R5_STORE_COMMIT_IDEMPOTENCY: STILL CLOSED - the successful same-object duplicate is preserved.
```

## The rest of the closure

```yaml
POPULATION_CONSERVATION: HELD - dispatched = accounted + missing + unresolved, and the unresolved population is
  empty at quiescence.  Measured after the failed aggregation and its refused retry: dispatched 1, accounted 0,
  missing 1, unresolved 0 - the same numbers before and after the retry.
FULL_SUITE: FAIL_BASELINE_EQUIVALENT - 1271 tests, 4 failures, 2 errors, 12 skipped.  The suite is NOT green on
  this host: the four failures and the two errors are the pre-existing structured-output and JSON-schema cases,
  and the failure set is IDENTICAL to the ENTRY_HEAD baseline (1252 tests, the same 4 failures and 2 errors).
  The totals reconcile: 1252 + 11 (the R1-R5 witnesses) + 8 (this correction's witnesses) = 1271, and the
  number of failures and errors never moved.
MUTATION_RESULTS: 2 + 49 - the two narrow reversals of this correction each make their witness fail, and the six
  predecessor mutation suites (12 + 9 + 8 + 8 + 7 + 5) still pass.  51 tests in all, all OK.
PATCH_HYGIENE: CLEAN - the incremental source-only diff touches four paths and nothing else:
  serve/reqtelemetry/store.py (the correction), serve/test_telemetry_store_commit_correction.py (the witnesses,
  new), tools/test_telemetry_store_commit_correction_mutations.py (the reversals, new), docs/TELEMETRY.md (the
  documentation of the correction).  No native file, no build artifact, no unrelated refactoring.
PRODUCTION_STATE_CHANGED: NONE - no deployment, no engine restart, no live inference qualification, and no change
  to the deployment repositories or to .kurchatov-acts/.  The native engine (include/, src/, CMakeLists.txt) is
  untouched, so the isolated CUDA build and the native live qualification are unchanged and remain INDEPENDENT
  qualifications, to be run independently.
UNRESOLVED_DEFECTS: NONE.  The accepted telemetry gates (F2-F5, the request-local population accounting, R1-R5)
  are not reopened, and their witnesses still pass.
EVIDENCE_LOCATION: docs/evidence/strata-telemetry-atomic-store-commit-01-correction-01/
FINAL_DISPOSITION: SOURCE_ACCEPTANCE_READY
```

## The witnesses

| Witness | Result |
|---|---|
| ONE_SHOT_AGGREGATION_WITNESS | PASS - the retry of a failed aggregation is refused, and the population stays `(1, 0, 1, 0)`.  FAILS at the previous head (the retry accounts the same invocation again) |
| STORE_OWNERSHIP_WITNESS | PASS - another store's committed record is refused, and the foreign store counts nothing.  FAILS at the previous head (the foreign store takes the record and returns the other store's receipt) |
| BOUNDED_DEDUPLICATION_WITNESS | PASS - the committed identities are bounded, and they are per store |
| the eleven witnesses of R1-R5 | PASS, unchanged |

## What was not touched

* No new membership filter, no transaction framework, no persistent replay tracking, no diagnostic recovery
  protocol, and no native source mutation.
* The receipt model, the native instrumentation, the dashboard, the request-local population accounting and the
  accepted F2-F5 and R1-R5 corrections.
* The historical evidence: only a successor receipt was appended to the exit report of the segment before.  Its
  checksum was refreshed for that one file (07-exit-report.md), because the receipt changed it; the other eight
  checksums of that segment are unchanged.
