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
    if reused is not None and matched is not None and reused > matched:
        problems.append("reused_prefix_tokens is greater than matched_prefix_tokens")
    if matched is not None and submitted is not None and matched > submitted:
        problems.append("matched_prefix_tokens is greater than submitted_tokens")
    if reused is not None and submitted is not None and reused > submitted:
        problems.append("reused_prefix_tokens is greater than submitted_tokens")
    if record.replayed_tokens is not None and evaluated is not None and record.replayed_tokens > evaluated:
        problems.append("replayed_tokens is greater than evaluated_tokens")
    if record.evaluation_work_tokens is not None and evaluated is not None \
            and record.evaluation_work_tokens < evaluated:
        problems.append("evaluation_work_tokens is less than evaluated_tokens")
    if record.identity_evaluable() and \
            reused + record.non_prefix_reused_tokens + evaluated != submitted:
        problems.append("submitted_tokens is not reused + non_prefix_reused + evaluated")
    return problems

def identity_evaluable(record) -> bool:
    """Whether the sum identity can be evaluated at all: every term measured and the accounting complete."""
    if record.state not in ("completed",):
        return False                                # a cancelled or failed request's accounting is not complete
    return None not in (record.submitted_tokens, record.reused_prefix_tokens, record.evaluated_tokens,
                        record.non_prefix_reused_tokens)

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

