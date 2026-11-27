# Request telemetry

What the engine did with each request: the prompt tokens it reused, the ones it evaluated, where the reusable
state came from, and how long each stage took.

The telemetry answers one question that the Monitor tab cannot: **why did this request cost what it cost?** The
Monitor tab shows the expert cache's hit rate (the GPU's weights) and the request's speed. The telemetry shows the
*conversation cache*: the prompt's prefix that was reused, the prefix that was matched but could not be used, and
the tokens the engine had to read again.

Two authorities, kept apart:

| | The native engine | The HTTP server |
|---|---|---|
| Owns | the cache state, the token accounting, the prefill and decode time | the queue wait, the render, the tokenization, the model load, the time to the client |
| Source | the request's own `DONE` line | the server's own clock |

Neither reconstructs the other's numbers. There is no client-side reconstruction of engine internals.

## The record

One record per **physical request attempt**. Two requests that carry the same `X-Request-ID` are two records.

```json
{
  "schema_version": "strata.request-telemetry/3",
  "identity": {
    "request_id": "9ca8c311a98448e5a10827dd9cac6b7b",
    "client_request_id": "my-trace-42",
    "engine_instance_id": "pid-8123-gen-2",
    "server_instance_id": "c14ecbc49c694f2fbd08b10cfdbdcd7b",
    "engine_invocation_id": "5d0f7b1c2a9e4f6b8c3d1e0f5a6b7c8d",
    "engine_invocation_ordinal": 1,
    "slot_id": 0,
    "model_id": "qwen3.8-flash",
    "build_revision": "5b0e549b762d"
  },
  "lifecycle": {"state": "completed", "api": "openai", "received_at": 1795717079.16, "http_status": 200,
                "finish_reason": "stop"},
  "prompt": {"rendered_tokens": 246, "submitted_tokens": 246, "matched_prefix_tokens": 200,
             "reused_prefix_tokens": 200, "evaluated_tokens": 46, "replayed_tokens": 0,
             "non_prefix_reused_tokens": 0, "evaluation_work_tokens": 46,
             "first_divergent_token_index": null},
  "cache": {"source": "conversation_cache", "disposition": "partial_hit", "reason_code": "exact_match",
            "restore_attempted": true, "restore_succeeded": true, "restore_ms": 3.2},
  "timing_ms": {"prefill_wall": 41.5, "decode_wall": 210.0, "http_first_token": 55.2, "total": 268.0},
  "generation": {"requested_max_output_tokens": 512, "effective_max_output_tokens": 512,
                 "generated_tokens": 63, "emitted_tokens": null,
                 "speculative_draft_tokens": 31, "speculative_accepted_tokens": 24},
  "invocations": [
    {"identity": {"engine_invocation_id": "5d0f7b1c2a9e4f6b8c3d1e0f5a6b7c8d", "ordinal": 1,
                  "engine_instance_id": "pid-8123-gen-2", "model_id": "qwen3.8-flash",
                  "build_revision": "5b0e549b762d", "slot_id": 0},
     "state": "completed",
     "prompt": {"submitted_tokens": 246, "matched_prefix_tokens": 200, "reused_prefix_tokens": 200,
                "evaluated_tokens": 46, "evaluation_work_tokens": 46},
     "timing_ms": {"cache_lookup": 2.1, "cache_restore": 3.2, "prefill_wall": 41.5, "decode_wall": 210.0},
     "measurement_quality": {"native_correlation": "verified", "native_partial": false,
                             "measurement_valid": true,
                             "accounting": {"state": "satisfied", "valid": true, "problems": []},
                             "admission": {"complete_cache_ratio": true, "native_duration": true, ...}}}
  ],
  "measurement_quality": {"state": "partial", "unavailable_fields": {"generation.emitted_tokens": "..."},
                          "timing_authority": {...}}
}
```

The schema is [`docs/telemetry/strata-request-telemetry-3.schema.json`](telemetry/strata-request-telemetry-3.schema.json).
The historical contract is kept beside it:
[`docs/telemetry/strata-request-telemetry-2.schema.json`](telemetry/strata-request-telemetry-2.schema.json)
(JSON Schema draft 2020-12). It is checked by an executable test, so the contract on the wire and the contract in
the code cannot drift apart.

### The native invocations

One physical HTTP request can dispatch the engine **more than once**: a thinking budget wraps the reasoning up and
continues, a recovery sends the request again. Every dispatch is its own **invocation**, and every invocation owns
its own measurements, in the record's `invocations` section (ACT-...-AMENDMENT-03, G1).

