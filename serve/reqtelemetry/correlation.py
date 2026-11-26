"""serve/reqtelemetry/correlation.py - the native receipt and the request it belongs to (G2, G9).

The engine echoes the request's own id on its DONE line.  A receipt that carries ANOTHER request's id is foreign:
none of its numbers are attached to the receiving request, its aggregates stay clean, and the request says it had
an instrumentation error.  A receipt with no id at all (an older engine) leaves the correlation explicitly
unavailable - never an asserted join.
"""
from __future__ import annotations

import uuid

from serve.reqtelemetry.accounting import (CORRELATION_NOT_APPLICABLE, CORRELATION_REJECTED, CORRELATION_UNAVAILABLE,
                                            CORRELATION_VERIFIED)
from serve.reqtelemetry.record import RequestRecord
from serve.reqtelemetry.vocabulary import (INSTRUMENTATION_ERROR, SOURCE_CONVERSATION_CACHE, SOURCE_MULTIPLE,
                                         SOURCE_NONE, SOURCE_RESIDENT_SLOT, SOURCE_RESTORED_CHECKPOINT,
                                         SOURCE_UNKNOWN)

SOURCE_NAMES = {
    "none": SOURCE_NONE,
    "live": SOURCE_RESIDENT_SLOT,
    "active_checkpoint": SOURCE_CONVERSATION_CACHE,
    "parked_live": SOURCE_CONVERSATION_CACHE,
    "parked_checkpoint": SOURCE_RESTORED_CHECKPOINT,
    "slot": SOURCE_RESIDENT_SLOT,
}

# The engine's reason names (cache_diag::Reason) mapped to the canonical reason codes.  They are the engine's own
# words for why it did what it did, kept as they are: an operator who knows the engine's log reads them.
REASON_CODES = {
    "EXACT_MATCH": "exact_match",
    "TOKEN_MISMATCH": "token_mismatch",
    "IMAGE_MISMATCH": "image_mismatch",
    "STEERING_MISMATCH": "steering_mismatch",
    "ABSENT": "absent",
    "INELIGIBLE": "ineligible",
    "EVICTED": "evicted",
    "RETENTION_REMOVED": "retention_removed",
    "CACHE_DISABLED": "cache_disabled",
    "BUDGET_REFUSED": "budget_refused",
    "SUPERSEDED": "superseded",
    "BORROWED": "borrowed",
    "SLOT_SOURCE": "slot_source",
    "UNKNOWN": "unknown",
}


def new_invocation_id() -> str:
    """A fresh id for ONE native execution attempt (AMENDMENT-02, G2/A2).

    Three identities are kept apart: the PHYSICAL HTTP REQUEST's id (the record's own), the NATIVE INVOCATION's id
    (this one - a new one for every dispatch, including a recovery dispatch inside the same request) and the ENGINE
    INSTANCE's id.  The id is hexadecimal, because that is what the native protocol's `rid=` field accepts.
    """
    return uuid.uuid4().hex


