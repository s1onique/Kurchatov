"""serve/reqtelemetry/accounting.py - the token accounting rules (ACT-...-AMENDMENT-01, G3, G9).

The rules live here, apart from the record that carries them, so that "what does this number mean" has one place:
the disposition is derived from EVIDENCE only, and the conservation identities are CHECKED, never repaired.

A measurement that was NOT taken is not a zero: a prompt that matched 90 tokens but whose reuse was never measured
has an UNKNOWN disposition - not a match without usable state and not a cold miss.
"""
from __future__ import annotations

import math

from serve.reqtelemetry.vocabulary import (DISPOSITION_COLD_MISS, DISPOSITION_FULL_HIT,
                                        DISPOSITION_MATCH_WITHOUT_STATE, DISPOSITION_PARTIAL_HIT,
                                        DISPOSITION_UNKNOWN, INSTRUMENTATION_ERROR)

def derive_disposition(record):
    """The cache disposition, from the evidence and nothing else.

    The rules, in order:
      * the engine matched the prompt but had no usable state for it -> match_without_usable_state;
      * nothing was reused at all -> cold_miss;
      * everything was reused -> full_hit;
      * some of it was reused -> partial_hit.
    A duration or a rate never decides this: a fast request with no reuse is still a cold miss.

    A measurement that was NOT taken is not a zero (AMENDMENT-01, G3): a prompt that matched 90 tokens but whose
    reuse was never measured has an UNKNOWN disposition - it is not a match without usable state, and it is not
    a cold miss either.  Only a measured reuse decides.
    """
    if record.cache_disposition != DISPOSITION_UNKNOWN:
        return record.cache_disposition                    # the engine named it (an explicit reason code)
    matched, reused = record.matched_prefix_tokens, record.reused_prefix_tokens
    if matched is None and reused is None:
        return DISPOSITION_UNKNOWN
    if reused is None:
        return DISPOSITION_UNKNOWN                        # the reuse was not measured: nothing can be derived
    if reused == 0:
        if matched is not None and matched > 0:
            return DISPOSITION_MATCH_WITHOUT_STATE         # the tokens matched, the state did not
        return DISPOSITION_COLD_MISS
    if record.submitted_tokens is not None and record.submitted_tokens > 0 \
            and reused >= record.submitted_tokens:
        return DISPOSITION_FULL_HIT
    return DISPOSITION_PARTIAL_HIT

# ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-02 (G1): the token counts and who owns them.
#
# The server owns what it measured itself (the submitted prompt, the budgets, its own durations).  The engine owns
# the cache attribution and the execution work.  A measurement is admitted to an authoritative aggregate only when it
# is VALID (a whole, non-negative count), its owner is CORRELATED (the engine's receipt belongs to this request)
# and the record's ACCOUNTING is not violated.
TOKEN_FIELDS = ("rendered_tokens", "submitted_tokens", "matched_prefix_tokens", "reused_prefix_tokens",
                "evaluated_tokens", "replayed_tokens", "non_prefix_reused_tokens", "evaluation_work_tokens")

# ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D1): the GENERATION counters and the CUMULATIVE native
# counters are counts too - a whole, non-negative integer.  They are validated here, so a record that carries an
# invalid one says so instead of publishing it.
GENERATION_FIELDS = ("requested_max_output_tokens", "effective_max_output_tokens", "generated_tokens",
                     "emitted_tokens", "speculative_draft_tokens", "speculative_accepted_tokens")
CUMULATIVE_FIELDS = ("cache_invalidations", "cache_evictions", "first_divergent_token_index")

# the fields the NATIVE ENGINE measures.  They are admitted only when the receipt is correlated to this request.
NATIVE_TOKEN_FIELDS = ("matched_prefix_tokens", "reused_prefix_tokens", "evaluated_tokens", "replayed_tokens",
                       "evaluation_work_tokens")

# the correlation states.  "not_applicable" is a request that never reached the engine.
CORRELATION_VERIFIED = "verified"
CORRELATION_UNAVAILABLE = "unavailable"
CORRELATION_REJECTED = "rejected"
CORRELATION_NOT_APPLICABLE = "not_applicable"


def valid_token_count(value) -> bool:
    """A token count is a WHOLE, non-negative number.  A bool, a fraction, a negative and a string are not counts."""
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return value >= 0


# ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D1): the TYPED measurement admission, shared by the record
# and the invocation receipt.
#
# The predecessor's `_num` accepted anything that was a number, so a negative duration, a NaN and a fractional
# token count all reached the published record - and the aggregate exporter then excluded them, so the record and
# the totals disagreed.  The rules are here, in ONE place:
#
#   * a COUNT (token counts, generation counts, cumulative event counters) is a whole, non-negative integer; a
#     bool is not a count;
#   * a DURATION (milliseconds) is a FINITE, non-negative number;
#   * an invalid value is REFUSED: it is never clamped, rounded or coerced into a valid one.  The field stays
#     null, the receipt says why, and the measurement is marked invalid so it cannot enter a total.
#
# The native sentinels keep their own documented meanings (the engine writes -1 for "not measured" and leaves
# the key out entirely), so they are handled where the figures are parsed, not here.
def valid_count(value) -> bool:
    """A count is a WHOLE, non-negative integer.  A bool, a fraction, a negative and a string are not counts."""
    return valid_token_count(value)


def valid_duration(value) -> bool:
    """A duration in milliseconds is a FINITE, non-negative number.  NaN and infinity are not durations."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if not math.isfinite(float(value)):
        return False
    return float(value) >= 0.0


def admit_count(target, name, value, field=None):
    """ONE count, at the admission boundary.  The value or None.

    An invalid count is refused, never repaired: the field stays null, the target says why, and the target is
    marked as carrying an invalid measurement (so it does not enter the authoritative aggregates).
    """
    if value is None:
        return None
    if valid_count(value):
        return value
    target.measurements_invalid = True
    target.mark_unavailable(field or name,
                            f"the {name} that was reported is not a whole, non-negative count",
                            INSTRUMENTATION_ERROR)
    return None


def admit_duration(target, name, value, field=None):
    """ONE duration, at the admission boundary.  The value or None.

    A duration that is negative, NaN or infinite is refused, never repaired: it is never published, and it never
    reaches the histogram as a measured zero.
    """
    if value is None:
        return None
    if valid_duration(value):
        return float(value)
    target.measurements_invalid = True
    target.mark_unavailable(field or name,
                            f"the {name} that was reported is not a finite, non-negative duration",
                            INSTRUMENTATION_ERROR)
    return None


def validate_measurements(record) -> list:
    """The problems with the record's own numbers, whatever the accounting says.

    A count that is not a whole non-negative number is not a measurement at all: it is refused at the admission
    boundary, never repaired and never counted.  The ranges that make the accounting IDENTIFY itself (reused <=
    matched <= submitted) are checked by `conservation` - they are a broken identity, not a broken number.
    """
    problems = []
    if getattr(record, "measurements_invalid", False):
        # a measurement the engine sent was refused at the admission boundary: the record's numbers are not
        # measurements, so it does not enter the authoritative aggregates
        problems.append("the engine reported a measurement that is not a whole, non-negative token count")
    for name in TOKEN_FIELDS:
        value = getattr(record, name, None)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            problems.append(f"{name} is not a whole token count")
        elif value < 0:
            problems.append(f"{name} is negative")
    # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D1): the generation counters and the cumulative native
    # counters are counts as well: a fraction, a bool and a negative are not counts.
    for name in GENERATION_FIELDS + CUMULATIVE_FIELDS:
        value = getattr(record, name, None)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            problems.append(f"{name} is not a whole count")
        elif value < 0:
            problems.append(f"{name} is negative")
    # the durations: a NaN or an infinity is not a measurement either
    for name, value in (getattr(record, "timing", None) or {}).items():
        if not valid_duration(value):
            problems.append(f"timing_ms.{name} is not a finite, non-negative duration")
    return problems


def measurement_valid(record) -> bool:
    """Whether the record's own numbers are measurements at all."""
    return not validate_measurements(record)


# ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D1): the validity is CLASS-AWARE.  An invalid DURATION does
# not invalidate the valid token counts, and an invalid count does not invalidate the valid durations: the
# measurement classes are independent, and each one is admitted (or refused) on its own terms.  The overall
# `measurement_valid` still says that SOMETHING in the record is not a measurement.
def counts_valid(record) -> bool:
    """Whether the record's own COUNTS are measurements: whole, non-negative integers."""
    for name in TOKEN_FIELDS + GENERATION_FIELDS + CUMULATIVE_FIELDS:
        value = getattr(record, name, None)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return False
    return True


