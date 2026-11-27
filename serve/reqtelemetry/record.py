"""serve/reqtelemetry/record.py - the canonical request record and its vocabulary.

One versioned, machine-readable record per physical request attempt.  It is METADATA ONLY: no prompt, no answer,
no reasoning, no token ids, no hash of the prompt.  Two authorities write into it:

  * the NATIVE ENGINE owns the cache state and the model execution: the prompt tokens it was given, the prefix it
    actually reused, the tokens it read, the prefill and decode time, the drafts it offered and accepted, and the
    reason it ended.  Those numbers arrive on the request's own DONE line (serve/server.py: StrataEngine._parse_done),
    which is the request's own channel - not a log that is read afterwards and matched by position.
  * the HTTP SERVER owns the request lifecycle: the queue wait, the template render, the tokenization, the model
    load, the time to the first byte the client sees, the total time, and the HTTP status.

The record keeps the two apart and says which is which.  A number that was not measured is null, never 0: 0 is a
measured zero, and a null says "this was not measured here" (measurement_quality says why).

(ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-01, G9: this module is one part of the split of the former
serve/reqtelemetry.py; the import surface of serve.reqtelemetry is unchanged.)
"""
from __future__ import annotations

import base64
import json
import time
import uuid

from serve.reqtelemetry.accounting import (CORRELATION_REJECTED, CORRELATION_UNAVAILABLE, CORRELATION_VERIFIED,
                                           METRICS as METRIC_CLASSES)
from serve.reqtelemetry.invocation import InvocationReceipt
from serve.reqtelemetry.vocabulary import (CLIENT_ID_ALLOWED, CLIENT_ID_MAX, COMPLETE, DEFAULT_PAGE_SIZE,
                                         DEFAULT_RETENTION_BYTES, DEFAULT_RETENTION_RECORDS, DISPOSITIONS,
                                         DISPOSITION_BYPASSED, DISPOSITION_COLD_MISS, DISPOSITION_FULL_HIT,
                                         DISPOSITION_INVALIDATED, DISPOSITION_MATCH_WITHOUT_STATE,
                                         DISPOSITION_PARTIAL_HIT, DISPOSITION_UNKNOWN, INSTRUMENTATION_ERROR,
                                         MAXIMUM_PAGE_SIZE, MAX_INVOCATION_BYTES, MAX_INVOCATION_RECORDS, PARTIAL,
                                         SCHEMA_VERSION, SOURCES, SOURCE_CONVERSATION_CACHE,
                                         SOURCE_MULTIPLE, SOURCE_NONE, SOURCE_RESIDENT_SLOT,
                                         SOURCE_RESTORED_CHECKPOINT, SOURCE_UNKNOWN, STATES, UNSUPPORTED)


def _receipt_size(receipt):
    """The UTF-8 BYTES of one invocation receipt, or None when it cannot be serialized.

    The bound of the per-request invocation history is a byte budget, and a character count is not a byte count.
    ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D5): a receipt that cannot be serialized has an UNKNOWN
    size - it is not a zero-byte receipt, and it is never admitted as if it were free.
    """
    try:
        return len(json.dumps(receipt.to_dict(), ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError):
        return None

def valid_client_request_id(value) -> bool:
    """True when a client-supplied request id may be kept: printable ASCII, bounded, no whitespace or control
    characters.  Anything else is dropped (the request still runs; it just has no client id)."""
    if not isinstance(value, str) or not value or len(value) > CLIENT_ID_MAX:
        return False
    return all(c in CLIENT_ID_ALLOWED for c in value)


def new_request_id() -> str:
    """The server's own id for one physical request attempt: unique, opaque, and never derived from the client's
    id, so two requests that carry the same client id stay two records."""
    import uuid
    return uuid.uuid4().hex


def encode_cursor(seq: int, server_instance_id: str | None = None) -> str:
    """The pagination cursor: the sequence number of the last record of the previous page, encoded, together with
    the server that wrote it and the moment it was written.

    The number is a monotonic counter, so a page stays stable while new records arrive at the head.  The server id
    and the time make the cursor OWNED and EXPIRING: a cursor from another server (or from before a restart) is
    refused instead of quietly pointing somewhere else (G7).
    """
    stamp = int(time.time())
    raw = f"seq:{int(seq)}:{server_instance_id or ''}:{stamp}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, server_instance_id: str | None = None, max_age_s: float | None = None) -> int:
    """The sequence number a cursor names.

    Raises ValueError for a cursor this server did not write, for a cursor of another server, for an expired
    one, for a cursor with no owner, for a sequence number that is not a positive number and for a timestamp in
    the future.  An invalid cursor is NOT treated as an exhausted collection: it is an error the operator sees.
    """
    if not isinstance(cursor, str) or not cursor:
        raise ValueError("the cursor is empty")
    pad = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + pad).decode()
    except (ValueError, UnicodeDecodeError):
        raise ValueError("the cursor is not a cursor this server wrote") from None
    parts = raw.split(":")
    if len(parts) < 4 or parts[0] != "seq":
        raise ValueError("the cursor is not a cursor this server wrote")
    try:
        seq = int(parts[1])
    except ValueError:
        raise ValueError("the cursor is not a cursor this server wrote") from None
    if seq < 1:
        raise ValueError("the cursor names no record")
    owner, stamp = parts[2], parts[3]
    # AMENDMENT-02 (G6): a cursor carries its OWNER.  A cursor without one, or with another server's, is refused:
    # it points at a collection this server never wrote.
    if not owner:
        raise ValueError("the cursor names no server")
    if server_instance_id and owner != server_instance_id:
        raise ValueError("the cursor belongs to another server instance")
    try:
        issued = int(stamp)
    except ValueError:
        raise ValueError("the cursor is not a cursor this server wrote") from None
    if issued > int(time.time()) + 60:
        raise ValueError("the cursor is dated in the future")
    if max_age_s is not None and (time.time() - issued) > max_age_s:
        raise ValueError("the cursor has expired")
    return seq


