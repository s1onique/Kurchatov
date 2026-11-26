# 03 - What was implemented (W2-W6)

Five pieces, each in the place that owns it.

## 1. The native half (`include/strata/program/reqtelemetry.hpp`, `src/program/generate.cpp`)

The engine measures the cache state and the model execution, and reports it **on the request's own DONE line**,
as `key=value` pairs after the ones the line already had.

| The engine writes | What it is |
|---|---|
| `rid=<hex>` | the request's own id, echoed back |
| `matched=<n>` | the contiguous token-prefix match against the candidates, before the execution-state constraints |
| `reused=<n>` | the prefix whose usable execution state was really retained or restored |
| `evaluated=<n>` | the distinct prompt positions the engine evaluated |
| `replayed=<n>` | the evaluated positions that were previously processed prompt material |
| `work=<n>` | the executed prompt-token evaluations |
| `divergent=<n>` | the first divergent token's position (-1: no mismatch) |
| `slot=<n>` | the execution slot |
| `restore=<none\|succeeded\|failed>` | the restoration's actual outcome |
| `restore_ms=<f>`, `lookup_ms=<f>` | the engine's own durations |
| `cache_source=<word>`, `cache_reason=<word>` | where the prefix came from and why |

**The engine's decision is not modified.** The cache analysis is the *existing* one: the telemetry turns the same
`CacheDiagCollector` on (`cdiag.on = cdiag_on || tele_on;`) and carries the result on the DONE line. There is no
second, parallel account of the cache decision.

**The switch.** `STRATA_TELEMETRY=1` (off by default). With it off, the engine does no extra work and the DONE
line is byte-identical to the release's. The server sets it for the engine it starts (`child_env`).

**The restore's outcome is measured where the restore happens**, and a restore that was tried and failed is
reported as a failure - never as a successful reuse.

## 2. The server's half (`serve/reqtelemetry.py`, `serve/server.py`)

`serve/reqtelemetry.py` holds the contract (the record, the schema, the store, the evidence log) and nothing
else. `serve/server.py` wires it:

| Where | What |
|---|---|
| `Service.__init__` | the store and the evidence log (`STRATA_TELEMETRY_RECORDS`, `STRATA_TELEMETRY_BYTES`, `STRATA_TELEMETRY_EVIDENCE`) |
| `Service._finish_telemetry` | closes the record: the engine's figures from the DONE line, the server's own timings |
| `Service.telemetry_api` | the HTTP API's answers |
| `Service.telemetry_summary` | the totals for `/metrics` and the Prometheus exporter |
| `_parse_done` | reads the engine's `key=value` telemetry off the DONE line |
| `StrataEngine.request_key` / `set_request_id` | the request's id on the wire (`rid=`) |
| `do_POST` | the record is created; the client's `X-Request-ID` is validated |
| `_json` / `_sse` | the `X-Strata-Request-ID` response header |

The request's id is a **thread-local on the engine** (`_req_local`), not an engine attribute: with parallel batch
slots several requests share one engine process and each must carry its own id.

## 3. The HTTP API (`serve/server.py`)

| Route | Answer |
|---|---|
| `GET /v1/telemetry/status` | the capability, the identity, the retention |
| `GET /v1/telemetry/summary` | the process-lifetime totals |
| `GET /v1/telemetry/requests` | a bounded page of the recent requests |
| `GET /v1/telemetry/requests/{request_id}` | one request |
| `GET /telemetry` | the browser view |

Read-only, bounded, metadata-only, on the existing port. **No new service, no database, no extra listener.**

The pagination is stable: the cursor names the sequence number of the last record of the previous page, so a page
never repeats a record and never skips one while new requests arrive.

## 4. The web view (`serve/web/telemetry.html`, `serve/web/telemetry.js`)

Its own page, loaded in an iframe from the chat app's **Telemetry** tab. It works without the API monitor: the
telemetry keeps no prompts and no answers.

It shows the identity and the capability, the request counts, the token-weighted cache reuse ratio, the recent
request table (with the filters), and the request inspector (the identities, the token accounting with a bar, the
cache attribution, the per-stage timings with their authority, the measurement quality and the raw metadata-only
JSON).

It warns when the matched prefix exceeds the usable prefix, when a restoration failed, when the attribution is
incomplete and when the engine reported no telemetry. **An unsupported measurement is shown as `-`, not as `0`.**

The refresh is bounded (two seconds by default) and never overlaps: `poll()` returns early while one is in
flight, and a hidden tab does not poll.

## 5. The Prometheus extension (`serve/prometheus.py`)

**Additive only.** The JSON `/metrics`, the content negotiation, the vLLM-compatible names and the
llama.cpp-compatible names are untouched. The new families are `strata_requests_total`,
`strata_prompt_*_tokens_total`, `strata_generated_tokens_total`, `strata_cache_restore_*_total`,
`strata_cache_evictions_total`, `strata_telemetry_*_total`, the seven duration histograms and the five gauges.

The labels are bounded enumerations only: **no request id, no session, no engine instance, no prompt, no user,
no error message, no dynamic model identity** in a label.

A duration that was not measured contributes **no sample**: a histogram's `_count` says how many observations
there really were.

## 6. The structured evidence (`serve/reqtelemetry.py`'s `EvidenceLog`)

With `STRATA_TELEMETRY_EVIDENCE=<path>`, every finished request is one metadata-only JSON object per line.

* written by a **background thread**: the token path never touches the disk;
* the queue is **bounded**: a record that does not fit is dropped and counted, never written synchronously;
* the file carries no prompt, no answer, no reasoning, no tool arguments, no header, no key, no raw token id and
  no prompt hash;
* the queue is flushed and the file closed on the way down (`shutdown`).

## The privacy boundary

The telemetry surface is **independent of the API monitor**: the API monitor (`/api-monitor`, the config's
`api_monitor`) captures prompts and answers; the telemetry never does, and it works with the monitor off.
