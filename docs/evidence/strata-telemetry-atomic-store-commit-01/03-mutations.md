# ACT-STRATA-TELEMETRY-ATOMIC-STORE-COMMIT-01 - the non-vacuity

Each correction is reversed IN MEMORY ONLY, one at a time, and the witness that guards it has to fail.  Nothing
is written to the repository's files: the reversal is a patch of the running process, and it is undone when the
test ends.

```text
python tools/test_telemetry_store_commit_mutations.py
Ran 5 tests in 0.003s

OK
```

| Mutation | The reversal | The witness that must fail | What it showed |
|---|---|---|---|
| `test_the_retention_commits_before_the_aggregation` | the record is kept and the old records are evicted BEFORE the aggregation, and the rollback removes the record again (the predecessor's ordering) | `RetentionRollback.test_the_existing_evidence_survives_a_failed_aggregation` | `AssertionError` - the evidence that was retained is evicted by a failed transaction |
| `test_the_rollback_removes_a_record_that_does_not_exist` | the same predecessor's ordering | `OversizedReceiptRollback.test_the_original_exception_survives_an_oversized_receipt` | `IndexError: pop from empty list` - the rollback removes a record that the retention already dropped, and the original exception is lost |
| `test_the_failed_transaction_marks_the_engine_as_seen` | the engine identity is written into the membership filter at once, and not at the commit | `MembershipFilterRollback.test_the_failed_transaction_does_not_mark_the_engine_as_seen` | `AssertionError` - the failed transaction marked the engine as previously observed |
| `test_the_sequence_field_is_not_accounted` | the retained size is measured before the sequence field is inserted | `ExactRetainedBytes.test_the_retained_bytes_are_the_exact_serialized_size` | `AssertionError` - the retained size is short by the sequence field |
| `test_the_committed_record_is_committed_again` | a record that is already committed is committed again | `StoreCommitIdempotency.test_the_same_committed_record_is_not_committed_twice` | `AssertionError` - the same measurement is counted twice |

The predecessor's mutation suites still pass, unchanged:

| Suite | Result |
|---|---|
| `tools/test_telemetry_mutations.py` | 12 tests, OK |
| `tools/test_telemetry_closure01_mutations.py` | 9 tests, OK |
| `tools/test_telemetry_amendment01_mutations.py` | 8 tests, OK |
| `tools/test_telemetry_amendment03_mutations.py` | 8 tests, OK |
| `tools/test_telemetry_amendment01_final_mutations.py` | 7 tests, OK |
| `tools/test_telemetry_store_commit_mutations.py` | 5 tests, OK |
