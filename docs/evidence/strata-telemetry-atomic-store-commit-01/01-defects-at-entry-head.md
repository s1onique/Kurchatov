# ACT-STRATA-TELEMETRY-ATOMIC-STORE-COMMIT-01 - the defects at ENTRY_HEAD

The witnesses of `serve/test_telemetry_store_commit.py` were run against the ENTRY_HEAD tree, unchanged
(`git archive 0d57d20be3c29b07a469e672214066499c71493f` into a scratch directory; the witness file was the only
file added there).  Every defect of `TelemetryStore.add()` reproduces.

```text
Ran 11 tests in 0.013s

FAILED (failures=5, errors=3)
```

| Witness | Result at ENTRY_HEAD | The defect |
|---|---|---|
| `RetentionRollback.test_the_existing_evidence_survives_a_failed_aggregation` | FAIL - `AssertionError: 0 != 1 : the retained evidence was lost` | **R1**: the record was kept, and the old records evicted, BEFORE the aggregation ran.  The failed transaction of request B evicted request A's receipt, and A was never restored |
| `RetentionRollback.test_the_failed_transaction_keeps_the_sequence_and_the_bytes` | PASS | the sequence and the byte accounting of a failed transaction were already restored (the rollback undid what the transaction had done) |
| `OversizedReceiptRollback.test_the_original_exception_survives_an_oversized_receipt` | ERROR - `IndexError: pop from empty list` | **R2**: the receipt did not fit the 4096-byte budget, the retention dropped it at once, and the rollback removed a record that did not exist.  The original exception was lost |
| `OversizedReceiptRollback.test_the_previously_retained_records_are_unchanged` | ERROR - `IndexError: pop from empty list` | **R2**: the same defect, with a record that was retained before the failed transaction |
| `OversizedReceiptRollback.test_the_successful_oversized_receipt_keeps_the_retention_policy` | PASS | the documented retention policy of an oversized receipt was already correct - the witness guards it against a regression |
| `MembershipFilterRollback.test_the_failed_transaction_does_not_mark_the_engine_as_seen` | FAIL - `AssertionError: 'engine-x' unexpectedly found in <serve.reqtelemetry.store._SeenEngines object ...>` | **R3**: the engine identity was written into the membership filter inside the aggregation, so the failed transaction marked an uncommitted counter domain as previously observed |
| `ExactRetainedBytes.test_the_retained_bytes_are_the_exact_serialized_size` | FAIL - `AssertionError: 1992 != 2002 : the retained size of the record 1 is not its exact size` | **R4**: the record was measured BEFORE the sequence field was inserted |
| `ExactRetainedBytes.test_the_sequence_width_is_accounted` | ERROR - `AttributeError: type object 'TelemetryStore' has no attribute '_kept_size'` | **R4**: the exact size of the kept document was not computed at all |
| `ExactRetainedBytes.test_the_stored_records_account_for_their_own_width` | FAIL - `AssertionError: 0 != 1` | **R4**: the sequence's own width (9 -> 10, 99 -> 100) was not part of the retained size |
| `StoreCommitIdempotency.test_the_same_committed_record_is_not_committed_twice` | FAIL - `AssertionError: 2 != 1` | **R5**: the same committed record was committed again, and its measurements were counted again |
| `StoreCommitIdempotency.test_a_different_record_is_still_committed` | PASS | a guard: the idempotency must not refuse a different record |

The full output of that run is kept with this segment (`08-entry-head-witness-run.txt`).
