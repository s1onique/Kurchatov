# 06 - The non-vacuity (G10)

Every P0 correction has a witness, and every witness has a **reversal** that makes it fail. The reversals are
in-memory patches of the running process (`tools/test_telemetry_mutations.py`): no file of the repository is
edited, and no mutation code is left in the production tree.

| The mutation | What it reverses | The witness that must fail |
|---|---|---|
| `HISTOGRAM_BUCKET_FABRICATION` | the exporter's real bucket counts → every bucket carries the total count | `HistogramIntegrity.test_the_mandatory_witness` (a 120 s observation in the 1 s bucket) |
| `HISTOGRAM_UNIT_CONVERSION_REMOVED` | the conversion of the milliseconds into seconds | the same witness (the sum is 142 000, not 142) |
| `FOREIGN_NATIVE_ID_ACCEPTED` | the receipt's `rid` check | `Correlation.test_a_foreign_id_is_not_applied` |
| `NULL_REUSE_INTERPRETED_AS_ZERO` | the `is None` comparison in the disposition | `NullSemantics.test_a_null_reuse_is_not_a_zero` |
| `CONSERVATION_CHECK_BYPASSED` | the conservation check | `NullSemantics.test_the_non_closing_accounting_is_reported` |
| `OUTPUT_BUDGET_NOT_WIRED` | the writing of the requested budget | `ProductionWiring.test_the_requested_and_the_effective_budget_are_different_numbers` |
| `WALL_CLOCK_USED_FOR_DURATION` | the monotonic clock of the total duration | `ProductionWiring.test_the_durations_come_from_a_monotonic_clock` |
| `TERMINAL_RECEIPT_LOST` | the finalization of the record | `LifecycleOwnership.test_every_accepted_request_produces_exactly_one_receipt` |

```bash
$ /usr/bin/python3 tools/test_telemetry_mutations.py
........
----------------------------------------------------------------------
Ran 8 tests in 0.001s

OK
```

Each test asserts that the mutated behaviour **fails** the witness: the assertion is `assertNotEqual` (or
`assertIsNone`) on the mutated result, so a mutation that did not change the outcome fails the test.
