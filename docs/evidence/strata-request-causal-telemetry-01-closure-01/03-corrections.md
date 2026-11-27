# ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 - the corrections

Every correction below is in the production path.  The witnesses are in `serve/test_telemetry_closure01.py`
(the corrections of this ACT), `serve/test_reqtelemetry.py` (the writer's witnesses) and
`tools/test_telemetry_closure01_mutations.py` (the reversals that show the witnesses are not vacuous).

## C1 - the acceptance boundary is the enqueue

`serve/reqtelemetry/evidence.py`, `EvidenceLog.write`:

* the first critical section is the FAST PATH only.  It counts the submission and refuses the obvious cases (no
  handle, the boundary already closed).
* the record is serialized OUTSIDE the lock, so a slow serializer never blocks the worker.
* the SECOND critical section - the one that enqueues - revalidates EVERY acceptance condition under that lock:
  the boundary may have closed while the record was being serialized (the C1 defect), the handle may be gone,
  and the byte and count bounds may have been reached by the records the worker took in the meantime.
* a record that lost the race is REFUSED there: it is counted as a shutdown refusal and it never enters the
  queue.  Nothing is accepted and abandoned.

The mandatory witness uses deterministic barriers (`threading.Event`), never a sleep:

```
write_result: false
accepted_records: 0
shutdown_refusals: 1
outstanding_records: 0
```

## D7 - the writer's counter domains are exact

* `pending_records` is the new domain: the submissions that have ENTERED but are not RESOLVED yet - the ones
  whose record is being serialized right now.
* The published identity is now

  ```
  submitted = accepted + refused + pending        (at every moment)
  submitted = accepted + refused                  (at quiescence)
  accepted  = written + failed + outstanding      (at every moment)
  ```

  `resolved_records` (= accepted + refused) is published beside them, so the counter contract can be checked at
  any moment without waiting for quiescence.
* `flush()` waits for the in-progress serialization as well: a flush that returned while a submission was in
  the serializer would report the evidence as durable when it is not.
* The refusal domains stay apart and are published apart: `initialization_failures`,
  `serialization_refusals`, `capacity_refusals`, `shutdown_refusals` and `write_failures`.  The legacy mixed
  `errors` counter is not the canonical accepted-record write-failure counter - `write_failures` is.

## D1 - the typed measurement admission

`serve/reqtelemetry/accounting.py` holds the shared rules (`valid_count`, `valid_duration`, `admit_count`,
`admit_duration`), and BOTH the record and the invocation receipt use them:

* a COUNT is a whole, non-negative integer - a bool, a fraction and a negative are refused;
* a DURATION is a finite, non-negative number - a negative, a NaN and an infinity are refused;
* an invalid value is REFUSED, never clamped, rounded or coerced: the field stays null, the receipt says why,
  and the measurement is marked invalid so it cannot enter a total;
* the native sentinels keep their own meaning: the engine's -1 ("not measured") stays null and is NOT an invalid
  measurement;
* the validity is CLASS-AWARE: an invalid duration does not exclude the valid token counts, and an invalid count
  does not exclude the valid durations;
* the strict JSON holds: `json.dumps(record, allow_nan=False)` never raises, so the browser's parser and the
  evidence JSONL are safe.

## D2 - the dispatch identity authority

* `RequestRecord.begin_invocation` distinguishes OMITTED from EXPLICITLY UNKNOWN (the `OMITTED` sentinel): an
  argument that is not given falls back to the record's own identity, an argument that is given as None means
  "this identity was not available at the dispatch" - and it stays unavailable.
* the terminal path NEVER creates a dispatch: `correlation.apply_engine` refuses a receipt whose invocation this
  request does not hold (it was never dispatched, or its receipt was dropped).  The compatibility path is
  explicit (`adopt_legacy_invocation`) and does not count as a dispatch.
* the production finalizer's fallback to the last retained receipt is GONE (serve/server.py).

## D3 - the HTTP measurement authority

`serve/reqtelemetry/store.py` counts the HTTP-owned counters on their own terms: a broken NATIVE accounting no
longer suppresses `prompt_tokens_submitted` or `emitted_tokens`, and the store's decision agrees with the
record's own `admission.http`.

## C2 - the coverage denominators

* the invocation population is the DISPATCHED one: a receipt that was dropped is a MISSING invocation, so the
  coverage falls instead of improving;
* the physical request's own coverage is measured against the requests that reached a TERMINAL OUTCOME (counted
  before the receipt is sealed and stored), so a lost terminal receipt lowers the coverage instead of shrinking
  the denominator;
* the dropped receipts are published (`dropped_invocations`).

