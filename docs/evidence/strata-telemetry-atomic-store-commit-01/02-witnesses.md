# ACT-STRATA-TELEMETRY-ATOMIC-STORE-COMMIT-01 - the witnesses

The witnesses are `serve/test_telemetry_store_commit.py`.  The failure is injected **after the real aggregation
ran** (the store's own `_count_locked` runs, and the exception comes after it), so the rollback is measured
against a transaction that really counted something.

```text
python -m unittest serve.test_telemetry_store_commit
Ran 11 tests in 0.014s

OK
```

## R1 - the existing evidence survives a failed transaction

`RetentionRollback.test_the_existing_evidence_survives_a_failed_aggregation`: the store keeps ONE record
(`max_records=1`).  Request A completes and is retained.  Request B runs the real aggregation and then fails.

| Requirement | The witness asserts it |
|---|---|
| A remains retained and unchanged | `len(store.records) == 1`, the record is A's, and it is the SAME dictionary the first `add` returned |
| B is not retained | `store.get("b") is None` |
| the retained bytes describe A exactly | `store.bytes` is unchanged, and it is the length of A's UTF-8 serialized document |
| the retention-eviction counter is unchanged | `counters["retention_evictions"]` is unchanged |
| B's dispatch is counted as missing | `native_invocations == 2`, `native_invocations_accounted == 1`, `native_invocations_missing == 1` |
| the previously accepted measurements are unchanged | the prompt, the native work, the request total and the histograms are unchanged |

`RetentionRollback.test_the_failed_transaction_keeps_the_sequence_and_the_bytes`: the sequence, the byte
accounting, the retained records and the receipt counter survive the failed transaction.

## R2 - the oversized receipt rolls back cleanly

`OversizedReceiptRollback.test_the_original_exception_survives_an_oversized_receipt`: the store is configured
with the supported 4096-byte budget and the receipt is larger than it.

| Requirement | The witness asserts it |
|---|---|
| the original exception is preserved | `RuntimeError("the aggregation failed")` reaches the caller |
| the rollback does not remove a record that does not exist | `store.records == []` and `store.bytes == 0` |
| the sequence and the retention accounting stay consistent | `store.seq == 0` and `counters["retention_evictions"] == 0` |
| the dispatch population conserves | `dispatched == accounted + missing + unresolved` (1 == 0 + 1 + 0) |
| the previously retained records are unchanged | the records and the bytes of a store that already held one are unchanged |

`OversizedReceiptRollback.test_the_successful_oversized_receipt_keeps_the_retention_policy`: the documented
policy of a receipt that does not fit is unchanged - it is dropped at once, the store stays inside its bounds,
and the request itself is committed and counted.

## R3 - the membership filter is rolled back

`MembershipFilterRollback.test_the_failed_transaction_does_not_mark_the_engine_as_seen`: an engine that was
never seen here reports 10 cumulative evictions; the aggregation fails; the next request of the SAME engine
reports 11.

```yaml
authoritative_evictions_after_failure: 0
authoritative_evictions_after_success: 11
unattributed_evictions_after_success: 0
```

The witness also asserts that the engine is not in the membership filter after the failure, and that no
attribution was refused (`cache_evictions_attribution_unavailable == 0`).

## R4 - the exact retained bytes

`ExactRetainedBytes.test_the_retained_bytes_are_the_exact_serialized_size`: for every retained record, the
store's size is the length of the document it keeps, and `store.bytes` is their sum.

`ExactRetainedBytes.test_the_sequence_width_is_accounted`: the size of the kept document at the sequences 9, 10,
99 and 100 is the exact size, and the width transitions cost exactly one byte.

`ExactRetainedBytes.test_the_stored_records_account_for_their_own_width`: in the store itself, the record 10 is
one byte larger than the record 9, and the record 100 is one byte larger than the record 99.

## R5 - the store commit is idempotent

`StoreCommitIdempotency.test_the_same_committed_record_is_not_committed_twice`: a physical request is completed
and the same committed record is inserted again through the store's own API.

```yaml
requests: 1
eligible_requests: 1
invocations: 1
eligible_invocations: 1
coverage: 1.0
request_coverage: 1.0
```

The counters and the histograms are the same before and after the repeated insertion.

`StoreCommitIdempotency.test_a_different_record_is_still_committed`: a guard - three different records are
committed as usual.

## The predecessor's rollback witness, strengthened

`serve/test_telemetry_amendment01_final.py::ConcurrentPopulation.test_a_failed_aggregation_commits_nothing`
now runs the REAL aggregation before the injection, and it also asserts that the failed record was not kept.
