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


def _admit(target, name, value):
    """One native measurement, at the admission boundary (AMENDMENT-02, G1).

    A measurement that is not a whole, non-negative number is REFUSED: it is not written into the receipt, the
    field stays null and the receipt says why.  A refused measurement is never clamped, coerced or counted - and
    the receipt is marked as carrying an invalid measurement, so it does not enter the authoritative aggregates.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        target.measurements_invalid = True
        target.mark_unavailable(f"prompt.{name}",
                                f"the engine reported a {name} that is not a whole, non-negative token count",
                                INSTRUMENTATION_ERROR)
        return None
    return value


def _counter(value):
    """A native CUMULATIVE counter, with the engine's own sentinel for "not measured".

    The engine writes -1 for a counter it did not measure (include/strata/program/reqtelemetry.hpp) and leaves the
    key out of the DONE line entirely; the key=value reader here keeps whatever was on the line, so a -1 can
    reach this point.  It means "not measured" - it is NOT a negative count and NOT an invalid measurement: the
    field stays null and the receipt says it was not measured.  Every other value goes through the shared typed
    admission (a negative, a fraction and a bool are refused there).
    """
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool) and value == -1:
        return None
    return value


def normalize_terminal_evidence(figures: dict | None, positional: dict | None = None) -> dict:
    """The COMPLETE, NORMALIZED terminal evidence of ONE native dispatch (A3a).

    It is the evidence AS IT ARRIVED - not as it was applied - so that a second terminal receipt can be compared
    with the accepted one field by field.  It covers the cache figures, the durations, the POSITIONAL DONE fields,
    the generation counters, the partial classification, the native finish reason, the native terminal state and
    the id the engine echoed.  Five prompt counters are not a terminal evidence: a duplicate that changed a
    duration, a generation count, the restoration's outcome or the native outcome is a CONFLICT.
    """
    figures = figures or {}
    positional = positional or {}
    return {
        "rid": figures.get("rid"),
        "cache": {key: figures.get(key) for key in
                  ("matched", "reused", "evaluated", "replayed", "work", "divergent", "cache_source",
                   "cache_reason", "restore", "restore_ms", "invalidations", "evictions", "slot")},
        "timing_ms": {"cache_lookup": figures.get("lookup_ms"),
                      "cache_restore": figures.get("restore_ms")},
        "position": {"prompt_ms": positional.get("prompt_ms"),
                     "decode_ms": positional.get("decode_ms")},
        "generation": {"generated": positional.get("generated"),
                       "drafts_offered": positional.get("drafts_offered"),
                       "drafts_accepted": positional.get("drafts_accepted"),
                       "finish_reason": positional.get("finish")},
        "partial": bool(positional.get("native_segment_only")),
        "state": positional.get("native_state"),
    }


def native_terminal_state(finish) -> str:
    """The terminal outcome of ONE native dispatch, from ITS OWN evidence (A3b).

    ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (A3b): the native outcome is the NATIVE
    dispatch's own, never the physical HTTP request's.  An invocation that failed stays failed when the request
    recovers; an invocation that completed natively stays completed when the HTTP delivery fails afterwards.  An
    outcome that is not known stays unknown - it is never taken from the request's outcome or from the position of
    the dispatch in a list.
    """
    if finish is None:
        return "unknown"
    if finish in ("completed", "stop", "length"):
        return "completed"
    if finish in ("cancel", "cancelled", "disconnect"):
        return "cancelled"
    if finish in ("error", "failed", "nonfinite"):
        return "failed"
    return "unknown"


def _duplicate_verdict(record: RequestRecord, receipt, incoming: dict, expected):
    """A SECOND terminal receipt for an invocation whose terminal evidence was already ACCEPTED (A3a).

    The accepted snapshot is NOT touched: no measurement is updated, the correlation is not changed and the
    positional measurements are not reapplied.  An identical duplicate is ignored; a conflicting or a foreign one
    is reported as explicit instrumentation evidence.
    """
    accepted = receipt.terminal_evidence or {}
    if incoming == accepted:
        # the SAME evidence, seen twice: nothing is updated, nothing is counted twice
        return {"correlation": receipt.correlation, "admitted": receipt.correlation == CORRELATION_VERIFIED,
                "duplicate": True}
    rid = incoming.get("rid")
    foreign = rid is not None and expected is not None and rid != expected
    if foreign:
        reason = ("a second terminal receipt for this invocation carried ANOTHER invocation's id: the accepted "
                  "terminal evidence was kept and the foreign receipt was not attached")
    else:
        reason = ("a second terminal receipt for this invocation carried DIFFERENT terminal evidence: the "
                  "accepted evidence was kept and the conflict is reported")
    receipt.mark_unavailable("engine_telemetry", reason, INSTRUMENTATION_ERROR)
    record.mark_unavailable("engine_telemetry", reason, INSTRUMENTATION_ERROR)
    record.native_correlation = record.aggregate_correlation()
    record._sync_parent()
    return {"correlation": receipt.correlation, "admitted": False, "conflict": True, "foreign": foreign}


def apply_engine(record: RequestRecord, figures: dict | None, expected_invocation_id: str | None = None,
                 receipt=None, terminal_state: str = "completed", native_segment_only: bool = False,
                 positional: dict | None = None, native_state: str | None = None):
    """The engine's own measurements for ONE native invocation, into ITS receipt (AMENDMENT-03, G1).

    `figures` is the `telemetry` part of the engine's DONE line: what the engine measured about the cache and about
    the work it did.  A field the engine did not send stays null - it is NOT a zero, and it is NOT guessed from the
    server's own timings.

    AMENDMENT-02 (G2/A2): the receipt is bound to the NATIVE INVOCATION, not to the request.  AMENDMENT-03 (G1):
    it is bound to the receipt of THAT invocation - every dispatch owns its own measurements, and a measurement
    of one invocation is never published under the identity of another one.  The server knows which invocation it
    dispatched (it generated the id itself, immediately before the dispatch) and the engine echoes that id on its
    DONE line.  A receipt that carries ANOTHER invocation's id is FOREIGN: none of its numbers are attached to
    this request - not even the positional DONE fields outside the telemetry suffix - its aggregates stay clean,
    and the request says it had an instrumentation error.  A receipt with no id at all (an older engine) leaves
    the correlation explicitly unavailable - never an asserted join.

    The return value is the VERDICT: {"correlation": ..., "admitted": bool}.  The caller uses it to decide whether
    the receipt's other fields (the timings, the generated count) may be applied at all.
    """
    expected = expected_invocation_id
    if expected is None:
        expected = record.engine_invocation_id
    if expected is None:
        expected = record.request_id
    # the receipt this evidence belongs to: the one the server bound before the dispatch.
    #
    # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D2b): the terminal evidence may NOT create a dispatch.
    # The predecessor called `record.begin_invocation(expected)` here, so a receipt of an invocation this request
    # never dispatched - or of one whose receipt had already been dropped - produced a NEW dispatch: the
    # dispatched population grew and the retained population changed.  Now:
    #
    #   * the receipt of an invocation this request DISPATCHED is used, even when its measurements are already
    #     there (an identical duplicate is ignored, a conflicting one is reported);
    #   * a receipt of an invocation this request did NOT dispatch is refused: it is not attached to anything,
    #     it does not create a dispatch and it does not resurrect a dropped receipt;
    #   * the compatibility path (a caller that never went through the dispatch boundary) is EXPLICIT:
    #     `adopt_legacy_invocation` - it does not count as a dispatch.
    if receipt is None:
        receipt = record.invocation_for(expected)
    if receipt is None:
        if expected is not None and (record.invocations or record.dispatched(expected)):
            # the receipt of an invocation this request dispatched (and whose receipt was dropped) or of one it
            # never dispatched: the evidence belongs to nobody.  It is not attached to anything, it does not
            # create a dispatch and it does not resurrect a dropped receipt.
            record.mark_unavailable("engine_telemetry",
                                    "the engine's receipt carried the id of a native invocation whose receipt "
                                    "this request does not hold: its measurements were not attached",
                                    INSTRUMENTATION_ERROR)
            record.native_correlation = record.aggregate_correlation()
            record._sync_parent()
            return {"correlation": CORRELATION_REJECTED, "admitted": False}
        # the compatibility path: a caller that never went through the dispatch boundary
        receipt = record.adopt_legacy_invocation(expected)
    # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (A3a): the incoming evidence, normalized.
    # It is built BEFORE anything is applied, so the comparison below cannot be influenced by an application.
    incoming = normalize_terminal_evidence(figures, positional)
    # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (A3a): an ACCEPTED terminal receipt is never
    # silently overwritten.  The comparison is the COMPLETE evidence, and it happens BEFORE any measurement is
    # applied: an identical duplicate performs no update at all, a conflicting or a foreign one keeps the accepted
    # snapshot and is reported.
    if receipt.terminal_accepted:
        return _duplicate_verdict(record, receipt, incoming, expected)
    if not figures:
        receipt.correlation = CORRELATION_UNAVAILABLE
        receipt.mark_unavailable("cache", "the engine reported no cache measurements for this invocation")
        receipt.mark_unavailable("prompt.matched_prefix_tokens", "the engine reported no cache measurements")
        record.mark_unavailable("cache", "the engine reported no cache measurements for this request")
        record.mark_unavailable("prompt.matched_prefix_tokens", "the engine reported no cache measurements")
        record.native_correlation = record.aggregate_correlation()
        record._sync_parent()
        return {"correlation": CORRELATION_UNAVAILABLE, "admitted": False}
    # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-01 (G2): the receipt is BOUND to the request that asked for
    # it.  The engine echoes the request's own id on its DONE line; a receipt that carries another request's id is
    # FOREIGN and none of its numbers are attached to this record (the aggregate counters are not touched either -
    # this record never sees them).  The request itself goes on: a telemetry problem never decides an inference.
    rid = figures.get("rid")
    if rid is not None and expected is not None and rid != expected:
        receipt.correlation = CORRELATION_REJECTED
        receipt.mark_unavailable("engine_telemetry",
                                 "the engine's receipt carried another invocation's id: its measurements were "
                                 "not attached to this invocation", INSTRUMENTATION_ERROR)
        record.mark_unavailable("engine_telemetry",
                                "the engine's receipt carried another invocation's id: its measurements were not "
                                "attached to this request", INSTRUMENTATION_ERROR)
        record.native_correlation = record.aggregate_correlation()
        record._sync_parent()
        return {"correlation": CORRELATION_REJECTED, "admitted": False}
    if rid and expected is not None:
        receipt.correlation = CORRELATION_VERIFIED
        if record.engine_invocation_id is None:
            # the dispatcher owns the record's invocation id (it is the LAST dispatch's id); the receipt's id
            # is never written over it - an earlier invocation's receipt must not become the record's identity
            record.engine_invocation_id = rid
    elif rid:
        # an id the server cannot check against an invocation it dispatched: the correlation stays unavailable
        receipt.correlation = CORRELATION_UNAVAILABLE
        receipt.mark_unavailable("identity.engine_invocation_id",
                                 "the engine's receipt carried an id, but this request did not dispatch that "
                                 "invocation: the native measurements cannot be tied to it by id")
    else:
        # An older engine does not echo the id: the correlation is UNAVAILABLE, never an asserted join.
        receipt.correlation = CORRELATION_UNAVAILABLE
        receipt.mark_unavailable("identity.engine_invocation_id",
                                 "the engine did not echo the invocation's id (an older engine): the native "
                                 "invocation cannot be tied to this request by id")

    matched = _admit(receipt, "matched_prefix_tokens", figures.get("matched"))
    reused = _admit(receipt, "reused_prefix_tokens", figures.get("reused"))
    evaluated = _admit(receipt, "evaluated_tokens", figures.get("evaluated"))
    replayed = _admit(receipt, "replayed_tokens", figures.get("replayed"))
    work = _admit(receipt, "evaluation_work_tokens", figures.get("work"))

    # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (A3a): the duplicate comparison itself now
    # happens ABOVE, before any measurement is applied - it compares the COMPLETE normalized terminal evidence
    # with the accepted snapshot, not five prompt counters.

    # The engine writes the divergent index as: a position (0 or more), -1 for "the sequences agree throughout"
    # and -2 for "not measured".  The receipt's field is null in both of those cases - there is no mismatch to
    # report - and the reason says which of the two it was.
    divergent = figures.get("divergent")
    if divergent is not None:
        if divergent >= 0:
            receipt.first_divergent_token_index = int(divergent)
        elif divergent == -1:
            receipt.mark_unavailable("prompt.first_divergent_token_index",
                                     "the sequences agree throughout: there is no mismatch")
        else:
            receipt.mark_unavailable("prompt.first_divergent_token_index",
                                     "the engine did not report a divergence index")
    receipt.set_native_cache(
        matched_prefix=matched, reused_prefix=reused, evaluated=evaluated,
        replayed=replayed, evaluation_work=work,
        source=SOURCE_NAMES.get(figures.get("cache_source", ""), SOURCE_UNKNOWN),
        reason_code=REASON_CODES.get(figures.get("cache_reason", ""), "unknown"),
        restore_attempted=(figures.get("restore") != "none") if "restore" in figures else None,
        restore_succeeded=(figures.get("restore") == "succeeded") if "restore" in figures else None,
        restore_ms=figures.get("restore_ms"),
        invalidations=_counter(figures.get("invalidations")),
        evictions=_counter(figures.get("evictions")))
    # the engine's own durations: the lookup and the restoration it measured
    # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D1): a duration that is negative, NaN or infinite is
    # REFUSED by the shared typed rule - it is never published and never a measured zero.  The receipt says why.
    if figures.get("lookup_ms") is not None:
        receipt.set_timing("cache_lookup", figures["lookup_ms"], "native_engine")
    if figures.get("restore_ms") is not None:
        receipt.set_timing("cache_restore", figures["restore_ms"], "native_engine")
    if "slot" in figures:
        slot = figures["slot"]
        # the engine writes a slot only when there is one; a stray negative is "no slot", not a slot
        receipt.slot_id = int(slot) if isinstance(slot, int) and not isinstance(slot, bool) and slot >= 0 else None
    if matched is None:
        receipt.mark_unavailable("prompt.matched_prefix_tokens", "the engine did not report a prefix match")
    if reused is None:
        receipt.mark_unavailable("prompt.reused_prefix_tokens", "the engine did not report a reused prefix")
    if evaluated is None:
        receipt.mark_unavailable("prompt.evaluated_tokens", "the engine did not report the tokens it evaluated")
    # the invocation's OWN prompt domain: what this dispatch gave the engine.  When the caller did not bind it
    # (the predecessor's path), the request's own prompt is the domain - they are the same for an ordinary
    # single-dispatch request.
    if receipt.submitted_tokens is None:
        receipt.submitted_tokens = record.submitted_tokens
    # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (A3a): the POSITIONAL DONE fields and the
    # native finish reason are part of THIS terminal evidence, and they are applied inside the commit - once, and
    # only when the receipt is correlated to this invocation.
    if positional:
        if receipt.correlation == CORRELATION_VERIFIED:
            if positional.get("prompt_ms") is not None:
                receipt.set_timing("prefill_wall", float(positional["prompt_ms"]), "native_engine")
            if positional.get("decode_ms") is not None:
                receipt.set_timing("decode_wall", float(positional["decode_ms"]), "native_engine")
            receipt.set_generation(generated=positional.get("generated"),
                                   draft_tokens=positional.get("drafts_offered"),
                                   accepted_tokens=positional.get("drafts_accepted"))
        if positional.get("finish") is not None:
            receipt.set_generation(finish_reason=str(positional["finish"]))
    # AMENDMENT-03 (G1): the invocation's own terminal state, and its own partial flag
    # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (A3b): the state is the NATIVE outcome of
    # THIS dispatch.  Uncorrelated evidence does not establish one: the receipt stays "running" and the record's
    # seal turns it into "unknown" (never "completed", never "failed").
    if receipt.correlation == CORRELATION_VERIFIED:
        receipt.state = native_state if native_state is not None else terminal_state
    if native_segment_only:
        receipt.native_partial = True
        receipt.mark_unavailable("cache",
                                 "the engine's batch slot reported only its admission segment: the native "
                                 "accounting is not the whole invocation")
    receipt.seal()
    # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (C3, D4): this invocation's terminal evidence is now
    # ACCEPTED.  A second terminal receipt for it is a duplicate: the same one is ignored, a conflicting one is
    # reported as explicit instrumentation evidence, and neither overwrites these measurements.
    receipt.terminal_accepted = True
    # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (A3a): the IMMUTABLE snapshot.  It is
    # committed once, here, and it is what a later duplicate is compared with.
    receipt.terminal_evidence = incoming
    # the parent's fields are the single invocation's; with more than one invocation they stay null (ambiguous)
    record.native_correlation = record.aggregate_correlation()
    record._sync_parent()
    # AMENDMENT-02 (G1): the receipt's measurements are in the record, but they are only AUTHORITATIVE when the
    # correlation was verified.  An unavailable correlation (an older engine) keeps the numbers as diagnostics.
    return {"correlation": receipt.correlation, "admitted": receipt.correlation == CORRELATION_VERIFIED}