class _Omitted:
    """The sentinel for an argument that was NOT given at all.

    ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D2a): it is not None.  An argument that is not given
    falls back to the record's own identity; an argument that is given as None means "this identity was not
    available", and the two must not be confused.
    """

    def __repr__(self):
        return "<omitted>"


OMITTED = _Omitted()

# how many dispatched invocation ids a record remembers (the bounded evidence that a receipt belongs to a
# dispatch of THIS request)
MAX_DISPATCHED_IDS = 64


def _num(value):
    """A number or None: 0 stays 0 (a measured zero), anything that is not a number becomes null."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value



class RequestRecord:
    """One request's telemetry, built up while it runs and sealed when it ends.

    Every setter takes the measurement and the authority that made it.  A measurement that was never made stays
    None, and the record says so in measurement_quality.
    """

    def __init__(self, request_id, client_request_id=None, server_instance_id=None, engine_instance_id=None,
                 model_id=None, build_revision=None, api=None):
        self.request_id = request_id
        self.seq = 0
        self.client_request_id = client_request_id if valid_client_request_id(client_request_id) else None
        self.server_instance_id = server_instance_id
        self.engine_instance_id = engine_instance_id
        self.engine_invocation_id = None
        # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-02 (G2/A2): the native invocation's id is a SEPARATE
        # identity from the request's own id, and the ordinal says which attempt of this request it was.  A new id is
        # generated for every dispatch, so a recovery dispatch inside the same request is its own invocation.
        self.engine_invocation_ordinal = None
        # how well the engine's receipt is tied to this request: verified, unavailable or rejected
        self.native_correlation = "not_applicable"
        # AMENDMENT-02 (A9): the native figures cover only ONE segment of the invocation (a batch slot's
        # admission segment): they stay in the record as diagnostics and do not enter the authoritative totals.
        self.native_partial = False
        # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-03 (G1): the per-invocation measurement receipts.
        # Every native dispatch owns ONE receipt, and the measurements of one invocation never appear under the
        # identity of another one.  The bounds are a COUNT and a BYTE budget; a receipt that does not fit is
        # counted as a loss, never dropped silently.
        self.invocations = []
        self.invocations_total = 0            # how many native invocations this request dispatched
        # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D2b): the ids this request DISPATCHED (bounded).
        # The dispatch boundary is the only authority that may create a dispatch; the terminal evidence may not.
        self.dispatched_ids = []
        self.invocations_bytes = 0
        self.invocations_dropped = 0
        self.invocations_dropped_bytes = 0
        # AMENDMENT-02 (G1): the engine sent a measurement that is not a measurement (a negative count, a
        # fraction, a bool).  It was refused at the admission boundary and the record says so.
        self.measurements_invalid = False
        self.slot_id = None
        self.model_id = model_id
        self.build_revision = build_revision
        self.api = api
        self.state = "queued"
        self.received_at = time.time()
        # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-01 (G4): the record's OWN monotonic clock.  Every
        # duration of this request is measured against it; the wall-clock timestamps are for reporting only.
        self.clock = time.perf_counter()
        self.started_at = None
        self.finished_at = None
        self.http_status = None
        self.finish_reason = None
        self.outcome_detail = None
        # the prompt accounting (tokens)
        self.rendered_tokens = None
        self.submitted_tokens = None
        self.matched_prefix_tokens = None
        self.reused_prefix_tokens = None
        self.evaluated_tokens = None
        self.replayed_tokens = None
        self.non_prefix_reused_tokens = None
        self.evaluation_work_tokens = None
        self.first_divergent_token_index = None
        # the cache attribution
        self.cache_source = SOURCE_UNKNOWN
        self.cache_disposition = DISPOSITION_UNKNOWN
        self.cache_reason_code = None
        self.cache_restore_attempted = None
        self.cache_restore_succeeded = None
        self.cache_restore_ms = None
        self.cache_recurrent_state = None
        self.cache_attention_state = None
        self.cache_checkpoint_state = None
        self.cache_invalidations = None
        self.cache_evictions = None
        # the timings (milliseconds)
        self.timing = {}
        self.timing_authority = {}
        # the generation
        self.requested_max_output_tokens = None
        self.effective_max_output_tokens = None
        self.generated_tokens = None
        self.emitted_tokens = None
        self.speculative_draft_tokens = None
        self.speculative_accepted_tokens = None
        self.first_token_includes_reasoning = None
        # why a measurement is missing
        self.unavailable = {}
        self.quality = COMPLETE
        # the accounting's own state (satisfied / violated / unevaluated); set when the record is sealed
        self.accounting = {"state": "unevaluated", "valid": None, "problems": []}

    # ------------------------------------------------------------------ the measurements
    def mark_unavailable(self, field, reason, quality=UNSUPPORTED):
        """A measurement this server could not make: the field stays null and the record says why.  This is the
        only way a field becomes null - a number that was measured is never turned into null afterwards."""
        self.unavailable[field] = reason
        if quality == INSTRUMENTATION_ERROR:
            self.quality = INSTRUMENTATION_ERROR
        elif self.quality == COMPLETE:
            self.quality = PARTIAL

    def set_timing(self, name, ms, authority):
        """A duration in milliseconds, from a monotonic clock, with the authority that measured it.

        ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D1): the SHARED typed rule admits it: a negative, a
        NaN and an infinity are refused, never published.
        """
        from serve.reqtelemetry import accounting
        value = accounting.admit_duration(self, name, ms, field=f"timing_ms.{name}")
        if value is None:
            return
        self.timing[name] = round(float(value), 3)
        self.timing_authority[name] = authority

    def set_prompt_tokens(self, rendered=None, submitted=None, authority="server"):
        """The prompt's token counts.  `rendered` is the count after the template render and the tokenization;
        `submitted` is what the engine was actually given (the two differ when the server truncates)."""
        if rendered is not None:
            from serve.reqtelemetry import accounting
            self.rendered_tokens = accounting.admit_count(
                self, "rendered_tokens", rendered, field="prompt.rendered_tokens")
        if submitted is not None:
            from serve.reqtelemetry import accounting
            self.submitted_tokens = accounting.admit_count(
                self, "submitted_tokens", submitted, field="prompt.submitted_tokens")

    def set_native_cache(self, *, matched_prefix=None, reused_prefix=None, evaluated=None, replayed=None,
                         non_prefix_reused=None, evaluation_work=None, first_divergent=None,
                         source=None, disposition=None, reason_code=None, restore_attempted=None,
                         restore_succeeded=None, restore_ms=None, recurrent_state=None, attention_state=None,
                         checkpoint_state=None, invalidations=None, evictions=None):
        """What the NATIVE ENGINE measured about the cache and the prompt.

        `matched_prefix` is the contiguous token-prefix match against the selected candidate, BEFORE the execution
        state is considered.  `reused_prefix` is the contiguous prefix whose usable execution state was actually
        retained or restored - the two are different things and the record keeps them apart.  `evaluated` is the
        distinct prompt positions the engine evaluated; `evaluation_work` is the executed prompt-token evaluations
        (repeated work counts again).
        """
        from serve.reqtelemetry import accounting
        if matched_prefix is not None:
            self.matched_prefix_tokens = accounting.admit_count(
                self, "matched_prefix_tokens", matched_prefix, field="prompt.matched_prefix_tokens")
        if reused_prefix is not None:
            self.reused_prefix_tokens = accounting.admit_count(
                self, "reused_prefix_tokens", reused_prefix, field="prompt.reused_prefix_tokens")
        if evaluated is not None:
            self.evaluated_tokens = accounting.admit_count(
                self, "evaluated_tokens", evaluated, field="prompt.evaluated_tokens")
        if replayed is not None:
            self.replayed_tokens = accounting.admit_count(
                self, "replayed_tokens", replayed, field="prompt.replayed_tokens")
        if non_prefix_reused is not None:
            self.non_prefix_reused_tokens = accounting.admit_count(
                self, "non_prefix_reused_tokens", non_prefix_reused, field="prompt.non_prefix_reused_tokens")
        if evaluation_work is not None:
            self.evaluation_work_tokens = accounting.admit_count(
                self, "evaluation_work_tokens", evaluation_work, field="prompt.evaluation_work_tokens")
        if first_divergent is not None:
            self.first_divergent_token_index = accounting.admit_count(
                self, "first_divergent_token_index", first_divergent,
                field="prompt.first_divergent_token_index")
        if source is not None:
            self.cache_source = source
        if disposition is not None:
            self.cache_disposition = disposition
        if reason_code is not None:
            self.cache_reason_code = reason_code
        if restore_attempted is not None:
            self.cache_restore_attempted = restore_attempted
        if restore_succeeded is not None:
            self.cache_restore_succeeded = restore_succeeded
        if restore_ms is not None:
            from serve.reqtelemetry import accounting
            self.cache_restore_ms = accounting.admit_duration(
                self, "restore_ms", restore_ms, field="cache.restore_ms")
        if recurrent_state is not None:
            self.cache_recurrent_state = recurrent_state
        if attention_state is not None:
            self.cache_attention_state = attention_state
        if checkpoint_state is not None:
            self.cache_checkpoint_state = checkpoint_state
        if invalidations is not None:
            from serve.reqtelemetry import accounting
            self.cache_invalidations = accounting.admit_count(
                self, "invalidations", invalidations, field="cache.invalidations")
        if evictions is not None:
            from serve.reqtelemetry import accounting
            self.cache_evictions = accounting.admit_count(
                self, "evictions", evictions, field="cache.evictions")

    def set_generation(self, *, requested_max=None, effective_max=None, generated=None, emitted=None,
                       draft_tokens=None, accepted_tokens=None, finish_reason=None):
        """What was generated.  `requested_max` is what the client asked for; `effective_max` is what the server
        actually allowed (the context's room, a budget).  They are kept apart on purpose."""
        from serve.reqtelemetry import accounting
        if requested_max is not None:
            self.requested_max_output_tokens = accounting.admit_count(
                self, "requested_max_output_tokens", requested_max,
                field="generation.requested_max_output_tokens")
        if effective_max is not None:
            self.effective_max_output_tokens = accounting.admit_count(
                self, "effective_max_output_tokens", effective_max,
                field="generation.effective_max_output_tokens")
        if generated is not None:
            self.generated_tokens = accounting.admit_count(
                self, "generated_tokens", generated, field="generation.generated_tokens")
        if emitted is not None:
            self.emitted_tokens = accounting.admit_count(
                self, "emitted_tokens", emitted, field="generation.emitted_tokens")
        if draft_tokens is not None:
            self.speculative_draft_tokens = accounting.admit_count(
                self, "speculative_draft_tokens", draft_tokens,
                field="generation.speculative_draft_tokens")
        if accepted_tokens is not None:
            self.speculative_accepted_tokens = accounting.admit_count(
                self, "speculative_accepted_tokens", accepted_tokens,
                field="generation.speculative_accepted_tokens")
        if finish_reason is not None:
            self.finish_reason = finish_reason

    # ------------------------------------------------------------------ the native invocations (G1)
    def begin_invocation(self, invocation_id, ordinal=None, engine_instance_id=OMITTED, model_id=OMITTED,
                         build_revision=OMITTED):
        """The measurement receipt of ONE native dispatch (AMENDMENT-03, G1).

        The receipt is bound to the invocation id, the ordinal, the engine instance, the model and the build
        identity IMMEDIATELY BEFORE the dispatch, so the terminal evidence can be validated against exactly that
        identity - and against nothing else.  The receipt is created empty: a measurement that the invocation
        does not report stays null in it, and it never inherits a value from another invocation.

        ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D2a): the identity arguments distinguish OMITTED from
        EXPLICITLY UNKNOWN.  An argument that is not given at all falls back to the record's own identity (the
        compatibility path); an argument that is given as None means "this identity was NOT AVAILABLE at the
        dispatch" - and it stays unavailable.  The preparation-time identity is never substituted for it.
        """
        if invocation_id is None:
            return None
        existing = self.invocation_for(invocation_id)
        if existing is not None:
            return existing
        receipt = InvocationReceipt(invocation_id,
                                    int(ordinal) if ordinal else len(self.invocations) + 1,
                                    engine_instance_id=self.engine_instance_id if engine_instance_id is OMITTED
                                    else engine_instance_id,
                                    model_id=self.model_id if model_id is OMITTED else model_id,
                                    build_revision=self.build_revision if build_revision is OMITTED
                                    else build_revision)
        self.invocations_total += 1
        self.dispatched_ids.append(invocation_id)
        if len(self.dispatched_ids) > MAX_DISPATCHED_IDS:
            del self.dispatched_ids[:-MAX_DISPATCHED_IDS]
        self._add_receipt(receipt)
        return receipt

    def dispatched(self, invocation_id) -> bool:
        """Whether THIS request dispatched that invocation id (the dispatch boundary is the only authority)."""
        return invocation_id is not None and invocation_id in self.dispatched_ids

    def adopt_legacy_invocation(self, invocation_id, ordinal=None):
        """The COMPATIBILITY path: a receipt for an invocation id this request never dispatched.

        ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D2b): this operation is EXPLICIT and it is NOT a
        dispatch: the dispatch counter is not incremented and the id is not remembered as dispatched.  It exists
        for the callers that apply engine figures to a request that never went through the dispatch boundary (the
        predecessor's path); the production terminal path never uses it, so terminal evidence can never create a
        dispatch or resurrect a dropped receipt.
        """
        if invocation_id is None:
            return None
        existing = self.invocation_for(invocation_id)
        if existing is not None:
            return existing
        receipt = InvocationReceipt(invocation_id,
                                    int(ordinal) if ordinal else len(self.invocations) + 1,
                                    engine_instance_id=self.engine_instance_id,
                                    model_id=self.model_id,
                                    build_revision=self.build_revision)
        self._add_receipt(receipt)
        return receipt

    def invocation_for(self, invocation_id):
        """The receipt of one invocation id, or None."""
        if invocation_id is None:
            return None
        for receipt in self.invocations:
            if receipt.invocation_id == invocation_id:
                return receipt
        return None

    def _add_receipt(self, receipt):
        """Keep the receipt inside the documented bounds; a receipt that does not fit is COUNTED as a loss.

        ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D5): a receipt that cannot fit within the byte budget
        ON ITS OWN is refused: the predecessor admitted it when the history was empty, so one oversized receipt
        could exceed the whole budget.  The size is the receipt's ACTUAL serialized UTF-8 size; a receipt that
        cannot be serialized at all is refused too - a serialization failure is NOT a zero-byte receipt.
        """
        size = _receipt_size(receipt)
        if size is None:
            # the receipt cannot be serialized: its size is UNKNOWN, not zero.  It is refused and counted.
            self.invocations_dropped += 1
            self._note_drop()
            return
        receipt._size = size
        if size > MAX_INVOCATION_BYTES:
            # it cannot fit within the budget, not even alone: refused and counted as a loss
            self.invocations_dropped += 1
            self.invocations_dropped_bytes += size
            self._note_drop()
            return
        while self.invocations and (len(self.invocations) >= MAX_INVOCATION_RECORDS
                                    or self.invocations_bytes + size > MAX_INVOCATION_BYTES):
            dropped = self.invocations.pop(0)
            dropped_size = getattr(dropped, "_size", 0)
            self.invocations_bytes -= dropped_size
            self.invocations_dropped += 1
            self.invocations_dropped_bytes += dropped_size
        self.invocations.append(receipt)
        self.invocations_bytes += size
        self._sync_parent()
        self._merge_unavailable()
        self._note_drop()

    def _note_drop(self):
        """Publish the loss of a receipt: a dropped receipt is visible, never silent."""
        self._merge_unavailable()
        if self.invocations_dropped:
            self.mark_unavailable("invocations",
                                  f"{self.invocations_dropped} native invocation receipt(s) did not fit in the "
                                  f"record's bounds ({MAX_INVOCATION_RECORDS} receipts, {MAX_INVOCATION_BYTES} bytes) "
                                  f"and were dropped: the record does not show them")

    def revalidate_invocation_bytes(self):
        """ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (C5b, D5): the byte bound is re-checked AFTER the
        terminal measurements have been added.

        The receipt's size is measured when it is admitted - but the receipt grows afterwards: the terminal
        measurements (the durations, the generation counters, the reason) are added to it later.  The bound is
        therefore checked again here, on the receipts as they are published.
        """
        for receipt in list(self.invocations):
            size = _receipt_size(receipt)
            if size is None:
                # it cannot be serialized: it is not a zero-byte receipt, it is an unusable one
                self.invocations.remove(receipt)
                self.invocations_bytes -= getattr(receipt, "_size", 0)
                self.invocations_dropped += 1
                continue
            previous = getattr(receipt, "_size", 0)
            receipt._size = size
            self.invocations_bytes += size - previous
        # the oldest receipts go until the collection is inside the byte budget again
        while self.invocations and self.invocations_bytes > MAX_INVOCATION_BYTES:
            dropped = self.invocations.pop(0)
            self.invocations_bytes -= getattr(dropped, "_size", 0)
            self.invocations_dropped += 1
            self.invocations_dropped_bytes += getattr(dropped, "_size", 0)
        # a receipt that alone exceeds the budget does not fit either
        while self.invocations and getattr(self.invocations[0], "_size", 0) > MAX_INVOCATION_BYTES:
            dropped = self.invocations.pop(0)
            self.invocations_bytes -= getattr(dropped, "_size", 0)
            self.invocations_dropped += 1
            self.invocations_dropped_bytes += getattr(dropped, "_size", 0)
        self._sync_parent()
        self._note_drop()

    def _sync_parent(self):
        """The parent's native scalars describe ONE invocation - and only when that is unambiguous (G1).

        With one native invocation the parent's fields are that invocation's fields (the predecessor's contract).
        With more than one they would be a summary of several prompts, which is ambiguous: they are null, the
        record says so, and the per-invocation receipts carry the numbers.
        """
        if self.invocations_total <= 1:
            if len(self.invocations) == 1:
                self._mirror_receipt(self.invocations[0])
            self._merge_unavailable()
            return
        self._clear_native_fields()
        self._merge_unavailable()

    def _merge_unavailable(self):
        """The receipts' own "why this is missing" reasons reach the record too: the operator reads the record."""
        for receipt in self.invocations:
            for field, reason in receipt.unavailable.items():
                self.unavailable.setdefault(field, reason)

    def _mirror_receipt(self, receipt):
        """Copy one receipt's native measurements into the parent's fields (the unambiguous single-invocation
        case).  A REJECTED receipt is never mirrored: its numbers belong to somebody else."""
        if receipt.correlation == CORRELATION_REJECTED:
            return
        self.matched_prefix_tokens = receipt.matched_prefix_tokens
        self.reused_prefix_tokens = receipt.reused_prefix_tokens
        self.evaluated_tokens = receipt.evaluated_tokens
        self.replayed_tokens = receipt.replayed_tokens
        self.non_prefix_reused_tokens = receipt.non_prefix_reused_tokens
        self.evaluation_work_tokens = receipt.evaluation_work_tokens
        self.first_divergent_token_index = receipt.first_divergent_token_index
        self.cache_source = receipt.cache_source
        self.cache_disposition = receipt.cache_disposition
        self.cache_reason_code = receipt.cache_reason_code
        self.cache_restore_attempted = receipt.cache_restore_attempted
        self.cache_restore_succeeded = receipt.cache_restore_succeeded
        self.cache_restore_ms = receipt.cache_restore_ms
        self.cache_recurrent_state = receipt.cache_recurrent_state
        self.cache_attention_state = receipt.cache_attention_state
        self.cache_checkpoint_state = receipt.cache_checkpoint_state
        self.cache_invalidations = receipt.cache_invalidations
        self.cache_evictions = receipt.cache_evictions
        self.generated_tokens = receipt.generated_tokens
        self.speculative_draft_tokens = receipt.speculative_draft_tokens
        self.speculative_accepted_tokens = receipt.speculative_accepted_tokens
        self.slot_id = receipt.slot_id
        for name, value in receipt.timing.items():
            self.set_timing(name, value, receipt.timing_authority.get(name, "native_engine"))
        self.native_partial = receipt.native_partial
        self.measurements_invalid = receipt.measurements_invalid
        self.native_correlation = receipt.correlation

    def _clear_native_fields(self):
        """The parent's native fields are AMBIGUOUS (more than one invocation): they are null, not a guess."""
        self.matched_prefix_tokens = None
        self.reused_prefix_tokens = None
        self.evaluated_tokens = None
        self.replayed_tokens = None
        self.non_prefix_reused_tokens = None
        self.evaluation_work_tokens = None
        self.first_divergent_token_index = None
        self.cache_source = SOURCE_UNKNOWN
        self.cache_disposition = DISPOSITION_UNKNOWN
        self.cache_reason_code = None
        self.cache_restore_attempted = None
        self.cache_restore_succeeded = None
        self.cache_restore_ms = None
        self.cache_recurrent_state = None
        self.cache_attention_state = None
        self.cache_checkpoint_state = None
        self.cache_invalidations = None
        self.cache_evictions = None
        self.generated_tokens = None
        self.speculative_draft_tokens = None
        self.speculative_accepted_tokens = None
        self.slot_id = None
        self.measurements_invalid = any(receipt.measurements_invalid for receipt in self.invocations)
        for name in ("cache_lookup", "cache_restore", "prefill_wall", "decode_wall"):
            self.timing.pop(name, None)
            self.timing_authority.pop(name, None)
        self.native_partial = any(receipt.native_partial for receipt in self.invocations)



    # ------------------------------------------------------------------ the accounting rules
    def seal(self, state=None, http_status=None, finish_reason=None, detail=None):
        """Close the record: the state it ended in, and the checks that describe how complete it is.

        A record that was cancelled or that failed keeps the measurements it HAS (the work the engine really did) and
        says that the accounting is partial.  Nothing is invented to make it look complete.
        """
        if state is not None:
            self.state = state
        if http_status is not None:
            self.http_status = int(http_status)
        if finish_reason is not None:
            self.finish_reason = finish_reason
        if detail is not None:
            self.outcome_detail = detail
        self.finished_at = time.time()
        # AMENDMENT-03 (G1): every receipt closes with its OWN accounting, and the parent is re-synced: the
        # parent's native scalars are the single invocation's, or null when the request dispatched more than one.
        for receipt in self.invocations:
            receipt.seal()
            # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D4): an invocation whose terminal evidence never
            # arrived is NOT presented as running.  The request is over, so nothing is still executing: the state
            # says "unknown" and the receipt says why.  Missing telemetry is not a failure of the inference.
            if receipt.state == "running":
                receipt.state = "unknown"
                receipt.mark_unavailable("terminal_evidence",
                                        "the native invocation's terminal evidence never arrived: its outcome is "
                                        "unknown", INSTRUMENTATION_ERROR)
        # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (C5b, D5): the receipts have just received their
        # terminal measurements, so their serialized size is re-checked against the byte budget NOW.
        self.revalidate_invocation_bytes()
        self._sync_parent()
        self.cache_disposition = self.derive_disposition()
        if self.state in ("cancelled", "failed", "rejected") and self.quality == COMPLETE:
            self.quality = PARTIAL
        if self.non_prefix_reused_tokens is None and self.reused_prefix_tokens is not None:
            # Strata's execution path reuses a CONTIGUOUS prefix only, so the reuse outside the prefix is a
            # STRUCTURAL ZERO, not an unmeasured value (include/strata/program/reqtelemetry.hpp,
            # TokenAccounting::non_prefix_reused).  It is written here so the conservation identity can be evaluated
            # instead of being left unevaluated for every request.
            self.non_prefix_reused_tokens = 0
        accounting = self.accounting_state()
        self.accounting = accounting
        if accounting["state"] == "violated":
            self.quality = PARTIAL
            self.unavailable.setdefault("accounting", "the token accounting does not close (see conservation)")
        return self

    # ------------------------------------------------------------------ the accounting rules
    def derive_disposition(self):
        """The cache disposition, from the evidence and nothing else (serve/reqtelemetry/accounting.py)."""
        from serve.reqtelemetry import accounting
        return accounting.derive_disposition(self)

    def conservation(self) -> list:
        """The accounting identities that must hold - CHECKED, never enforced (serve/reqtelemetry/accounting.py)."""
        from serve.reqtelemetry import accounting
        return accounting.conservation(self)

    def identity_evaluable(self) -> bool:
        """Whether the sum identity can be evaluated at all (serve/reqtelemetry/accounting.py)."""
        from serve.reqtelemetry import accounting
        return accounting.identity_evaluable(self)

    def accounting_state(self) -> dict:
        """The accounting's own state: satisfied, violated or unevaluated (serve/reqtelemetry/accounting.py)."""
        from serve.reqtelemetry import accounting
        return accounting.accounting_state(self)

    # ------------------------------------------------------------------ the record itself
    def to_dict(self) -> dict:
        """The canonical record: the sections, in a fixed order, metadata only."""
        return {
            "schema_version": SCHEMA_VERSION,
            "identity": {
                "request_id": self.request_id,
                "client_request_id": self.client_request_id,
                "engine_instance_id": self.engine_instance_id,
                "server_instance_id": self.server_instance_id,
                "engine_invocation_id": self.engine_invocation_id,
                "engine_invocation_ordinal": self.engine_invocation_ordinal,
                "slot_id": self.slot_id,
                "model_id": self.model_id,
                "build_revision": self.build_revision,
            },
            "lifecycle": {
                "state": self.state,
                "api": self.api,
                "received_at": self.received_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "http_status": self.http_status,
                "finish_reason": self.finish_reason,
                "detail": self.outcome_detail,
            },
            "prompt": {
                "rendered_tokens": self.rendered_tokens,
                "submitted_tokens": self.submitted_tokens,
                "matched_prefix_tokens": self.matched_prefix_tokens,
                "reused_prefix_tokens": self.reused_prefix_tokens,
                "evaluated_tokens": self.evaluated_tokens,
                "replayed_tokens": self.replayed_tokens,
                "non_prefix_reused_tokens": self.non_prefix_reused_tokens,
                "evaluation_work_tokens": self.evaluation_work_tokens,
                "first_divergent_token_index": self.first_divergent_token_index,
            },
            "cache": {
                "source": self.cache_source,
                "disposition": self.cache_disposition,
                "reason_code": self.cache_reason_code,
                "restore_attempted": self.cache_restore_attempted,
                "restore_succeeded": self.cache_restore_succeeded,
                "restore_ms": self.cache_restore_ms,
                "recurrent_state": self.cache_recurrent_state,
                "attention_state": self.cache_attention_state,
                "checkpoint_state": self.cache_checkpoint_state,
                "invalidations": self.cache_invalidations,
                "evictions": self.cache_evictions,
            },
            "timing_ms": {k: self.timing[k] for k in sorted(self.timing)},
            # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-03 (G1): the per-invocation receipts.  Each one
            # carries its own measurements, its own correlation and its own admission decisions; the parent's
            # native scalars above are null when the request dispatched more than one invocation.
            "invocations": [receipt.to_dict() for receipt in self.invocations],
            "generation": {
                "requested_max_output_tokens": self.requested_max_output_tokens,
                "effective_max_output_tokens": self.effective_max_output_tokens,
                "generated_tokens": self.generated_tokens,
                "emitted_tokens": self.emitted_tokens,
                "speculative_draft_tokens": self.speculative_draft_tokens,
                "speculative_accepted_tokens": self.speculative_accepted_tokens,
            },
            "measurement_quality": {
                "state": self.quality,
                "unavailable_fields": dict(sorted(self.unavailable.items())),
                "timing_authority": dict(sorted(self.timing_authority.items())),
                "first_token_includes_reasoning": self.first_token_includes_reasoning,
                # AMENDMENT-02 (G1): the record says whether its numbers may enter the authoritative aggregates,
                # and why not when they may not.  The three decisions stay apart: the measurements are valid, the
                # accounting is not violated, and the engine's receipt is correlated to this request.
                "native_correlation": self.aggregate_correlation(),
                # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D6): the correlation of the RETAINED
                # evidence and the correlation of the WHOLE dispatched population are different claims.  A receipt
                # that was dropped means the request's evidence is incomplete, even when every receipt that
                # survived is verified.
                "native_correlation_complete": self.correlation_complete(),
                "native_partial": self.native_partial,
                "measurement_valid": self.measurement_valid(),
                "aggregate_eligible": self.aggregate_eligible(),
                "accounting": {"state": self.accounting.get("state", "unevaluated"),
                               "valid": self.accounting.get("valid"),
                               "problems": list(self.accounting.get("problems") or [])},
                # AMENDMENT-03 (G2): the admission decisions are PER METRIC CLASS.  One global predicate for
                # every measurement is what admitted an uncorrelated duration and an unevaluated accounting to
                # aggregates they do not belong in.
                "admission": {metric: self.metric_admission(metric) for metric in METRIC_CLASSES},
                # AMENDMENT-03 (G1): the invocation history of this request and its bounds
                "invocation_count": len(self.invocations),
                "invocations_dispatched": self.invocations_total,
                "invocations_dropped": self.invocations_dropped,
                # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D5): the bytes of the dropped receipts are
                # published beside the count: a lost receipt is visible in both.
                "invocation_dropped_bytes": self.invocations_dropped_bytes,
                "invocation_bytes": self.invocations_bytes,
            },
        }

    def aggregate_correlation(self) -> str:
        """The record's correlation state: the receipts' OWN states (G1).

        One receipt: its own state.  Several receipts: VERIFIED only when every one of them is verified; a
        rejected receipt (a foreign or a stale one) makes the record's state rejected - the record then says
        that something was wrong with the evidence.  Anything else is unavailable, never an asserted join.
        """
        if not self.invocations:
            return self.native_correlation
        states = [receipt.correlation for receipt in self.invocations]
        if any(state == CORRELATION_REJECTED for state in states):
            return CORRELATION_REJECTED
        if all(state == CORRELATION_VERIFIED for state in states):
            return CORRELATION_VERIFIED
        return CORRELATION_UNAVAILABLE

    def correlation_complete(self) -> bool:
        """Whether the native correlation covers the WHOLE dispatched population (D6).

        The RETAINED evidence may be fully verified while the request's evidence is incomplete: a receipt that
        did not fit the bounds was dropped, and the evidence of that invocation is lost.  The record then says so
        instead of claiming a complete request-level native correlation.
        """
        if self.invocations_dropped:
            return False
        if self.invocations_total != len(self.invocations):
            return False
        return self.aggregate_correlation() == CORRELATION_VERIFIED

    def metric_admission(self, metric: str) -> bool:
        """Whether this RECORD's own measurements of one metric class may enter an authoritative aggregate.

        The record's native fields are the single invocation's - so they are admitted exactly when that
        invocation is.  With more than one invocation the parent's native fields are null (ambiguous), so the
        native classes are not admitted at the record level: each receipt decides for itself.
        """
        from serve.reqtelemetry import accounting
        if metric == accounting.METRIC_HTTP:
            return True
        if self.invocations_total > 1:
            return False
        return accounting.invocation_admission(self, metric)

    # ------------------------------------------------------------------ the admission decisions
    def measurement_valid(self) -> bool:
        """Whether the record's own numbers are measurements at all (whole, non-negative counts)."""
        from serve.reqtelemetry import accounting
        return accounting.measurement_valid(self)

    def aggregate_eligible(self) -> bool:
        """Whether this record may contribute to the authoritative aggregates (serve/reqtelemetry/accounting.py)."""
        from serve.reqtelemetry import accounting
        return accounting.aggregate_eligible(self)