def durations_valid(record) -> bool:
    """Whether the record's own DURATIONS are measurements: finite and non-negative."""
    for name, value in (getattr(record, "timing", None) or {}).items():
        if not valid_duration(value):
            return False
    restore_ms = getattr(record, "cache_restore_ms", None)
    if restore_ms is not None and not valid_duration(restore_ms):
        return False
    return True


def correlation_state(record) -> str:
    """How well the engine's receipt is tied to this request: verified, unavailable or rejected."""
    return correlation_of(record)


def correlation_of(obj) -> str:
    """The correlation state of a record or of an invocation receipt (G1).

    The record aggregates the states of its receipts; a receipt carries its OWN.  One place reads both, so the
    two cannot drift apart.
    """
    state = getattr(obj, "correlation", None)
    if state is not None:
        return state
    return getattr(obj, "native_correlation", CORRELATION_NOT_APPLICABLE)


def aggregate_eligible(record) -> bool:
    """Whether this record may contribute to the AUTHORITATIVE aggregates at all.

    Three separate things decide it, and they are kept apart on purpose:

      * the MEASUREMENTS must be valid (whole, non-negative counts);
      * the ACCOUNTING must not be violated (a broken identity is not published as a total);
      * the native measurements must be CORRELATED (a receipt that could not be tied to this request says nothing
        about it - an older engine leaves the correlation unavailable, never an asserted join).
    ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D6): the field is DEPRECATED as a gate - the PER-CLASS
    admission (`measurement_quality.admission`) is the authority - but it is kept for the operator and it is now
    CONSISTENT with it: it is true when the record is admitted for the native classes it carries.  A record whose
    native classes are all refused (a foreign receipt, or a request that dispatched more than one invocation and
    therefore has no unambiguous native scalars) is not eligible, even when its HTTP-owned numbers are fine.
    """
    if not measurement_valid(record):
        return False
    if record.accounting_state()["state"] == "violated":
        return False
    if getattr(record, "native_partial", False):
        return False        # the native figures cover one segment of the invocation only (A9)
    classes = (METRIC_NATIVE_PROMPT_POSITION, METRIC_NATIVE_EXECUTION_WORK, METRIC_NATIVE_DURATION,
               METRIC_CACHE_RESTORE, METRIC_NATIVE_GENERATION)
    admitted = [metric for metric in classes if record.metric_admission(metric)]
    if admitted:
        return True
    # a request that holds no invocation receipt at all carries no native measurement: only its HTTP-owned numbers
    return not getattr(record, "invocations", None)


def field_eligible(record, name: str) -> bool:
    """Whether ONE measurement of this record may enter an authoritative aggregate.

    A measurement the SERVER owns stays eligible even when the engine's receipt could not be correlated: the
    request's own numbers are still the request's own numbers.

    ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D3): the legacy helper is now a THIN wrapper around the
    metric-specific admission, so it cannot contradict it: a native field is admitted by the NATIVE PROMPT
    POSITION class, a server-owned field by the HTTP class.
    """
    metric = METRIC_NATIVE_PROMPT_POSITION if name in NATIVE_TOKEN_FIELDS else METRIC_HTTP
    return field_admission(record, name, metric)


