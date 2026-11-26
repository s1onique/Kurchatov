# 08 - The security and the privacy (W6, W8)

## What the telemetry never carries

| Never captured | Where it would have come from |
|---|---|
| the raw prompts | the API monitor's `input` |
| the conversation messages | the request body |
| the generated answers | the API monitor's `output` |
| the private reasoning | the API monitor's `reasoning` |
| the tool arguments and the tool results | the request and the answer |
| the authorization headers | the HTTP request |
| the API keys | the HTTP request |
| the raw token ids | the engine's prompt |
| an arbitrary exception payload | an error |
| a prompt hash | - |

**The check is executable, not a promise.** `test_the_evidence_carries_no_content` reads a written evidence file
and asserts that every key in every section is one of the schema's names - a closed list of counts, positions,
ids and fixed words. There is no key that could hold a prompt or an answer.

`test_the_telemetry_carries_no_content_at_all` and the check in `06-http-contract-evidence.json` do the same for
the HTTP surface.

## The independence

The telemetry surface and the API monitor are **separate**:

| | The API monitor | The telemetry |
|---|---|---|
| the config's `api_monitor` | off by default | independent of it |
| what it keeps | the prompts and the answers | counts, positions and ids |
| the route | `/api-monitor` | `/v1/telemetry/*` |
| when it is off | the page says so | the API still answers, with the measurements it has |

The telemetry view works with the API monitor **off**: it never asks for content.

## The access control

| Listener | An API key | The request-level telemetry |
|---|---|---|
| this PC's loopback | no | **allowed** (the server's own trust) |
| this PC's loopback | yes | allowed, with the key |
| beyond this PC | **no** | **refused with 403** - it fails closed |
| beyond this PC | yes | allowed, with the key |

The three cases are tested (`test_a_shared_listener_without_a_key_refuses_the_request_metadata`,
`test_a_shared_listener_with_a_key_needs_it`, `test_the_loopback_listener_keeps_the_server_own_trust`).

**An inference endpoint that lets anonymous callers in does not make the request metadata anonymous.** The
answers are the client's business; the request's timing and its cache attribution are not.

## What was not weakened

| | |
|---|---|
| the API key check | untouched (`_authorized`) |
| the CORS rules | untouched; the telemetry adds no origin |
| the trusted origins | untouched |
| the ports | unchanged: the telemetry is on the existing listener |
| the ingress | unchanged |
| the credentials | never in a URL, never in the browser's stored configuration: the page asks for the key and keeps it in `sessionStorage` (the session, not the disk) |

## The response headers

The request-level diagnostics carry `Cache-Control: no-store`, so a proxy or a browser does not keep a request's
metadata.

## The structured evidence

| | |
|---|---|
| the format | one metadata-only JSON object per line (JSONL) |
| the writer | a background thread: the token path never touches the disk |
| the queue | bounded; a record that does not fit is **dropped and counted**, never written synchronously |
| the counters | `written`, `dropped`, `errors` - in `/v1/telemetry/status` and in the Prometheus metrics |
| the shutdown | the queue is flushed and the file closed (`shutdown`) |
| the rotation | the repository's own log facilities (the file is written by the same process that writes the log) |
