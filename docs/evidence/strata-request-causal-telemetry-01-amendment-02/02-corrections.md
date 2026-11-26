# 02 - The corrections

Every correction is in the production tree, in the place that owns the measurement.  The files and the symbols
are named so that a reviewer can read the change without the diff.

## G1 - the admission and the aggregate authority

| What | Where |
|---|---|
| the three decisions (the measurements are valid, the accounting holds, the receipt is correlated) | `serve/reqtelemetry/accounting.py`: `validate_measurements`, `measurement_valid`, `aggregate_eligible`, `field_eligible` |
| the admission boundary: a measurement that is not a whole, non-negative count is REFUSED | `serve/reqtelemetry/correlation.py`: `_admit` |
| the store counts only what is eligible | `serve/reqtelemetry/store.py`: `_count_locked` |
| the record publishes the decisions | `serve/reqtelemetry/record.py`: `measurement_quality.native_correlation`, `native_partial`, `measurement_valid`, `aggregate_eligible` |

A record whose accounting is violated, whose measurements are invalid or whose receipt is not correlated stays in
the store as a diagnostic receipt and contributes NOTHING to the authoritative totals.  A measurement the SERVER
owns (the submitted prompt) stays eligible even when the engine's receipt could not be correlated.

## G2/A2 - the invocation identity

* `serve/reqtelemetry/correlation.py`: `new_invocation_id()` - a fresh hexadecimal id for every dispatch;
* `serve/server.py` (`Service.run`): the id is generated IMMEDIATELY BEFORE the dispatch and sent with the
  command; the record keeps it and its ordinal (`identity.engine_invocation_ordinal`);
* `serve/reqtelemetry/correlation.py` (`apply_engine`): the echoed id is compared with the expected one.  A
  foreign id is REJECTED: none of its numbers is applied - not even the positional DONE fields outside the
  telemetry suffix - and the request says it had an instrumentation error;
* a receipt with no id leaves the correlation UNAVAILABLE, never an asserted join.

## G3/G4 - the native side (two measurement sites)

* `src/program/generate.cpp`: `tele.work = reread_state ? -1 : tele.evaluated;` - the cumulative work is the
  distinct count only on the path where every position is read exactly once; on the re-read path the field stays
  NOT MEASURED instead of repeating a smaller number;
* `src/program/generate.cpp`: the checkpoint-restore failure emits the telemetry it DID measure with the ERR
  line, so the failed request keeps its correlated partial evidence.  The engine still fails exactly as before.

## G5 - the counter's high-water mark

`serve/reqtelemetry/store.py`: the engine's eviction counter is a high-water mark PER ENGINE INSTANCE: a smaller
reading never lowers the mark and never lowers the total; a new engine instance starts its own mark.

## G6 - the cursor contract

`serve/reqtelemetry/record.py` (`decode_cursor`): a cursor without an owner, with a sequence number below one,
dated in the future or expired is refused.  `serve/reqtelemetry/store.py` (`list`): a cursor that names a record
this store never wrote, or one whose page was already evicted, is refused - it is never treated as an exhausted
collection.  The HTTP endpoint answers 400.

## A1 - the queue wait

`serve/server.py`: the wait is measured where it happens (when the request takes its turn, and when a request
that never ran gives its place up) and it is NOT overwritten at the finalization.

## A3 - the first content and the emitted tokens

* `serve/server.py`: `Handler._first_content` measures the first MEANINGFUL content at the response-write
  boundary (the headers, the keep-alives, the role-only events and the prompt-progress events do not start the
  clock; the reasoning output does, and the record says so);
* the Service's own observation is published as `engine_first_token` with the authority
  `http_server_observation` - it is not the client's first byte;
* the emitted-token count is NULL with a reason: the response is transformed, so the tokens written to the client
  are not attributable.  It is not a measured zero.

## A4 - the lifecycle conservation

`serve/reqtelemetry/store.py` (`begin_request`, `end_request`, `receipt_failed`) and
`serve/reqtelemetry/server.py` (`begin`, `finish`): the accepted count is taken at the admission boundary, the
terminal outcome is counted BEFORE the record is sealed, and the receipt's own delivery is counted beside them.
The identity at quiescence: accepted = completed + cancelled + failed + rejected, inflight = 0.

## A5 - the evidence writer

`serve/reqtelemetry/evidence.py`: the bytes are the serialized UTF-8 bytes with the framing; the bound counts
the queued records AND the record being written; `flush()` returns true only when every record it accepted has
reached a terminal writer outcome; the worker owns the handle until it has stopped; a refused write is counted
as a failure.

## A7 - the browser's accounting bar

`serve/web/telemetry_accounting.js`: the arithmetic is ONE pure function.  The denominator is the submitted
prompt; the positions nobody accounted for are drawn as such; an unknown replay is not a measured zero; a
violated or unevaluated accounting gets no bar at all.  The page uses the same function
(`serve/web/telemetry.js`), and `tools/test_telemetry_web_accounting.py` runs it.

## A8 - the model's label

`serve/prometheus.py`: the canonical telemetry metrics are PROCESS-SCOPED: they carry no `model_name` label.  A
process-lifetime total does not belong to the model that happens to be selected when the scrape happens.  The
existing compatibility metrics (`vllm:*`, `strata:*`) keep their labels and their meaning.

## A9 - the batch slot's segment

`serve/server.py` (`_apply_bdone`, `_finish_telemetry`): a slot's BDONE ends the slot's leg; the figures that
came with its admission describe that segment only.  The record says so (`native_partial`) and the numbers stay
out of the authoritative totals.