def conservation(record) -> list:
    """The accounting identities that must hold when the domains are equivalent, non-overlapping and complete.

    They are CHECKED, never enforced: a measurement is never adjusted to make the identity come out right.  A
    broken identity is reported so the operator sees that the accounting was incomplete.

    The SUM identity (submitted = reused + non_prefix_reused + evaluated) is only evaluated when every term of it
    was measured AND the request's accounting is complete.  A cancelled request evaluated part of its prompt, so
    the identity does not apply to it - that is "unevaluated", not "violated" (AMENDMENT-01, G3).
    """
    problems = []
    matched, reused = record.matched_prefix_tokens, record.reused_prefix_tokens
    submitted, evaluated = record.submitted_tokens, record.evaluated_tokens
    replayed, work = record.replayed_tokens, record.evaluation_work_tokens
    non_prefix = record.non_prefix_reused_tokens
    # AMENDMENT-02 (G1): a number that is not a whole count is not compared at all - it is refused at the
    # admission boundary (validate_measurements), so the identities below only ever compare real measurements.
    def count(value):
        return value if valid_token_count(value) else None

    matched, reused = count(matched), count(reused)
    submitted, evaluated = count(submitted), count(evaluated)
    replayed, work, non_prefix = count(replayed), count(work), count(non_prefix)
    if reused is not None and matched is not None and reused > matched:
        problems.append("reused_prefix_tokens is greater than matched_prefix_tokens")
    if matched is not None and submitted is not None and matched > submitted:
        problems.append("matched_prefix_tokens is greater than submitted_tokens")
    if reused is not None and submitted is not None and reused > submitted:
        problems.append("reused_prefix_tokens is greater than submitted_tokens")
    if replayed is not None and evaluated is not None and replayed > evaluated:
        problems.append("replayed_tokens is greater than evaluated_tokens")
    if work is not None and evaluated is not None and work < evaluated:
        problems.append("evaluation_work_tokens is less than evaluated_tokens")
    if record.identity_evaluable() and reused + non_prefix + evaluated != submitted:
        problems.append("submitted_tokens is not reused + non_prefix_reused + evaluated")
    return problems

def identity_evaluable(record) -> bool:
    """Whether the sum identity can be evaluated at all: every term measured and the accounting complete."""
    if record.state not in ("completed",):
        return False                                # a cancelled or failed request's accounting is not complete
    # AMENDMENT-02 (G1): a term that is not a whole count cannot take part in an identity: the identity is then
    # UNEVALUATED, never "satisfied" and never "violated" on the strength of a number that is not a measurement.
    terms = (record.submitted_tokens, record.reused_prefix_tokens, record.evaluated_tokens,
             record.non_prefix_reused_tokens)
    return all(valid_token_count(term) for term in terms)

def accounting_state(record) -> dict:
    """The accounting's own state: satisfied, violated or UNEVALUATED.

    An unevaluated identity is never reported as satisfied (AMENDMENT-01, G3): the measurements it needs were
    not taken, and the record says that instead of pretending the identity holds.
    """
    problems = record.conservation()
    if problems:
        return {"state": "violated", "valid": False, "problems": problems}
    if record.identity_evaluable():
        return {"state": "satisfied", "valid": True, "problems": []}
    missing = [name for name, value in (("submitted_tokens", record.submitted_tokens),
                                         ("reused_prefix_tokens", record.reused_prefix_tokens),
                                         ("evaluated_tokens", record.evaluated_tokens),
                                         ("non_prefix_reused_tokens", record.non_prefix_reused_tokens))
               if value is None]
    return {"state": "unevaluated", "valid": None, "problems": [],
            "missing": missing + ([] if record.state == "completed" else ["the request did not complete"])}


# ---------------------------------------------------------------------------------------------
# ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-03 (G2): the admission is METRIC-SPECIFIC.
#
# The predecessor used ONE global predicate (the record is valid, the accounting is not violated, the receipt is
# correlated) for every measurement.  That made three wrong admissions possible:
#
#   * an UNEVALUATED accounting (the complete prompt accounting was not available) was admitted to the COMPLETE
#     cache-reuse ratio - a ratio whose denominator is "the prompts whose accounting closes" must not count a
#     prompt whose accounting did not close;
#   * a NATIVE DURATION was observed in a histogram without the correlation and the segment-completeness checks -
#     an uncorrelated duration is somebody else's measurement;
#   * a valid PARTIAL work counter was excluded just because the complete-prompt accounting was unavailable.
#
# Each measurement class has its OWN rule now, and the rules are here - one place, so they cannot drift.
METRIC_HTTP = "http"
METRIC_NATIVE_PROMPT_POSITION = "native_prompt_position"
METRIC_NATIVE_EXECUTION_WORK = "native_execution_work"
METRIC_NATIVE_DURATION = "native_duration"
METRIC_CACHE_RESTORE = "cache_restore"
METRIC_COMPLETE_CACHE_RATIO = "complete_cache_ratio"
METRIC_PARTIAL_DIAGNOSTIC = "partial_diagnostic"
# the engine's own generation counters: they need a correlated receipt and valid numbers, like the restoration's
# outcome - they are not part of the prompt's accounting.
METRIC_NATIVE_GENERATION = "native_generation"

