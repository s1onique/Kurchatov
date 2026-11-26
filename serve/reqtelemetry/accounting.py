"""serve/reqtelemetry/accounting.py - the token accounting rules (ACT-...-AMENDMENT-01, G3, G9).

The rules live here, apart from the record that carries them, so that "what does this number mean" has one place:
the disposition is derived from EVIDENCE only, and the conservation identities are CHECKED, never repaired.

A measurement that was NOT taken is not a zero: a prompt that matched 90 tokens but whose reuse was never measured
has an UNKNOWN disposition - not a match without usable state and not a cold miss.
"""
from __future__ import annotations

from serve.reqtelemetry.vocabulary import (DISPOSITION_COLD_MISS, DISPOSITION_FULL_HIT,
                                        DISPOSITION_MATCH_WITHOUT_STATE, DISPOSITION_PARTIAL_HIT,
                                        DISPOSITION_UNKNOWN)

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
    return problems


def measurement_valid(record) -> bool:
    """Whether the record's own numbers are measurements at all."""
    return not validate_measurements(record)


def correlation_state(record) -> str:
    """How well the engine's receipt is tied to this request: verified, unavailable or rejected."""
    return getattr(record, "native_correlation", CORRELATION_NOT_APPLICABLE)


def aggregate_eligible(record) -> bool:
    """Whether this record may contribute to the AUTHORITATIVE aggregates at all.

    Three separate things decide it, and they are kept apart on purpose:

      * the MEASUREMENTS must be valid (whole, non-negative counts);
      * the ACCOUNTING must not be violated (a broken identity is not published as a total);
      * the native measurements must be CORRELATED (a receipt that could not be tied to this request says nothing
        about it - an older engine leaves the correlation unavailable, never an asserted join).
    """
    if not measurement_valid(record):
        return False
    if record.accounting_state()["state"] == "violated":
        return False
    if correlation_state(record) not in (CORRELATION_VERIFIED, CORRELATION_NOT_APPLICABLE):
        return False
    if getattr(record, "native_partial", False):
        return False        # the native figures cover one segment of the invocation only (A9)
    return True


def field_eligible(record, name: str) -> bool:
    """Whether ONE measurement of this record may enter an authoritative aggregate.

    A measurement the SERVER owns stays eligible even when the engine's receipt could not be correlated: the
    request's own numbers are still the request's own numbers.
    """
    value = getattr(record, name, None)
    if value is None:
        return False
    if not valid_token_count(value):
        return False
    if name in NATIVE_TOKEN_FIELDS:
        return aggregate_eligible(record)
    # a server-owned measurement: it needs valid numbers, and the record's accounting must not be violated
    return measurement_valid(record) and record.accounting_state()["state"] != "violated"


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
