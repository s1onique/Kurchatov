# ACT-STRATA-TELEMETRY-ATOMIC-STORE-COMMIT-01-CORRECTION-01 - the defect at the previous head

The witnesses of `serve/test_telemetry_store_commit_correction.py` were run against the previous head
(`git archive 76d44be439aac8474d150e16ac76830900b2c1cf` into a scratch directory; the witness file was the only
file added there).  The defect reproduces, and so does the missing ownership boundary.

```text
Ran 8 tests in 0.083s

FAILED (failures=4)
```

## The retry of a failed aggregation

A request dispatched ONE native invocation.  The real aggregation ran, and then it failed: the dispatched
population of the record was resolved as MISSING evidence.  The same record was then offered to the store again.

```yaml
after_failure:
  dispatched: 1
  accounted: 0
  missing: 1
  unresolved: 0

after_retry:
  dispatched: 1
  accounted: 1
  missing: 1
  unresolved: 0
```

The same invocation is ACCOUNTED and MISSING at the same time: the identity `dispatched = accounted + missing +
unresolved` no longer holds (1 != 1 + 1 + 0).  The failed aggregation had already resolved the population, and
the retry aggregated the record a second time without removing that resolution.

## The witnesses that fail at the previous head

| Witness | Result at the previous head | The defect |
|---|---|---|
| `TerminalAggregationIsOneShot.test_the_failed_aggregation_is_not_aggregated_again` | FAIL | the retry is not refused: the same invocation is accounted again |
| `TerminalAggregationIsOneShot.test_the_refused_retry_changes_nothing_at_all` | FAIL | the retry moves the counters |
| `StoreOwnership.test_a_record_of_another_store_is_refused` | FAIL | another store's committed record is taken: its receipt is returned to the foreign store, and the foreign store counts it |
| `StoreOwnership.test_the_failed_record_of_another_store_is_refused` | FAIL | the same, for a record whose aggregation failed elsewhere |

The other four witnesses are guards: they hold before the correction and after it.

The full output of that run is kept with this segment (`07-previous-head-witness-run.txt`).