* The invocation's id is generated immediately before the dispatch, and the engine echoes it back on its `DONE`
  line. The id, the ordinal, the engine instance, the model and the build revision are bound to the invocation
  **before** the dispatch, and the terminal evidence is checked against exactly that identity.
* A measurement of one invocation is **never** published under the identity of another one. A receipt that carries
  another invocation's id is refused, and the invocation that was waited for keeps its own numbers - a missing
  measurement stays `null`.
* The record's own native fields (`prompt.matched_prefix_tokens`, `cache_lookup`, ...) describe **one** invocation:
  the request's, when there was only one. With more than one they would be a summary of several prompts, so they
  are `null` and the per-invocation receipts carry the numbers.
* The request's prompt domain is the prompt the HTTP request carried. An invocation's prompt domain is the prompt
  **that dispatch** gave the engine. The positions of two different prompts are never added together and never
  published as one prompt's coverage.
* The history is bounded: at most 8 receipts and 32 KiB per request. A receipt that does not fit is **counted as a
  loss** (`measurement_quality.invocations_dropped`) and the record says so - it is never dropped silently.

### Identity

* `request_id` is the **server's** id: unique per physical attempt, never derived from the client's. It is
  echoed in the `X-Strata-Request-ID` response header, so a client can quote it in a bug report.
* `client_request_id` is the client's `X-Request-ID`, kept as a **label**. It is checked (printable ASCII,
  bounded), never used as a key, never treated as an authentication. Two requests with the same one stay two
  records.
* `engine_instance_id` changes when the engine process is restarted; `server_instance_id` when the server is.
* The engine echoes the request's id back on its `DONE` line (`rid=`), so the numbers it measures belong to that
  request **by construction** - not by timestamp proximity, not by "the most recently active request".

### The token accounting

The two prefixes are different things, and the record keeps them apart:

| Field | Meaning |
|---|---|
| `matched_prefix_tokens` | the contiguous **token-prefix match** against the candidates the engine examined, **before** the execution-state constraints. How far the tokens agreed. |
| `reused_prefix_tokens` | the contiguous prefix whose **usable execution state** was really retained or restored, so those positions were not evaluated again. |
| `evaluated_tokens` | the distinct prompt positions the engine evaluated. |
| `replayed_tokens` | the evaluated positions that were previously processed prompt material. |
| `evaluation_work_tokens` | the executed prompt-token evaluations (repeats count again). |
| `first_divergent_token_index` | the zero-based first token mismatch; `null` when there is none. |

A candidate whose **tokens match but whose state is unusable** moves the first without moving the second. That is
the case the Monitor tab cannot show, and it is what `match_without_usable_state` means.

For a fully processed prompt with a complete accounting:

```
0 <= reused_prefix_tokens <= matched_prefix_tokens <= submitted_tokens
submitted_tokens = reused_prefix_tokens + non_prefix_reused_tokens + evaluated_tokens
replayed_tokens <= evaluated_tokens
evaluation_work_tokens >= evaluated_tokens
```

These identities are **checked, never enforced**. A broken identity means the accounting was incomplete (a
cancel, a re-read), and `measurement_quality.state` says `partial` and `measurement_quality.unavailable_fields`
says why. No measurement is ever adjusted to make an identity come out right.

### The cache attribution

`cache.source` says where the reusable prefix came from: `none`, `resident_slot`, `conversation_cache`,
`restored_checkpoint`, `multiple`, `unknown`.

`cache.disposition` says what the engine did with it, derived from **evidence only** - never from a duration or a
rate:

| Disposition | When |
|---|---|
| `cold_miss` | nothing was reused |
| `full_hit` | the whole prompt was reused |
| `partial_hit` | some of it was reused |
| `match_without_usable_state` | the tokens matched but the state could not be used |
| `bypassed` | the cache was not used for this request |
| `invalidated` | the state was invalidated before it could be used |
| `unknown` | the engine did not say |

`cache.reason_code` is the engine's own reason (`exact_match`, `token_mismatch`, `steering_mismatch`,
`ineligible`, `evicted`, `absent`, ...).

**The conversation cache is not the expert cache.** The expert cache's hit rate, its RAM/file tiers and the MTP
drafts are GPU weight residency; they are not conversation-cache hits and are not reinterpreted as such.

### Measurement quality

`measurement_quality.state` is one of:

