# ACT-STRATA-TELEMETRY-ATOMIC-STORE-COMMIT-01-CORRECTION-01 - the non-vacuity

Each correction is reversed IN MEMORY ONLY, one at a time, and the witness that guards it has to fail.  Nothing
is written to the repository's files: the reversal is a patch of the running process, and it is undone when the
test ends.

```text
python tools/test_telemetry_store_commit_correction_mutations.py
Ran 2 tests in 0.002s

OK
```

| Mutation | The reversal | The witness that must fail | What it showed |
|---|---|---|---|
| `test_the_failed_aggregation_is_aggregated_again` | the one-shot refusal is gone, so the retry of a failed aggregation aggregates the record again | `TerminalAggregationIsOneShot.test_the_failed_aggregation_is_not_aggregated_again` | `AssertionError` - the same invocation is accounted a second time and the population is counted twice |
| `test_the_store_ownership_is_not_enforced` | the ownership boundary is gone, so a record of another store is taken here | `StoreOwnership.test_a_record_of_another_store_is_refused` | `AssertionError` - the foreign store returns the other store's committed receipt instead of refusing it |

The mutation suites of the earlier segments still pass, unchanged:

| Suite | Result |
|---|---|
| `tools/test_telemetry_mutations.py` | 12 tests, OK |
| `tools/test_telemetry_closure01_mutations.py` | 9 tests, OK |
| `tools/test_telemetry_amendment01_mutations.py` | 8 tests, OK |
| `tools/test_telemetry_amendment03_mutations.py` | 8 tests, OK |
| `tools/test_telemetry_amendment01_final_mutations.py` | 7 tests, OK |
| `tools/test_telemetry_store_commit_mutations.py` | 5 tests, OK |
| `tools/test_telemetry_store_commit_correction_mutations.py` | 2 tests, OK |
