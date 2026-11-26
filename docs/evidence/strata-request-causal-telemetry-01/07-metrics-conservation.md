# 07 - The metrics conservation (W5, W7)

## What the Prometheus extension adds, and what it does not touch

| | |
|---|---|
| **Touched** | nothing that exists |
| **Added** | `strata_requests_total`, `strata_prompt_*_tokens_total` (six), `strata_generated_tokens_total`, `strata_cache_restore_attempts_total`, `strata_cache_restore_failures_total`, `strata_cache_evictions_total`, `strata_telemetry_dropped_records_total`, `strata_telemetry_retention_evictions_total`; the histograms `strata_queue_duration_seconds`, `strata_cache_lookup_duration_seconds`, `strata_cache_restore_duration_seconds`, `strata_prefill_duration_seconds`, `strata_decode_duration_seconds`, `strata_time_to_first_token_seconds`, `strata_request_duration_seconds`; the gauges `strata_requests_in_flight`, `strata_requests_queued`, `strata_telemetry_retained_records`, `strata_telemetry_retained_bytes`, `strata_telemetry_available` |
| **Unchanged** | the JSON `/metrics` shape, the content negotiation, `vllm:*`, `llamacpp:*`, the `strata:` families |

The exporter's own regression test (`serve/test_prometheus.py`) still passes: `Ran 43 tests ... OK` for
`serve.test_prometheus` + `serve.test_reqtelemetry`.

## The conservation between the record and the counters

The counters are the **sum of the records** the store has seen since the server started. The store is bounded and
not durable, but the counters are not: they are the process-lifetime totals.

The identity the store keeps:

```
counters.prompt_tokens_submitted  == sum(record.prompt.submitted_tokens)
counters.prompt_tokens_matched    == sum(record.prompt.matched_prefix_tokens)
counters.prompt_tokens_reused     == sum(record.prompt.reused_prefix_tokens)
counters.prompt_tokens_evaluated  == sum(record.prompt.evaluated_tokens)
counters.prompt_tokens_replayed   == sum(record.prompt.replayed_tokens)
counters.prompt_evaluation_work_tokens == sum(record.prompt.evaluation_work_tokens)
counters.generated_tokens         == sum(record.generation.generated_tokens)
counters.requests_total           == the number of records
```

**A measurement that is null contributes nothing.** A counter only moves when the number exists: `_count_locked`
tests `isinstance(value, int)`. An unavailable measurement is not counted as a zero, so the counters never claim
work that was not measured.

`test_the_counters_do_not_fall_when_a_record_is_evicted` proves the other half: after 20 requests into a
5-record store, `requests_total` is still 20 and `prompt_tokens_evaluated` is still 20.

## The buckets

The duration histograms use `TELEMETRY_BUCKETS`, which reaches **an hour**:

```
0.001 0.005 0.01 0.025 0.05 0.1 0.25 0.5 1.0 2.5 5.0 10.0 30.0 60.0 120.0 300.0 600.0 1200.0 3600.0
```

A prefill of a long context takes minutes. A bucket set that ended at 20 s (the request-latency set) would put
every long prefill in the same bucket and hide the difference between a 30 s and a 300 s prefill.

**The buckets are cumulative and the store keeps the sum and the count, not the per-bucket counts.** The exporter
therefore reports the total count in every bucket: a bucket never claims an observation that did not happen, and
the `_count` says how many observations there really were. The shape is coarse; the count and the sum are exact.
This is stated in the code next to the exporter, so nobody reads the buckets as a distribution.

## An unavailable duration is not observed as a zero

`_observe_locked` only observes a duration that exists. A histogram with no observation has **no family at all**
in the exposition - not a family of zeros. A scrape that shows `strata_prefill_duration_seconds_count 0` means
"nothing was measured"; a family that is absent means the same thing, and the absence is not mistaken for a
zero-valued measurement.

## The labels

Only bounded enumerations:

| Label | Where |
|---|---|
| `model_name` | the existing one, on every family |
| `outcome`, `cache_disposition`, `cache_source`, `reason_code` | permitted by the ACT; the current exporter uses none of them, because the counters are totals |

**No request id, no session, no engine instance, no prompt, no user, no error message, no dynamic model identity**
appears in a label. A label's value is drawn from a fixed vocabulary, so the series count is bounded.
