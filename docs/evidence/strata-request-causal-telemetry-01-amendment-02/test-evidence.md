# 03 - The test evidence

Every command below was run on this host, against the committed tree.  The Python is `/tmp/stratavenv`, which has
the repository's REAL dependencies (`jinja2`, `regex`, `jsonschema`) - no stand-in was used for the acceptance
run.

| # | Command | Result |
|---|---|---|
| 1 | `/tmp/stratavenv/bin/python -m unittest discover -s serve -p 'test_*.py'` | see the table below |
| 2 | `/tmp/stratavenv/bin/python -m unittest serve.test_reqtelemetry serve.test_telemetry_integrity serve.test_telemetry_amendment02` | 158 tests, OK |
| 3 | `/tmp/stratavenv/bin/python tools/test_reqtelemetry_schema.py` | `test_reqtelemetry_schema: all checks passed` |
| 4 | `/tmp/stratavenv/bin/python tools/test_telemetry_mutations.py` | 12 witnesses, OK |
| 5 | `/tmp/stratavenv/bin/python tools/test_telemetry_web_accounting.py` | `4 cases checked with osascript` |
| 6 | `git diff --check 579f5cef..HEAD` | clean (no whitespace error) |
| 7 | `/tmp/reqtelemetry_test` (built with `clang++ -std=c++17 -O1 -Iinclude src/program/reqtelemetry_test.cpp`) | `reqtelemetry_test: all checks passed` (exit 0) |
| 8 | `/tmp/stratavenv/bin/python tools/test_reqtelemetry_roundtrip.py` (the real native writer built) | 6 tests, OK |

## The whole suite

| Run | Tests | Result |
|---|---|---|
| the entry head (`579f5cef`), for comparison | 1052 | 1 failure (`test_responses.NoLeakedSampler.test_server_close_ends_the_sampler` - a timing-sensitive sampler test) |
| the first amendment-02 run | 1126 | 4 failures, all in `serve/test_prometheus.py`: the exporter's own parser did not accept a sample without a label set, which the process-scoped telemetry metrics produce (A8).  The parser was corrected to accept the valid `name value` form; the metrics themselves were not changed. |
| the final run | 1129 | **OK (20 skipped)**, exit code 0 |

The final run is the acceptance run: the repository's real dependencies, the committed tree, no stand-in.

The suite's own count grew by the amendment's own witnesses (37) and by the predecessor's delta.

## The G7 witnesses that use the real transport

Three of the witnesses drive the actual HTTP transport instead of a fixture:

* **a queued request that the client abandons**: the first request holds the turn (the mock engine is slow), a
  second client opens a real socket, sends its request and closes it.  The abandoned request ends as `cancelled`,
  it gets exactly ONE receipt, its finish reason is the cancellation (never a successful stop), and the
  lifecycle identity still balances with `inflight = 0`;
* **a transport disconnection mid-stream**: the client opens a real socket, reads nothing and closes it while
  the stream runs.  The request ends as `cancelled` (or `failed`) with exactly one receipt, and the accounting
  balances;
* **the terminalization fault injection through the HTTP path**: `RequestRecord.seal` is made to fail while the
  request runs.  The request's answer is unaffected, the terminal outcome is still counted, the loss of the
  receipt is counted as a delivery failure, and the identity balances.

These are the controls the amendment asks for by name ("a genuinely queued request and actual HTTP disconnect
controls, not merely an engine fixture returning a cancellation finish reason").

## The witnesses, and what each one protects

| The witness | What it protects |
|---|---|
| `Admission` (6) | the measurement admission and the aggregate authority (G1) |
| `InvocationIdentity` (6) | the invocation identity (G2/A2), including the recovery witness |
| `InvocationIdentity` (6) | the invocation identity (G2/A2), including the recovery witness |
| `Monotonicity` (2) | the engine's eviction high-water mark (G5) |
| `Cursors` (7) | the cursor contract (G6) |
| `EvidenceWriter` (4) | the writer's bytes, its bounds and its flush (A5) |
| `Lifecycle` (2) | the lifecycle conservation (A4) |
| `ModelSwitch` (1) | the process-scoped metrics (A8) |
| `HttpWitnesses` (9) | the queue wait (A1), the first content (A3), the lifecycle over HTTP (A4), the cursor over HTTP (G6), a genuinely QUEUED request that the client abandons (G7), an actual TRANSPORT DISCONNECTION mid-stream (G7), and the terminalization FAULT INJECTION through the HTTP path (G7/A4) |
| `tools/test_telemetry_mutations.py` (12) | the non-vacuity: every correction is reversed in memory and the witness that guards it fails |

## The non-vacuity witnesses (G10)

| Name | The correction it reverses |
|---|---|
| `HISTOGRAM_BUCKET_FABRICATION` | the exporter's real cumulative buckets |
| `HISTOGRAM_UNIT_CONVERSION_REMOVED` | the conversion of the milliseconds, once |
| `FOREIGN_NATIVE_ID_ACCEPTED` | the receipt's binding to the invocation |
| `NULL_REUSE_INTERPRETED_AS_ZERO` | the null semantics of the disposition |
| `CONSERVATION_CHECK_BYPASSED` | the conservation check |
| `OUTPUT_BUDGET_NOT_WIRED` | the requested budget's path into the record |
| `WALL_CLOCK_USED_FOR_DURATION` | the monotonic clock of the durations |
| `TERMINAL_RECEIPT_LOST` | the terminal receipt's delivery |
| `QUEUE_DURATION_OVERWRITTEN` | the queue wait's measurement boundary (A1) - the witness is the real HTTP path with two requests |
| `HTTP_FIRST_TOKEN_MISATTRIBUTED` | the first-content measurement at the write boundary (A3) |
| `INVOCATION_ID_REUSED` | the new invocation id per dispatch (A2) |
| `FLUSH_RETURNS_WHILE_WRITER_BUSY` | the evidence writer's flush (A5) |

Each of them reverses the PRODUCTION behavior (not a return value): the queue witness overwrites the timing in
`Service._finish_telemetry`, the first-content witness writes the service's observation into the HTTP field, the
invocation witness makes every dispatch use the same id, and the flush witness looks at the queue only.  The
mutation code lives in the test file; nothing is left in the production tree.