The mandatory witness:

```
native_dispatches: 10, retained_complete_receipts: 8, dropped_receipts: 2
-> invocations: 10, eligible_invocations: 8, missing_invocations: 2, coverage: 0.8

physical_requests_accepted: 2, complete_accounting_receipts: 1, terminal_receipts_lost: 1
-> requests_with_complete_accounting: 1, request_coverage: 0.5
```

## C3, D4 - the invocation terminalization

* every native dispatch is terminalized on its OWN evidence: the segment carries the id of the dispatch that
  produced it, and the expected identity comes from the DISPATCH boundary, never from the id the engine echoed
  back.  Each receipt gets its own cache measurements, prefill and decode time, generated count, speculative
  counters, native finish reason, terminal state and partial-segment classification;
* the receipt publishes its NATIVE finish reason (`generation.finish_reason`) - it is not the physical HTTP
  finish reason;
* the effective output budget is the budget the dispatch was given (`max_new - n` at that moment);
* an accepted terminal receipt is never silently overwritten: an identical duplicate is ignored (and causes no
  additional work accounting), a conflicting duplicate keeps the accepted measurements and produces explicit
  instrumentation evidence.

## C4 - the prompt domains

The prompt's LENGTH is not its identity.  The dispatch boundary NAMES the domain of each dispatch ("request",
"continuation", "other") - no prompt content and no prompt hash - and the coverage is computed from that name.
The store uses the name (not the length) to decide whether an invocation's positions belong to the request's own
prompt.

## C5 - the bounded accounting

* a retired engine's counter domain is not forgotten: the retired engines' last readings are kept in a SEPARATE,
  equally bounded map, so a late observation of a retired engine is compared with its own last reading and only
  its DELTA is counted.  When a retired reading is dropped, the engine is remembered as unattributable and its
  later observation is REFUSED from the authoritative total (never counted again).  The tombstone storage is
  bounded.
* the invocation byte bound is revalidated AFTER the terminal measurements were added, a receipt that cannot fit
  on its own is refused, and the dropped bytes are published.  A serialized-byte budget is NOT a hard Python RSS
  bound: it bounds the retained receipts, not the interpreter's memory.

## D6 - the measurement quality and the presentation

* the receipt derives its OWN cache disposition from the same rules as the record;
* the record publishes `native_correlation_complete`: the RETAINED evidence may be verified while the request's
  evidence is incomplete (a receipt was dropped);
* the request inspector (serve/web/telemetry.js) shows the invocation-level evidence through the EXISTING facts
  list - no new page, no new feature - and the loss of a receipt is a warning;
* the TTFT tooltip now describes the actual HTTP-write boundary.

## C6, D8 - the non-vacuity

`tools/test_telemetry_closure01_mutations.py` reverses each correction IN MEMORY ONLY and shows that its witness
FAILS without it:

```
INVALID_DURATION_PUBLISHED, INVALID_GENERATION_COUNT_PUBLISHED, EXPLICIT_UNKNOWN_IDENTITY_INHERITED,
TERMINAL_RECEIPT_CREATES_DISPATCH, CONFLICTING_DUPLICATE_TERMINAL_RECEIPT_ACCEPTED,
HTTP_COUNTER_SUPPRESSED_BY_NATIVE_ACCOUNTING, RETIRED_ENGINE_COUNTER_COUNTED_AGAIN,
INVOCATION_BYTES_NOT_REVALIDATED, DROPPED_INVOCATIONS_EXCLUDED_FROM_DENOMINATOR
```

and `serve/test_reqtelemetry.py` holds the writer's own reversal (`WRITER_CLOSE_RECHECK_REMOVED`).  Nothing is
left in the production tree: the reversals are patches of the running process.

## What was NOT changed

The AMENDMENT-03 architecture, the InvocationReceipt abstraction, the metric-specific admission, the histogram
implementation and the native restoration correction are preserved.  The production semantics, the cache policy
and the model execution are untouched, and the historical acceptance reports were not rewritten - this package
is a successor reference to them.

## The review payload

`01-source-only.diff` is the diff the ACT asks for:

```bash
git diff "$ENTRY_HEAD"..HEAD -- \
  serve/reqtelemetry serve/server.py serve/prometheus.py serve/web \
  serve/test_reqtelemetry.py serve/test_telemetry_amendment03.py tools
```

The new witness file `serve/test_telemetry_closure01.py` lies OUTSIDE those paths, so its diff is published
beside it as `05-witness-files.diff` (together with the reversals in `tools/`, which are inside the payload
already).  The historical evidence documents are not in the payload.
