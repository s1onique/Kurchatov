# ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 - the defects that were reproduced

ENTRY_HEAD: `586a720781b990c5801b346653b1887525ca1009` (the reviewed head; there were no intervening changes -
`git status --porcelain` was empty and `git rev-parse HEAD` was the reviewed head).

## C1 - the writer's acceptance boundary was not the enqueue

`EvidenceLog.write` (serve/reqtelemetry/evidence.py) checked the closed state, released its lock, serialized the
record and then took the lock again to enqueue it.  The second critical section did NOT revalidate the acceptance
boundary, so a record that was being serialized while the writer was closed was accepted into a queue no worker
would write any more.

Reproduced against ENTRY_HEAD with a deterministic barrier (no sleep): the producer blocks inside the
serialization, the writer is closed, the worker is joined, and only then the serialization is released.

```
$ /tmp/stratavenv/bin/python -m unittest \
    serve.test_reqtelemetry.Evidence.test_a_write_that_races_the_shutdown_is_refused_at_the_enqueue
FAIL: ... test_a_write_that_races_the_shutdown_is_refused_at_the_enqueue
AssertionError: True is not false : the raced write was accepted
```

## D7 - the writer's counter domains did not hold during a serialization

`submitted_records` was incremented before the serialization and `accepted_records` / `refused_records` after it,
so the advertised identity `submitted = accepted + refused` did not hold while a record was being serialized.
The in-progress serialization had no domain of its own.

## D1 - the measurement admission was not typed

The predecessor's `_num` accepted anything that was a number, so a negative duration, a NaN and a fractional
token count all reached the published record - and the aggregate exporter excluded them afterwards, so the
record and the totals disagreed.

Reproduced against ENTRY_HEAD (the reviewer's own reproduction, confirmed here):

```
negative_duration:    lookup_ms = -1.0    -> published, measurement_valid true, 2 schema errors
nonfinite_duration:   lookup_ms = NaN     -> published, strict JSON serialization FAILED
negative_evictions:   evictions = -2     -> published, schema validation FAILED
negative_generation:  generated = -1      -> published, schema validation FAILED
fractional_generation: generated = 2.5    -> published, schema validation FAILED
```

## D2 - the terminal evidence created dispatches

`correlation.apply_engine` called `record.begin_invocation(expected)` when the expected receipt was not found, so
a receipt of an invocation this request never dispatched - or of one whose receipt had already been dropped -
produced a NEW dispatch: the dispatched population grew and the retained population changed.

`RequestRecord.begin_invocation` also treated an explicitly supplied `None` identity as permission to inherit the
record's preparation-time identity, so an identity that was unavailable at the dispatch was presented as the old
one.

## D3 - the HTTP counters were suppressed by the native accounting

The store counted `prompt_tokens_submitted` only when the record's native accounting was not violated, while the
record's own admission said that the HTTP class is always admitted.  The record and the store disagreed.

## C5a - a retired engine's counter domain was forgotten

The bounded high-water map DELETED an engine's mark when the bound was reached, so a late observation of that
engine looked like a first observation and its whole cumulative counter was counted again.

## D5 - an oversized single receipt was admitted

The receipt's serialized size was measured when it was admitted - before the terminal measurements were added -
and a receipt that could not fit within the byte budget on its own was admitted when the history was empty.

## C2, C3, C4, D4, D6 - the confirmed defects of the review

The invocation denominator was counted while iterating the retained receipts, so a dropped receipt disappeared
from the coverage; the physical-request denominator came from the stored receipts; the positional DONE fields of
the earlier segments were applied only from the last segment; the prompt length was used as the prompt domain;
the receipt's `finish_reason` was never published; the parent's correlation claimed "verified" even when receipts
had been dropped.

## The corrections

See `03-corrections.md`.  The source-only diff against ENTRY_HEAD is `01-source-only.diff`.
