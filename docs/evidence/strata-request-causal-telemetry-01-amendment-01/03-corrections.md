# 03 - The corrections, one by one

## G1 - the Prometheus measurement integrity

* The store keeps the durations in **seconds** and the **real cumulative bucket counts**
  (`serve/reqtelemetry/metrics.py: observe_duration`). The record's `timing_ms` stays in milliseconds - the
  section is named after its unit - and the conversion happens **once**, where the observation is made.
* The exporter prints the store's own bucket counts (`serve/prometheus.py: telemetry`). It does not invent a
  distribution any more.
* The bucket edges have **one** authority: `DURATION_BUCKETS` in `serve/reqtelemetry/metrics.py`, imported by the
  exporter, so the two cannot drift apart.
* A duration that is negative or not finite is **not observed**: it is not a duration, and it is not a zero.

The mandatory witness (2 000 ms, 20 000 ms, 120 000 ms): `sum_seconds` 142.0, `count` 3, buckets 0.001 → 0,
1.0 → 0, 2.5 → 1, 5.0 → 1, 30.0 → 2, 120.0 → 3, +Inf → 3.
(`serve/test_telemetry_integrity.py: HistogramIntegrity.test_the_mandatory_witness`)

## G2 - the end-to-end request correlation

* The engine's receipt is **bound** to the request that asked for it: `apply_engine` compares the echoed `rid`
  with the record's own id.
* A **foreign** receipt (`rid` of another request) is not attached: the record keeps its own measurements, says
  `instrumentation_error`, and the aggregates stay clean - the numbers never reach the counters.
* A receipt with **no** id (an older engine) leaves the correlation explicitly unavailable
  (`identity.engine_invocation_id`), never an asserted join.
* The invocation's identity carries the ordinal: `<rid>#<n>` for the n-th native invocation of the request.
* The engine's id is only sent when the telemetry is on: with the telemetry off the DONE line is byte-identical
  to the release's.

## G3 - the null semantics and the conservation

* `derive_disposition` compares with `is None`, never with truthiness: a `null` reuse gives `unknown`; a
  **measured** zero gives `match_without_usable_state`; a measured reuse gives `full_hit` or `partial_hit`.
* The sum identity has **three** states: `satisfied`, `violated`, `unevaluated`. An unevaluated identity (a
  cancelled request, a missing measurement) is never reported as satisfied.
* The non-prefix reuse is a documented **structural zero** (Strata's execution path reuses a contiguous prefix
  only - `include/strata/program/reqtelemetry.hpp`, `TokenAccounting::non_prefix_reused`), so the identity can be
  evaluated instead of being left unevaluated for every request.
* A broken identity sets the record's quality to `partial` and names the problem in
  `measurement_quality.accounting.problems`. No measurement is ever adjusted to make an identity come out right.

## G4 - the production measurement wiring

* The rendered prompt is measured at the template render; the submitted prompt at the engine's admission. They
  are two numbers, and the record says which is which.
* The requested output budget is what the client asked for; the effective one is what the context's room
  allowed. Both are measured where they happen.
* The generated tokens are the engine's count; the emitted tokens are what the client received.
* The durations come from request-local **monotonic** clocks: the record carries its own `perf_counter` start,
  and the wall-clock timestamps are for reporting only.
* The first token is the first **token** the client saw - not a header, a keep-alive or a prompt-progress event.
* The identity (model, build, engine instance) is written **after the model was selected**.
* Where an exact measurement is not available without changing the inference semantics, the field stays `null`
  with an explicit reason (`timing_ms.template_render` is the example: the render and the tokenization are one
  pass).

## G5 - the physical HTTP lifecycle ownership

* The engine's completion only fills the **measurements**. It never finalizes the record.
* One boundary finalizes it: the physical HTTP request's own end (`Service._seal_telemetry`, called from the
  handler's `finally`). It runs for every accepted request - answered, refused, cancelled while queued,
  disconnected or failed - and produces **exactly one** receipt.
* The states are `completed`, `cancelled`, `failed` and `rejected`; at quiescence
  `accepted = completed + cancelled + failed + rejected` and `inflight = 0`.
* A request that never reached the engine keeps no invented native work.

## G6 - the aggregation and the bounds

* The cache-reuse ratio's numerator and denominator come from the **same** eligible population (the requests
  whose reuse accounting is complete); the coverage is published beside it
  (`strata_cache_reuse_ratio`, `strata_telemetry_accounting_coverage`, `cache_reuse` in the summary).
* The engine's eviction counter is counted per engine instance: the counter never falls and never counts the
  same eviction twice.
* The evidence writer's drops, failures and incomplete shutdown flushes are published (the summary's `evidence`
  and `strata_telemetry_evidence_dropped_total` / `..._failures_total`).
* The evidence queue is bounded by **records and bytes**; the store is bounded by records and bytes.
* With the telemetry off nothing is allocated: no receipt, no evidence writer, no `rid=` on the engine's
  commands.

## G7 - the HTTP contract and the browser integrity

* The request id, the client id, the lifecycle filter, the disposition filter, the page size and the cursor are
  validated; a refused input is a **400 with a message**, never an empty page.
* A cursor names the server that wrote it and the moment it was written: another server's cursor and an expired
  one are refused. An expired cursor never impersonates an exhausted collection.
* The record's own `accounting` section is in the schema, so the browser and `curl` read the same contract.

## G9 - the modularity and the hygiene

`serve/reqtelemetry.py` (1 044 lines) became a package, one responsibility per module:

```
serve/reqtelemetry/
    vocabulary.py   the enumerations, the limits, the schema version
    record.py       the canonical record and its helpers
    accounting.py   the disposition and the conservation identities
    correlation.py  the native receipt and the request it belongs to
    schema.py       the JSON Schema and its checker
    store.py        the bounded store and the process-lifetime counters
    metrics.py      the duration histograms the exporter reads
    evidence.py     the metadata-only JSONL evidence
    server.py       the server's side (the store, the evidence, the lifecycle helpers)
```

`serve.reqtelemetry` imports the same names as before: `from serve.reqtelemetry import RequestRecord, ...` and
`from serve import reqtelemetry as rt` both keep working. The package is named `reqtelemetry` and not `telemetry`
because `serve/telemetry.py` (the hardware sampler) already exists.
