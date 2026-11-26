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

from serve.reqtelemetry.vocabulary import (CLIENT_ID_ALLOWED, CLIENT_ID_MAX, COMPLETE, DEFAULT_PAGE_SIZE,
                                         DEFAULT_RETENTION_BYTES, DEFAULT_RETENTION_RECORDS, DISPOSITIONS,
                                         DISPOSITION_BYPASSED, DISPOSITION_COLD_MISS, DISPOSITION_FULL_HIT,
                                         DISPOSITION_INVALIDATED, DISPOSITION_MATCH_WITHOUT_STATE,
                                         DISPOSITION_PARTIAL_HIT, DISPOSITION_UNKNOWN, INSTRUMENTATION_ERROR,
                                         MAXIMUM_PAGE_SIZE, PARTIAL, SCHEMA_VERSION, SOURCES, SOURCE_CONVERSATION_CACHE,
                                         SOURCE_MULTIPLE, SOURCE_NONE, SOURCE_RESIDENT_SLOT,
                                         SOURCE_RESTORED_CHECKPOINT, SOURCE_UNKNOWN, STATES, UNSUPPORTED)

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
        """A duration in milliseconds, from a monotonic clock, with the authority that measured it."""
        value = _num(ms)
        if value is None:
            return
        self.timing[name] = round(float(value), 3)
        self.timing_authority[name] = authority

    def set_prompt_tokens(self, rendered=None, submitted=None, authority="server"):
        """The prompt's token counts.  `rendered` is the count after the template render and the tokenization;
        `submitted` is what the engine was actually given (the two differ when the server truncates)."""
        if rendered is not None:
            self.rendered_tokens = _num(rendered)
        if submitted is not None:
            self.submitted_tokens = _num(submitted)

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
        if matched_prefix is not None:
            self.matched_prefix_tokens = _num(matched_prefix)
        if reused_prefix is not None:
            self.reused_prefix_tokens = _num(reused_prefix)
        if evaluated is not None:
            self.evaluated_tokens = _num(evaluated)
        if replayed is not None:
            self.replayed_tokens = _num(replayed)
        if non_prefix_reused is not None:
            self.non_prefix_reused_tokens = _num(non_prefix_reused)
        if evaluation_work is not None:
            self.evaluation_work_tokens = _num(evaluation_work)
        if first_divergent is not None:
            self.first_divergent_token_index = _num(first_divergent)
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
            self.cache_restore_ms = _num(restore_ms)
        if recurrent_state is not None:
            self.cache_recurrent_state = recurrent_state
        if attention_state is not None:
            self.cache_attention_state = attention_state
        if checkpoint_state is not None:
            self.cache_checkpoint_state = checkpoint_state
        if invalidations is not None:
            self.cache_invalidations = _num(invalidations)
        if evictions is not None:
            self.cache_evictions = _num(evictions)

    def set_generation(self, *, requested_max=None, effective_max=None, generated=None, emitted=None,
                       draft_tokens=None, accepted_tokens=None, finish_reason=None):
        """What was generated.  `requested_max` is what the client asked for; `effective_max` is what the server
        actually allowed (the context's room, a budget).  They are kept apart on purpose."""
        if requested_max is not None:
            self.requested_max_output_tokens = _num(requested_max)
        if effective_max is not None:
            self.effective_max_output_tokens = _num(effective_max)
        if generated is not None:
            self.generated_tokens = _num(generated)
        if emitted is not None:
            self.emitted_tokens = _num(emitted)
        if draft_tokens is not None:
            self.speculative_draft_tokens = _num(draft_tokens)
        if accepted_tokens is not None:
            self.speculative_accepted_tokens = _num(accepted_tokens)
        if finish_reason is not None:
            self.finish_reason = finish_reason

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
                "native_correlation": self.native_correlation,
                "native_partial": self.native_partial,
                "measurement_valid": self.measurement_valid(),
                "aggregate_eligible": self.aggregate_eligible(),
                "accounting": {"state": self.accounting.get("state", "unevaluated"),
                               "valid": self.accounting.get("valid"),
                               "problems": list(self.accounting.get("problems") or [])},
            },
        }

    # ------------------------------------------------------------------ the admission decisions
    def measurement_valid(self) -> bool:
        """Whether the record's own numbers are measurements at all (whole, non-negative counts)."""
        from serve.reqtelemetry import accounting
        return accounting.measurement_valid(self)

    def aggregate_eligible(self) -> bool:
        """Whether this record may contribute to the authoritative aggregates (serve/reqtelemetry/accounting.py)."""
        from serve.reqtelemetry import accounting
        return accounting.aggregate_eligible(self)
