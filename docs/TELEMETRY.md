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
  "schema_version": "strata.request-telemetry/1",
  "identity": {
    "request_id": "9ca8c311a98448e5a10827dd9cac6b7b",
    "client_request_id": "my-trace-42",
    "engine_instance_id": "pid-8123-gen-2",
    "server_instance_id": "c14ecbc49c694f2fbd08b10cfdbdcd7b",
    "engine_invocation_id": "9ca8c311a98448e5a10827dd9cac6b7b",
    "slot_id": 0,
    "model_id": "qwen3.8-flash",
    "build_revision": "5b0e549b762d"
  },
  "lifecycle": {"state": "completed", "api": "openai", "received_at": 1795717079.16, "http_status": 200,
                "finish_reason": "stop"},
  "prompt": {"rendered_tokens": 246, "submitted_tokens": 246, "matched_prefix_tokens": 200,
             "reused_prefix_tokens": 200, "evaluated_tokens": 46, "replayed_tokens": 0,
             "non_prefix_reused_tokens": null, "evaluation_work_tokens": 46,
             "first_divergent_token_index": null},
  "cache": {"source": "conversation_cache", "disposition": "partial_hit", "reason_code": "exact_match",
            "restore_attempted": true, "restore_succeeded": true, "restore_ms": 3.2},
  "timing_ms": {"prefill_wall": 41.5, "decode_wall": 210.0, "http_first_token": 55.2, "total": 268.0},
  "generation": {"requested_max_output_tokens": 512, "effective_max_output_tokens": 512,
                 "generated_tokens": 63, "emitted_tokens": 63,
                 "speculative_draft_tokens": 31, "speculative_accepted_tokens": 24},
  "measurement_quality": {"state": "complete", "unavailable_fields": {}, "timing_authority": {...}}
}
```

The schema is [`docs/telemetry/strata-request-telemetry-1.schema.json`](telemetry/strata-request-telemetry-1.schema.json)
(JSON Schema draft 2020-12). It is checked by an executable test, so the contract on the wire and the contract in
the code cannot drift apart.

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

`timing_authority` names who measured each duration (`native_engine` or `http_server`), so the two are never
confused.

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
strata_telemetry_available
```

The labels are bounded enumerations only. There is **no** request id, session, engine instance, prompt, user,
error message or dynamic model identity in a label.

A duration that was not measured contributes **no sample**: a histogram's `_count` says how many observations
there really were. It is never padded with zeros.

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

## See also

* [docs/DETAILS.md](DETAILS.md) - the engine's own workings.
* [docs/monitoring/](monitoring/) - the Prometheus and Grafana setup.
