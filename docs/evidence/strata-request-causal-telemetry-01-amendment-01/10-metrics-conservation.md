# 10 - The metrics conservation

## The histograms

| The check | The result |
|---|---|
| the sum is the sum of the observations, in seconds | 2 s + 20 s + 120 s = 142 s, and the scrape says `142.0` |
| the count is the number of observations | 3 |
| a bucket says how many observations were at or below it | 0.001 → 0, 1.0 → 0, 2.5 → 1, 5.0 → 1, 30.0 → 2, 120.0 → 3, +Inf → 3 |
| an unavailable duration contributes no sample | the family is absent, not a family of zeros |
| a measured zero IS a sample | 0 ms lands in the 0.001 s bucket with a sum of 0.0 |
| a negative or non-finite duration is not a sample | the family is absent |
| the retention does not move the aggregates | five records, two kept: the counters and the histograms still say five |

## The counters

| The counter | What it counts | What it does not count |
|---|---|---|
| `strata_requests_total` | every sealed record | - |
| `strata_prompt_*_tokens_total` | the tokens of the records that carried them | a request with no measurement contributes nothing (not a zero) |
| `strata_cache_evictions_total` | the **increase** of the engine's counter, per engine instance | the same eviction is never counted twice, and the counter never falls |
| `strata_telemetry_dropped_records_total` | the records the store could not keep | - |
| `strata_telemetry_retention_evictions_total` | the records evicted because the store was full | - |
| `strata_telemetry_evidence_dropped_total` / `..._failures_total` | what the evidence writer could not queue or write | - |

## The ratios

`strata_cache_reuse_ratio` and `strata_telemetry_accounting_coverage` come from the **same** eligible population:
the requests whose reuse accounting is complete. A request that has a submitted prompt but no measured reuse is
**not** in the denominator - it is in the coverage's missing part, and the coverage says how big that part is.

## The compatibility

Nothing existing was renamed, removed or redefined: the JSON `/metrics`, the content negotiation, the
`vllm:*` names, the `llamacpp:*` names and the `strata:*` names of the predecessor keep their own meaning. The
new families (`strata_cache_reuse_ratio`, `strata_telemetry_accounting_coverage`,
`strata_telemetry_evidence_dropped_total`, `strata_telemetry_evidence_failures_total`) are additive.
