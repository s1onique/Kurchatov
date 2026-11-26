"""serve/reqtelemetry/correlation.py - the native receipt and the request it belongs to (G2, G9).

The engine echoes the request's own id on its DONE line.  A receipt that carries ANOTHER request's id is foreign:
none of its numbers are attached to the receiving request, its aggregates stay clean, and the request says it had
an instrumentation error.  A receipt with no id at all (an older engine) leaves the correlation explicitly
unavailable - never an asserted join.
"""
from __future__ import annotations

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


def apply_engine(record: RequestRecord, figures: dict | None):
    """The engine's own measurements for this request, into the record.

    `figures` is the `telemetry` part of the engine's DONE line: what the engine measured about the cache and about
    the work it did.  A field the engine did not send stays null - it is NOT a zero, and it is NOT guessed from the
    server's own timings.
    """
    if not figures:
        record.mark_unavailable("cache", "the engine reported no cache measurements for this request")
        record.mark_unavailable("prompt.matched_prefix_tokens", "the engine reported no cache measurements")
        return record
    # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-01 (G2): the receipt is BOUND to the request that asked for
    # it.  The engine echoes the request's own id on its DONE line; a receipt that carries another request's id is
    # FOREIGN and none of its numbers are attached to this record (the aggregate counters are not touched either -
    # this record never sees them).  The request itself goes on: a telemetry problem never decides an inference.
    rid = figures.get("rid")
    expected = record.request_id
    if rid is not None and expected is not None and rid != expected:
        record.mark_unavailable("engine_telemetry",
                                "the engine's receipt carried another request's id: its measurements were not "
                                "attached to this request", INSTRUMENTATION_ERROR)
        record.engine_invocation_id = None
        return record
    if rid:
        record.engine_invocation_id = rid
    elif expected is not None:
        # An older engine does not echo the id: the correlation is UNAVAILABLE, never an asserted join.
        record.mark_unavailable("identity.engine_invocation_id",
                                "the engine did not echo the request's id (an older engine): the native invocation "
                                "cannot be tied to this request by id")

    matched = figures.get("matched")
    reused = figures.get("reused")
    evaluated = figures.get("evaluated")
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
        replayed=figures.get("replayed"), evaluation_work=figures.get("work"),
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
        record.slot_id = int(slot) if isinstance(slot, int) and slot >= 0 else None
    if matched is None:
        record.mark_unavailable("prompt.matched_prefix_tokens", "the engine did not report a prefix match")
    if reused is None:
        record.mark_unavailable("prompt.reused_prefix_tokens", "the engine did not report a reused prefix")
    if evaluated is None:
        record.mark_unavailable("prompt.evaluated_tokens", "the engine did not report the tokens it evaluated")
    return record