METRICS = (METRIC_HTTP, METRIC_NATIVE_PROMPT_POSITION, METRIC_NATIVE_EXECUTION_WORK, METRIC_NATIVE_DURATION,
           METRIC_CACHE_RESTORE, METRIC_COMPLETE_CACHE_RATIO, METRIC_PARTIAL_DIAGNOSTIC, METRIC_NATIVE_GENERATION)


def invocation_admission(inv, metric: str) -> bool:
    """Whether a MEASUREMENT CLASS of this invocation may enter an authoritative aggregate (G2).

    `inv` is an invocation receipt (serve/reqtelemetry/invocation.py) or the record itself.  The rules:

      * HTTP            - the server's own numbers.  They stand on their own: a NATIVE measurement that was
                          refused at the admission boundary does not make the server's own number a guess.
      * PROMPT_POSITION - the engine's prompt positions (matched, reused, evaluated).  They need a CORRELATED
                          receipt, valid numbers and an accounting that is not violated.
      * EXECUTION_WORK  - the work counters (replayed, evaluation work).  They keep their OWN authority: an
                          UNEVALUATED accounting (the complete prompt accounting was not available) does not
                          exclude a measured work counter - a VIOLATED identity does.
      * DURATION        - a native duration.  It is independently trustworthy when the receipt is CORRELATED to
                          this invocation and the invocation is WHOLE (a batch slot's admission segment is not
                          the whole invocation).  It does NOT depend on the token accounting: a broken token
                          count does not turn a measured duration into a guess.
      * CACHE_RESTORE   - the restoration's outcome: a correlated receipt and valid numbers.
      * COMPLETE_RATIO  - the complete cache-reuse ratio: a correlated receipt, valid numbers and an account-
                          ing that SATISFIED - not merely one that is not violated.
      * PARTIAL         - the diagnostic evidence of a partial segment.  It is published as a diagnostic and
                          never as the whole invocation.
    """
    if metric == METRIC_PARTIAL_DIAGNOSTIC:
        return True
    # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (A3c): a COMPATIBILITY receipt - one that was
    # constructed without a native dispatch - is not native evidence.  It is admitted to nothing: only an ACTUAL
    # dispatch contributes to the dispatched population and to the native aggregates.
    if getattr(inv, "synthetic", False):
        return False
    verified = correlation_of(inv) == CORRELATION_VERIFIED
    # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D1): the validity is CLASS-AWARE: an invalid duration
    # does not exclude the valid token counts, and an invalid count does not exclude the valid durations.  The
    # measurement classes are independent.
    counts = counts_valid(inv)
    durations = durations_valid(inv)
    partial = bool(getattr(inv, "native_partial", False))
    state = inv.accounting_state()["state"]
    if metric == METRIC_HTTP:
        return True
    if metric == METRIC_NATIVE_PROMPT_POSITION:
        return verified and counts and not partial and state != "violated"
    if metric == METRIC_NATIVE_EXECUTION_WORK:
        return verified and counts and not partial and state != "violated"
    if metric == METRIC_NATIVE_DURATION:
        return verified and durations and not partial
    if metric == METRIC_CACHE_RESTORE:
        return verified and counts and durations and not partial
    if metric == METRIC_NATIVE_GENERATION:
        return verified and counts and not partial
    if metric == METRIC_COMPLETE_CACHE_RATIO:
        return verified and counts and not partial and state == "satisfied"
    return False


def field_admission(record, name: str, metric: str, inv=None) -> bool:
    """Whether ONE measurement may enter an authoritative aggregate, for ONE metric class (G2).

    The measurement itself must be a measurement (a whole, non-negative count); then the class rule decides.
    """
    target = inv if inv is not None else record
    value = getattr(target, name, None)
    if value is None:
        return False
    if name in TOKEN_FIELDS and not valid_token_count(value):
        return False
    if metric == METRIC_HTTP:
        # the server's own number: it is a measurement of the request, whatever the engine's receipt says
        return True
    return invocation_admission(target, metric)