def _admit(record, name, value):
    """One native measurement, at the admission boundary (AMENDMENT-02, G1).

    A measurement that is not a whole, non-negative number is REFUSED: it is not written into the record, the field
    stays null and the record says why.  A refused measurement is never clamped, coerced or counted - and the
    record is marked as carrying an invalid measurement, so it does not enter the authoritative aggregates.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        record.measurements_invalid = True
        record.mark_unavailable(f"prompt.{name}",
                                f"the engine reported a {name} that is not a whole, non-negative token count",
                                INSTRUMENTATION_ERROR)
        return None
    return value


def apply_engine(record: RequestRecord, figures: dict | None, expected_invocation_id: str | None = None):
    """The engine's own measurements for this request, into the record.

    `figures` is the `telemetry` part of the engine's DONE line: what the engine measured about the cache and about
    the work it did.  A field the engine did not send stays null - it is NOT a zero, and it is NOT guessed from the
    server's own timings.

    AMENDMENT-02 (G2/A2): the receipt is bound to the NATIVE INVOCATION, not to the request.  The server knows which
    invocation it dispatched (it generated the id itself, immediately before the dispatch) and the engine echoes
    that id on its DONE line.  A receipt that carries ANOTHER invocation's id is FOREIGN: none of its numbers are
    attached to this request - not even the positional DONE fields outside the telemetry suffix - its aggregates stay
    clean, and the request says it had an instrumentation error.  A receipt with no id at all (an older engine)
    leaves the correlation explicitly unavailable - never an asserted join.

    The return value is the VERDICT: {"correlation": ..., "admitted": bool}.  The caller uses it to decide whether
    the receipt's other fields (the timings, the generated count) may be applied at all.
    """
    if not figures:
        record.mark_unavailable("cache", "the engine reported no cache measurements for this request")
        record.mark_unavailable("prompt.matched_prefix_tokens", "the engine reported no cache measurements")
        record.native_correlation = CORRELATION_UNAVAILABLE
        return {"correlation": CORRELATION_UNAVAILABLE, "admitted": False}
    # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-01 (G2): the receipt is BOUND to the request that asked for
    # it.  The engine echoes the request's own id on its DONE line; a receipt that carries another request's id is
    # FOREIGN and none of its numbers are attached to this record (the aggregate counters are not touched either -
    # this record never sees them).  The request itself goes on: a telemetry problem never decides an inference.
    rid = figures.get("rid")
    # the expectation: the invocation this request dispatched.  A record that never dispatched one falls back to
    # the request's own id (the predecessor's rule), so an older caller still gets the same protection.
    expected = expected_invocation_id
    if expected is None:
        expected = record.engine_invocation_id
    if expected is None:
        expected = record.request_id
    if rid is not None and expected is not None and rid != expected:
        record.mark_unavailable("engine_telemetry",
                                "the engine's receipt carried another invocation's id: its measurements were not "
                                "attached to this request", INSTRUMENTATION_ERROR)
        record.native_correlation = CORRELATION_REJECTED
        # the foreign id is NOT recorded as this request's invocation: the receipt belongs to somebody else
        record.engine_invocation_id = None
        return {"correlation": CORRELATION_REJECTED, "admitted": False}
    if rid and expected is not None:
        record.native_correlation = CORRELATION_VERIFIED
        record.engine_invocation_id = rid
    elif rid:
        # an id the server cannot check against an invocation it dispatched: the correlation stays unavailable
        record.native_correlation = CORRELATION_UNAVAILABLE
        record.engine_invocation_id = rid
        record.mark_unavailable("identity.engine_invocation_id",
                                "the engine's receipt carried an id, but this request did not dispatch that "
                                "invocation: the native measurements cannot be tied to it by id")
    else:
        # An older engine does not echo the id: the correlation is UNAVAILABLE, never an asserted join.
        record.native_correlation = CORRELATION_UNAVAILABLE
        record.mark_unavailable("identity.engine_invocation_id",
                                "the engine did not echo the invocation's id (an older engine): the native "
                                "invocation cannot be tied to this request by id")

    matched = _admit(record, "matched_prefix_tokens", figures.get("matched"))
    reused = _admit(record, "reused_prefix_tokens", figures.get("reused"))
    evaluated = _admit(record, "evaluated_tokens", figures.get("evaluated"))
    replayed = _admit(record, "replayed_tokens", figures.get("replayed"))
    work = _admit(record, "evaluation_work_tokens", figures.get("work"))

    # The engine writes the divergent index as: a position (0 or more), -1 for "the sequences agree throughout"
    # and -2 for "not measured".  The record's field is null in both of those cases - there is no mismatch to
    # report - and the reason says which of the two it was.
    divergent = figures.get("divergent")
    if divergent is not None:
        if divergent >= 0:
            record.first_divergent_token_index = int(divergent)
        elif divergent == -1:
            record.mark_unavailable("prompt.first_divergent_token_index",
                                    "the sequences agree throughout: there is no mismatch")
        else:
            record.mark_unavailable("prompt.first_divergent_token_index",
                                    "the engine did not report a divergence index")
    record.set_native_cache(
        matched_prefix=matched, reused_prefix=reused, evaluated=evaluated,
        replayed=replayed, evaluation_work=work,
        source=SOURCE_NAMES.get(figures.get("cache_source", ""), SOURCE_UNKNOWN),
        reason_code=REASON_CODES.get(figures.get("cache_reason", ""), "unknown"),
        restore_attempted=(figures.get("restore") != "none") if "restore" in figures else None,
        restore_succeeded=(figures.get("restore") == "succeeded") if "restore" in figures else None,
        restore_ms=figures.get("restore_ms"),
        invalidations=figures.get("invalidations"), evictions=figures.get("evictions"))
    # the engine's own durations: the lookup and the restoration it measured
    if figures.get("lookup_ms") is not None:
        record.set_timing("cache_lookup", figures["lookup_ms"], "native_engine")
    if figures.get("restore_ms") is not None:
        record.set_timing("cache_restore", figures["restore_ms"], "native_engine")
    if "slot" in figures:
        slot = figures["slot"]
        # the engine writes a slot only when there is one; a stray negative is "no slot", not a slot
        record.slot_id = int(slot) if isinstance(slot, int) and not isinstance(slot, bool) and slot >= 0 else None
    if matched is None:
        record.mark_unavailable("prompt.matched_prefix_tokens", "the engine did not report a prefix match")
    if reused is None:
        record.mark_unavailable("prompt.reused_prefix_tokens", "the engine did not report a reused prefix")
    if evaluated is None:
        record.mark_unavailable("prompt.evaluated_tokens", "the engine did not report the tokens it evaluated")
    # AMENDMENT-02 (G1): the receipt's measurements are in the record, but they are only AUTHORITATIVE when the
    # correlation was verified.  An unavailable correlation (an older engine) keeps the numbers as diagnostics.
    return {"correlation": record.native_correlation, "admitted": record.native_correlation == CORRELATION_VERIFIED}
