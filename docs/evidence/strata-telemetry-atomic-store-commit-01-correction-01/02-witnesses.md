# ACT-STRATA-TELEMETRY-ATOMIC-STORE-COMMIT-01-CORRECTION-01 - the witnesses

The witnesses are `serve/test_telemetry_store_commit_correction.py`.  They use the existing test infrastructure:
the production path (`RequestRecord`, `apply_engine`, `TelemetryStore.add`) and the same deterministic fault
injection as the segment before (the store's own `_count_locked` runs, and the exception comes after it).

```text
python -m unittest serve.test_telemetry_store_commit_correction
Ran 8 tests in 0.072s

OK
```

## The terminal aggregation is one-shot

`TerminalAggregationIsOneShot.test_the_failed_aggregation_is_not_aggregated_again`: the failure, and then the
retry of the same record through the store's own API.

| Requirement | The witness asserts it |
|---|---|
| the retry is refused | `ValueError` reaches the caller |
| the population conserves | `dispatched == accounted + missing + unresolved`, and the four numbers are `(1, 0, 1, 0)` before and after the retry |
| the failed record is not kept | `store.records == []` and `store.bytes == 0` |

`TerminalAggregationIsOneShot.test_the_refused_retry_changes_nothing_at_all`: the refused retry moves no counter,
keeps no record, does not change the byte accounting and does not move the sequence.

`TerminalAggregationIsOneShot.test_a_record_that_never_reached_the_aggregation_may_be_aggregated`: a record whose
terminal aggregation never ran is not refused - it never resolved anything.

## The store owns its records

`StoreOwnership.test_a_record_of_another_store_is_refused`: a record committed by one store and offered to
another.

| Requirement | The witness asserts it |
|---|---|
| the cross-store reuse is refused | `ValueError` reaches the caller |
| the foreign store does not aggregate it | its `native_invocations` and `native_invocations_accounted` are 0, and it keeps no record |
| the foreign store does not return the other store's receipt | `second.get(request_id)` is None, and the receipt is still exactly where it belongs - in the store that committed it |

`StoreOwnership.test_the_owning_store_keeps_its_own_receipt`: the successful same-object duplicate still returns
the SAME receipt and counts nothing twice (`native_invocations_accounted == 1`, `requests_total == 1`, one record).

`StoreOwnership.test_the_failed_record_of_another_store_is_refused`: a record whose aggregation failed in another
store is refused here too.

## The deduplication is bounded

`BoundedDeduplication.test_the_committed_identities_are_bounded`: after `COMMITTED_RECORDS_LIMIT + 5` commits the
store keeps at most `COMMITTED_RECORDS_LIMIT` committed identities, and it counted every request.

`BoundedDeduplication.test_the_deduplication_is_per_store`: the committed identities belong to the store that
committed them; another store has its own, and it counted nothing.

The bound is stated in the code and in `docs/TELEMETRY.md`: the content-based deduplication is **bounded** and
**per store**.  It protects against the **immediate** repeat of the same record.  It is **not** a protection
against an indefinite historical replay, and it is not claimed as one.

## The R1-R5 witnesses are preserved

`serve/test_telemetry_store_commit.py` is unchanged, and its eleven witnesses still pass:

```text
python -m unittest serve.test_telemetry_store_commit
Ran 11 tests in 0.013s

OK
```