| State | Meaning |
|---|---|
| `complete` | every measurement the record carries was really measured |
| `partial` | some measurements are missing; `unavailable_fields` says which and why |
| `unsupported` | this build does not measure them |
| `instrumentation_error` | the instrumentation itself failed |

**An unavailable measurement is `null`, never `0`.** `0` is a measured zero: "the engine reused no tokens" is a
measurement; "the engine did not say" is not. A missing measurement is never inferred from a wall-clock duration.

`timing_authority` names who measured each duration, so the two are never confused:

| Authority | What it means |
|---|---|
| `native_engine` | the engine measured it, on its own DONE line |
| `http_server` | the server measured it, on the request's own monotonic clock |
| `http_server_write` | the first MEANINGFUL content was written to the client (the write boundary) |
| `http_server_observation` | the service saw a generated token (not the client's first byte) |

Three more fields say how the record may be used (ACT-...-AMENDMENT-02, G1):

| Field | Meaning |
|---|---|
| `native_correlation` | `verified` (the receipt belongs to this invocation), `unavailable` (an older engine did not echo the id), `rejected` (the receipt carried another invocation's id - none of its numbers was applied) or `not_applicable` (the request never reached the engine) |
| `native_partial` | the native figures cover ONE segment of the invocation (a batch slot's admission segment) |
| `measurement_valid` / `aggregate_eligible` | whether the record's numbers are measurements at all, and whether the record may enter the authoritative totals |

A record whose accounting is **violated**, whose measurements are **invalid** or whose receipt is **not
correlated** stays in the collection as a diagnostic receipt and contributes **nothing** to the totals. A
measurement the server owns (the submitted prompt) stays eligible even when the engine's receipt could not be
correlated.

### The admission is per measurement class

One rule for every measurement is too coarse: an uncorrelated duration and an accounting that did not close are
different problems, and each class has its own rule (ACT-...-AMENDMENT-03, G2). The record's and every
invocation's `measurement_quality.admission` says, per class, whether the measurement may enter the authoritative
totals:

| Class | It needs |
|---|---|
| `http` | the measurement itself. The server's own numbers stand on their own. |
| `native_prompt_position` | a correlated receipt, valid numbers, and an accounting that is not violated. |
| `native_execution_work` | a correlated receipt and valid numbers. An accounting that could not be **evaluated** does not exclude a measured work counter; a **violated** one does. |
| `native_duration` | a correlated receipt and a **whole** invocation. A duration is independently trustworthy: a broken token count does not turn it into a guess, and a batch slot's admission segment is not the whole invocation. |
| `cache_restore` | a correlated receipt and valid numbers. |
| `complete_cache_ratio` | a correlated receipt, valid numbers, and an accounting that **satisfied**. The ratio's denominator is "the prompts whose accounting closes". |
| `partial_diagnostic` | nothing: a partial segment's evidence is published as a diagnostic and never as the whole. |

The **coverage** of the accounting is published with both populations: the native invocations whose accounting
closed (`eligible_invocations`) and the ones whose receipt never arrived (`missing_invocations`). A lost receipt
lowers the coverage - it never improves it. The physical HTTP request's own coverage is published beside it
(`request_coverage`): the two describe different populations.

Both denominators are counted independently of the receipts that survived (ACT-...-CLOSURE-01, C2):

| Number | What it counts |
|---|---|
| `invocations` | the native invocations this request DISPATCHED - a receipt that did not fit the bounds is still an invocation, and it is in the missing population |
| `eligible_invocations` | the dispatched invocations whose accounting closed and whose receipt survived |
| `missing_invocations` | the dispatched invocations without a complete accounting - the dropped ones among them |
| `dropped_invocations` | the receipts that did not fit the record's bounds (a count and a number of bytes) |
| `request_coverage` | the requests that reached a terminal outcome and had a complete accounting, over the requests that reached a terminal outcome. A request whose terminal receipt was lost lowers the coverage; it does not leave the denominator. |

### The measurements are typed

A measurement that is not a measurement is never published (ACT-...-CLOSURE-01, D1):

| Kind | It is |
|---|---|
| a count (the token counts, the generation counters, the cumulative native counters) | a whole, non-negative integer. A bool, a fraction and a negative are refused. |
| a duration (the milliseconds) | a finite, non-negative number. A negative, a NaN and an infinity are refused. |

A refused value stays null, the record says why, and it never enters a total. It is never clamped, rounded or
coerced into a valid one. The engine's own `-1` means "not measured" - it stays null and it is not an invalid
measurement. The validity is per class: an invalid duration does not exclude the valid token counts, and an
invalid count does not exclude the valid durations.

### The native invocation's own record

Every native dispatch owns one receipt, and it is terminalized on its OWN evidence (ACT-...-CLOSURE-01, C3, D4):

| Field | Meaning |
|---|---|
| `prompt.domain` | the NAME of the prompt domain the dispatch carried: `request`, `continuation` or `other`. The prompt's LENGTH is not its identity - two different prompts of the same length are two domains, and two invocations of the same prompt are one. No content and no hash. |
| `generation.finish_reason` | the NATIVE invocation's finish reason - not the physical HTTP request's. An invocation that exhausted its output budget may be followed by a successful continuation. |
| `generation.effective_max_output_tokens` | the budget THIS dispatch was given, not the request's |
| `state` | the invocation's own terminal state. `unknown` means its terminal evidence never arrived - it is never presented as `running` at the end of a request, and it is not a failure of the inference either. |

A terminal receipt that was already accepted is never silently overwritten: an identical duplicate is ignored (and
causes no additional work accounting) and a conflicting one keeps the accepted measurements and is reported as an
instrumentation error.

## The HTTP API

Read-only, metadata-only, and on the existing port. No new service, no database, no extra listener.

| Route | What it answers |
|---|---|
| `GET /v1/telemetry/status` | the capability, the identity, the retention |
| `GET /v1/telemetry/summary` | the process-lifetime totals |
| `GET /v1/telemetry/requests` | a bounded page of the recent requests |
| `GET /v1/telemetry/requests/{request_id}` | one request |
| `GET /telemetry` | the browser view |
| `GET /metrics` | the existing metrics, with the telemetry's added |

The collection takes `limit`, `cursor`, `client_request_id`, `request_status` and `cache_disposition`:

```bash
curl -s localhost:8095/v1/telemetry/requests?limit=20 | jq '.records[0].prompt'
curl -s localhost:8095/v1/telemetry/requests/<request_id> | jq .cache
```

The page size has a hard maximum (500 by default). The cursor is stable while new requests arrive: it names the
sequence number of the last record of the previous page, so a page never repeats a record and never skips one.

An unknown request id is a `404` with a documented body. A malformed cursor or filter is a `400`.

### Access control

The request-level endpoints **fail closed** when there is no API key on a listener that is not this PC's own
loopback: an inference endpoint that lets anonymous callers in does not make the request metadata anonymous.
On the loopback they keep the server's own trust.

The responses carry `Cache-Control: no-store` when they are request-level diagnostics.

## The web view

`http://127.0.0.1:8095/telemetry` (also the **Telemetry** tab in the chat app).

* **Overview**: the engine and server identity, the build revision, the model, the telemetry's capability and
  quality, the running and waiting request counts, the prompt tokens submitted, reused and evaluated, the replay
  work, the token-weighted cache reuse ratio, the prefill and decode throughput, the TTFT, the failures and
  cancellations, and the retention and loss counters.
* **The recent-request table**: the received time, the request id and the client id, the status, the model, the
  slot, the rendered and submitted tokens, the matched prefix, the reused prefix, the evaluated and replayed
  tokens, the cache disposition, the prefill duration and throughput, the TTFT, the decode throughput and the
  finish reason.
* **The request inspector**: the exact identities, the token accounting (with a bar), the matched versus the
  usable prefix, the cache selection and restoration, the replay work, the per-stage timings with their
  authority, the generation outcome, the measurement quality and the raw metadata-only JSON.

The page warns when the matched prefix exceeds the usable prefix, when a restoration failed, when the attribution
is incomplete and when the engine reported no telemetry. **An unsupported measurement is shown as `—`, not as
`0`.**

The refresh is bounded (two seconds by default) and never overlaps. Loading or refreshing the page does not run
inference, does not change the cache policy, does not hold the model and does not load it.

## The Prometheus metrics

The existing exporter is **extended**, never changed: the JSON `/metrics`, the content negotiation, the
vLLM-compatible names and the llama.cpp-compatible names keep their own meaning.

Counters (the engine's own accounting):

```
strata_requests_total                       strata_cache_restore_attempts_total
strata_prompt_tokens_total                  strata_cache_restore_failures_total
strata_prompt_matched_tokens_total          strata_cache_evictions_total
strata_prompt_reused_tokens_total           strata_telemetry_dropped_records_total
strata_prompt_evaluated_tokens_total        strata_telemetry_retention_evictions_total
strata_prompt_replayed_tokens_total         strata_generated_tokens_total
strata_prompt_evaluation_work_tokens_total
```

Histograms (seconds; the buckets reach an hour, so a long-context prefill is not flattened into one bucket):

```
strata_queue_duration_seconds        strata_prefill_duration_seconds
strata_cache_lookup_duration_seconds strata_decode_duration_seconds
strata_cache_restore_duration_seconds strata_time_to_first_token_seconds
strata_request_duration_seconds
```

Gauges:

```
strata_requests_in_flight      strata_telemetry_retained_records
strata_requests_queued         strata_telemetry_retained_bytes
strata_telemetry_available     strata_cache_reuse_ratio
strata_telemetry_accounting_coverage
strata_telemetry_accounted_invocations
strata_telemetry_missing_invocations
strata_telemetry_request_coverage
```

`strata_telemetry_accounting_coverage` is the share of the **native invocations** whose cache-reuse accounting is
complete; `strata_telemetry_request_coverage` is the share of the **physical HTTP requests** with at least one
complete native accounting. The two describe different populations and are published separately.

The labels are bounded enumerations only. There is **no** request id, session, engine instance, prompt, user,
error message or dynamic model identity in a label.

The canonical telemetry metrics above are **process-scoped**: they carry **no** `model_name` label
(ACT-...-AMENDMENT-02, A8). A process-lifetime total does not belong to the model that happens to be selected when
the scrape happens - otherwise the work of the model that ran before a switch is published under the new model's
name. The existing compatibility metrics (`vllm:*`, `strata:*`) keep their labels and their meaning.

A duration that was not measured contributes **no sample**: a histogram's `_count` says how many observations
there really were. It is never padded with zeros.

### The histograms are real (ACT-...-AMENDMENT-01, G1)

Every `_bucket` line says how many observations were **at or below** that edge, and nothing else. A 120 s
observation is in the 120 s bucket and in `+Inf`, and **not** in the 1 s bucket. The `_sum` is the sum of the
observations **in seconds**: the record keeps its timings in milliseconds (`timing_ms`) and the store converts
them **once**, in `serve/reqtelemetry/metrics.py`. The exporter and the store share one list of bucket edges
(`DURATION_BUCKETS`), so a bucket line and the store's own accounting cannot drift apart.

A duration that is negative or not finite is not observed at all - it is not a duration, and it is not a zero
either.

### The cache-reuse ratio has both of its numbers (G6)

`strata_cache_reuse_ratio` is published together with the population it covers:

| Gauge | What it is |
|---|---|
| `strata_cache_reuse_ratio` | reused prompt tokens / submitted prompt tokens, over the requests whose reuse accounting is **complete** |
| `strata_telemetry_accounting_coverage` | the share of the requests that are in that population |

The numerator and the denominator come from the **same** eligible requests, so a request whose accounting is
incomplete cannot distort the ratio. The coverage says how much of the traffic the ratio covers. The same numbers
are in `GET /v1/telemetry/summary` under `cache_reuse`.

`strata_cache_evictions_total` is a counter: the engine's own eviction count restarts with the engine, and the
server counts the **increase** per engine instance, so the counter never falls and never counts the same
eviction twice.

## The structured evidence

With `STRATA_TELEMETRY_EVIDENCE=<path>`, every finished request is written as one metadata-only JSON object per
line (JSONL). It is written by a **background thread**, so the token path never touches the disk; the queue is
bounded and a record that does not fit is **dropped and counted**, never written synchronously.

The file carries no prompt, no answer, no reasoning, no tool arguments, no header, no key, no raw token id and
no prompt hash.

The counters for what was written, dropped and failed are in `GET /v1/telemetry/status` and in the Prometheus
metrics.

## The configuration

| Setting | Default | What it does |
|---|---|---|
| `STRATA_TELEMETRY` | `1` | `0` turns the whole thing off. The engine's `DONE` line is then byte-identical to the release's. |
| `STRATA_TELEMETRY_RECORDS` | `2048` | how many records the store keeps |
| `STRATA_TELEMETRY_BYTES` | `16777216` | the store's memory ceiling (16 MiB) |
| `STRATA_TELEMETRY_EVIDENCE` | unset | the JSONL evidence file |

The store is bounded and **not durable**: it is a window on the recent requests, and a restart empties it. The
process-lifetime counters do not fall when a record is evicted.

## The overhead

The telemetry adds no per-token JSON serialization, no GPU synchronization, no filesystem I/O and no unbounded
CPU-side growth. The engine's extra work is the candidate comparison it already does for the cache diagnostics
and the handful of counters it already keeps.

## The unsupported cases

* **A prompt read that was cut short** (a cancel): the record keeps what really happened and says the accounting
  is partial.
* **An engine that reports nothing** (an older build): the native fields are `null` and
  `measurement_quality` says the engine reported no measurements. They are never zeros.
* **The recurrent and attention state** (a hybrid model): Strata's checkpoints restore the whole session state
  (the recurrent state and the attention state together), so the record reports one restoration, not two.

## Troubleshooting

* **The telemetry view says "Off"**: `STRATA_TELEMETRY=0` in the server's environment.
* **The native fields are all `—`**: the engine did not report them. The engine's switch is `STRATA_TELEMETRY=1`
  in the **engine's** environment; the server sets it for the engine it starts.
* **"the request telemetry needs an API key on this listener"**: the server listens beyond this PC. Set an API
  key, or listen on the loopback.
* **The cache disposition says `match_without_usable_state`**: the tokens matched but the state was not usable
  (another steering mode, a different picture, an evicted checkpoint). `cache.reason_code` says which.

## The corrections of ACT-...-AMENDMENT-01

The review of the predecessor found defects in the measurement, not in the architecture. What changed:

| Where | Before | Now |
|---|---|---|
| the Prometheus histograms | every bucket carried the total count; the milliseconds were printed as seconds | real cumulative buckets, converted to seconds once, in `serve/reqtelemetry/metrics.py` |
| the native receipt | the `rid` was sent but never checked | a receipt that carries another request's id is **not** attached; the request reports an instrumentation error; a receipt with no id leaves the correlation explicitly unavailable |
| the cache disposition | a `null` reuse was read as a zero | a `null` reuse gives the `unknown` disposition; only a **measured** reuse decides |
| the conservation identity | it was checked, but a broken one and an unevaluated one looked the same | three states: `satisfied`, `violated`, `unevaluated`; an unevaluated identity is never reported as satisfied |
| the non-prefix reuse | it was left unmeasured | a documented **structural zero** (Strata reuses a contiguous prefix only), so the identity can be evaluated |
| the record's life | the engine's completion finalized the record | one authoritative finalization at the physical HTTP request's boundary: a refused, cancelled or disconnected request still gets exactly one receipt |
| the durations | some were wall-clock differences | request-local monotonic clocks; the wall-clock timestamps are for reporting only |
| the output budget | the requested and the effective budget were the same number | they are measured where they happen: the client's request and the context's room |
| the rendered prompt | the rendered count was copied from the submitted one | the rendered count is measured at the template render, the submitted count at the engine's admission |
| the cache-reuse ratio | the numerator and the denominator came from different populations | both come from the same eligible population, and the coverage is published beside it |
| the pagination cursor | it named only a sequence number | it names the server that wrote it and when: another server's cursor and an expired one are refused, never silently treated as an exhausted collection |
| the module layout | `serve/reqtelemetry.py` held everything | `serve/reqtelemetry/` holds it, one responsibility per module; `serve.reqtelemetry` still imports the same names |

With the telemetry **off** (`STRATA_TELEMETRY=0`) nothing is allocated: no receipt, no evidence writer and no
`rid=` on the engine's commands - the engine's DONE line stays byte-identical to the release's.

## The corrections of ACT-...-AMENDMENT-02

The second review found measurement and attribution defects, not an architecture that needed replacing:

| Where | Before | Now |
|---|---|---|
| the aggregates | an invalid, unattributed or out-of-a-broken-accounting measurement was counted | a measurement enters an authoritative total only when it is valid, its accounting holds and its receipt is correlated; the invalid ones stay as diagnostic receipts |
| the native receipt | it was bound to the request | it is bound to the **invocation**: a new hexadecimal id is generated for every dispatch and the echoed id is checked before ANY native number is applied |
| the queue wait | it was overwritten with the request's whole time | it is the wait, measured where it happens, and never overwritten |
| the first token | the generation loop's timestamp, published as the client's | the first **meaningful content written** is timed at the write boundary; the service's own observation is published separately, and the emitted-token count is null with a reason |
| the lifecycle | the accepted count and the terminal count came from the same insertion | the accepted count is taken at the admission, the terminal outcome before the receipt is sealed, and the receipt's delivery is counted beside them |
| the evidence writer | the flush returned true while a record was blocked; the bytes were characters | the bytes are the UTF-8 bytes, the bound counts the record being written, the flush means "every accepted record reached a terminal outcome", and the worker owns the handle |
| the pagination cursor | a cursor without an owner was accepted | a cursor without an owner, with a sequence below one, dated in the future, expired or pointing at an evicted page is refused |
| the engine's eviction counter | a smaller reading lowered the total | it is a high-water mark per engine instance: the total never falls |
| the native cumulative work | it repeated the distinct count | on the re-read path it stays **not measured** instead of publishing a smaller number than the work that happened |
| the native terminal error | a bare `ERR`, the evidence lost | the ERR line carries the telemetry the engine did measure, so the failed request keeps its correlated partial evidence |
| the browser's bar | the denominator was `reused + evaluated`; an unknown replay became a zero | the denominator is the submitted prompt, the positions nobody accounted for are shown, an unknown replay is not a measured zero, and a broken accounting gets no bar |
| the batch slot | the admission segment's figures were published as the invocation's | the record says the figures cover one segment, and they stay out of the authoritative totals |

## The corrections of ACT-...-CLOSURE-01-AMENDMENT-01

The review of the closure found population, attribution and evidence defects. What changed:

| Where | Before | Now |
|---|---|---|
| the native dispatch population | it was counted from the receipts that were **stored**: a lost terminal receipt removed the whole invocation population | it is counted at the terminal boundary, **before** the receipt is sealed: a failed seal, a failed serialization or a failed store lowers the coverage instead of shrinking the population; a request that is still running is not in it yet |
| the request's own prompt coverage | the positions of every invocation of the request's prompt domain were **summed** | the coverage is counted once: when several dispatches carried the request's own prompt, the request-level coverage is **unavailable** (the cumulative native work is counted instead, and the request says so) |
| the unknown prompt domain | an unnamed domain was admitted as the request's own when the lengths agreed | the length fallback is gone: only the **dispatch boundary** names a domain, and an unnamed one is never the request's own |
| the duplicate terminal receipt | five prompt counters were compared | the **complete** normalized terminal evidence is compared - the cache figures, the durations, the positional DONE fields, the generation counters, the partial classification, the native finish reason and the native terminal state |
| the accepted terminal receipt | a foreign or a conflicting duplicate changed it | the snapshot is committed **once**; a duplicate never updates a measurement, and the conflict is reported beside it |
| the native outcome | it was taken from the request's HTTP outcome | it is the **native dispatch's** own outcome: an invocation that failed stays failed when the request recovers, and one that completed stays completed when the HTTP delivery fails |
| the compatibility receipt | a receipt built without a dispatch could enter the native coverage | it is explicit and outside the authoritative admission: only an **actual dispatch** contributes to the dispatched population |
| the engine's eviction counter | a forgotten engine identity looked like a new one, and its whole counter was counted again | a bounded membership filter remembers that an identity was **ever** seen: a forgotten one is refused (its exact delta cannot be recovered) and the attribution loss is published |
| the evidence writer | it wrote `{"x":NaN}` | it refuses a record JSON cannot represent, through the existing serialization-refusal domain |
| the telemetry's HTTP boundary | it could write a bare `NaN` | the boundary is strict: a non-finite value is refused and the answer is a proper JSON error |
| a discarded sole invocation | the parent kept the stale mirrored measurements | the parent's mirrored native fields are cleared; the HTTP-owned fields stay |
| the wire contract | the incompatible corrections were published under the v2 identity | the historical `strata.request-telemetry/2` contract is preserved and the corrected one has its own identity: `strata.request-telemetry/3` |
| the browser's inspector | the invocation facts were built inside the page | they are built by a pure function (`serve/web/telemetry_accounting.js`), so the inspector and its witness cannot drift apart |

The witnesses are `serve/test_telemetry_amendment01.py`, the reversals are
`tools/test_telemetry_amendment01_mutations.py`, and the browser's inspector is checked by
`tools/test_telemetry_web_inspector.py`.

## The corrections of ACT-...-CLOSURE-01-AMENDMENT-01 (FINAL-CORRECTION)

A second review of the corrections above found five more defects. What changed:

| Where | Before | Now |
|---|---|---|
| the native dispatch population on a failure | the outcome was read from the **global** counters before and after the failure, so a **concurrent** request that completed in between was read as this request's own progress | the outcome is counted on the **request's own** bookkeeping: the dispatches it dispatched, less the ones its own aggregation resolved. The dispatch-population boundary is **idempotent** and the check happens inside the store's lock. At quiescence `dispatched = accounted + missing`; a dispatch whose outcome is not known yet is in the **unresolved** population (`native_invocations_unresolved`) |
| an aggregation that fails | it could commit part of its measurements and then count them again | it is **atomic**: a failure rolls the counters, the histograms and the stored record back, so nothing is partially committed and nothing is counted twice |
| the request's own prompt coverage | the uniqueness was decided by the **retained** receipts: a discarded receipt made the surviving one look unique | the multiplicity is the **request's own**, counted at the dispatch boundary: it survives the retention. When the request's own domain was carried twice - or a dispatch's domain could not be established - the exact request-level coverage is **refused**, never guessed. Retention never improves the certainty |
| the terminal evidence | the state and the partial classification were normalized from one dictionary and applied from another | there is **one** authority: the **effective** state and partial classification are resolved once, and the comparison consumes exactly the values the commit applies. A duplicate that changed the effective state or the effective partial classification is a **conflict** |
| the cache-reuse card | the RESUME-01 patch dropped the assignment to the `reuse-ratio` element, and the coverage line disappeared when the ratio was unavailable | the card's value is drawn again (`$("reuse-ratio")`, looked up the way the page looks elements up: `$` is `getElementById`), and the **coverage populations stay visible** when the ratio itself is unavailable |
| the wire contract | the current contract carried the historical resource identity | the two contracts are **two resources**: the historical `strata-request-telemetry-2.json` and the current `strata-request-telemetry-3.json` |

The witnesses are `serve/test_telemetry_amendment01_final.py`, the reversals are
`tools/test_telemetry_amendment01_final_mutations.py`, the card is checked by
`tools/test_telemetry_web_status.py`, and the schema resources by `tools/test_reqtelemetry_schema.py`.

## The corrections of ACT-...-ATOMIC-STORE-COMMIT-01

A third review looked at the store's COMMIT alone. What changed:

| Where | Before | Now |
|---|---|---|
| the retention on a failure | the record was kept (and the old records evicted) **before** the aggregation ran, so a failed transaction evicted the evidence that was already retained, and the rollback removed a record that the retention had already dropped | the retention is part of the **commit**: the record is kept and the old records are evicted only **after** the aggregation committed. A failure touches nothing that was retained, and the rollback never removes a record that does not exist |
| the engine identity on a failure | the identity was written into the membership filter **inside** the aggregation, so a failed transaction marked an uncommitted counter domain as previously observed | the identity is remembered when the transaction **commits**. The counter domain of a failed transaction stays uncommitted, and the engine's next observation is a first observation again |
| the retained size | the record was measured **before** the sequence field was inserted, so the store's byte accounting was short by the field it had just added | the retained size is the **exact** size of the document that is kept - the UTF-8 serialized representation, sequence field included. The sequence's own width is part of it (9 -> 10 and 99 -> 100 cost one byte each) |
| a record that is committed twice | the same measurement could be committed again, and counted again | a record that is already committed is **not committed again**: it is recognized by its own content, so the measurements, the histograms and the population are counted exactly once. The committed identities are bounded |

The witnesses are `serve/test_telemetry_store_commit.py`, the reversals are
`tools/test_telemetry_store_commit_mutations.py`.

## The corrections of ACT-...-ATOMIC-STORE-COMMIT-01-CORRECTION-01

A fourth review looked at the store's terminal aggregation alone. What changed:

| Where | Before | Now |
|---|---|---|
| the retry of a failed aggregation | the failed aggregation resolved the record's dispatched population as **missing** evidence, and a retry through the store's own API **accounted the same invocation again**: the population was counted twice (accounted AND missing) | the terminal aggregation is **one-shot**: a record whose aggregation failed is **refused** when it is offered again, so the population stays resolved once and `dispatched = accounted + missing + unresolved` still holds |
| the ownership of a record | the store returned the committed receipt of **another** store when such a record was offered to it | the store **owns** the records it aggregated: a record that belongs to another store is **refused**, and this store never returns another store's committed receipt |
| the committed identities | they were bounded, but the bound was not stated | the bound is stated: the content-based deduplication is **bounded** (1024 identities) and **per store**. It protects against the **immediate** repeat of the same record; it is **not** a protection against an indefinite historical replay, and it is not claimed as one |

The witnesses are `serve/test_telemetry_store_commit_correction.py`, the reversals are
`tools/test_telemetry_store_commit_correction_mutations.py`.

## See also

* [docs/DETAILS.md](DETAILS.md) - the engine's own workings.
* [docs/monitoring/](monitoring/) - the Prometheus and Grafana setup.
