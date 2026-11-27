"""serve/reqtelemetry/invocation.py - the NATIVE INVOCATION's own measurement receipt (G1).

ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-03 (G1): one native dispatch owns ONE measurement receipt.

The predecessor generated a fresh invocation id for every dispatch, but the CANONICAL RECORD still carried a
single mutable set of native measurements.  So the measurements of an earlier invocation survived under the
identity of a later one: invocation B's `evaluated` and `lookup_ms` were published as invocation C's.

This module is the fix: every dispatch gets its OWN receipt, bound to the invocation id, the ordinal, the engine
instance, the model and the build identity BEFORE the dispatch, and it is validated against that identity when
the terminal evidence arrives.  The receipts are kept INDEPENDENTLY: a receipt that does not report a measurement
keeps that measurement null - it never inherits a value from another invocation.

THE PROMPT DOMAINS (G1, G2c): the parent record's `submitted_tokens` is the REQUEST's prompt domain - the prompt
the HTTP request carried.  An invocation's `submitted_tokens` is ITS OWN prompt domain - the prompt that dispatch
gave the engine.  They are equal for the ordinary single-dispatch request.  A recovery dispatch that sends a
DIFFERENT prompt has a different prompt domain, and its prompt positions are never added to the request's own
prompt coverage: the sum of distinct positions of two different prompts is not one prompt's distinct coverage.

THE BOUNDS (G1): the receipts of one request are bounded by COUNT and by BYTES, and every receipt that does not
fit is counted as a loss - a lost receipt is visible, never silently dropped:

    MAX_INVOCATION_RECORDS  how many receipts one request keeps
    MAX_INVOCATION_BYTES    how many bytes of receipts one request keeps

The oldest receipt is the one that goes when the bound is reached: the LAST dispatch is the one the request's
terminal outcome belongs to.  The loss is counted in `invocations_dropped` and it is published in the record.
"""
from __future__ import annotations

from serve.reqtelemetry.vocabulary import (COMPLETE, INSTRUMENTATION_ERROR, MAX_INVOCATION_BYTES,
                                           MAX_INVOCATION_RECORDS, PARTIAL, UNSUPPORTED)


def _num(value):
    """A number or None: 0 stays 0 (a measured zero), anything that is not a number becomes null."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


class InvocationReceipt:
    """One native dispatch's OWN measurements.

    It carries the same native vocabulary as the record (the prompt positions, the cache attribution, the
    durations, the generation counters) and it keeps its OWN correlation, its OWN validity and its OWN accounting
    state.  Two invocations of the same request never share a field.
    """

    def __init__(self, invocation_id, ordinal, engine_instance_id=None, model_id=None, build_revision=None,
                 parent=None):
        self.invocation_id = invocation_id
        # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (F2): the PARENT record.  The prompt
        # domain is a property of the DISPATCH, and the parent keeps the domain's MULTIPLICITY even when this
        # receipt is later discarded: the request's own prompt coverage must not become more certain when the
        # retention keeps fewer receipts.
        self._parent = parent
        self.ordinal = ordinal
        self.engine_instance_id = engine_instance_id
        self.model_id = model_id
        self.build_revision = build_revision
        # how well this receipt's evidence is tied to THIS invocation: verified, unavailable or rejected
        self.correlation = "not_applicable"
        # the invocation's own terminal state: "running" until its terminal evidence arrives
        self.state = "running"
        # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (C3, D4): the terminal evidence of this invocation has
        # been ACCEPTED.  A second terminal receipt is then a duplicate: the same one is ignored, a conflicting one
        # is reported - and the accepted measurements are never overwritten.
        self.terminal_accepted = False
        # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (A3a): the ACCEPTED terminal evidence, as
        # it arrived.  It is the snapshot a second terminal receipt is compared with - the complete normalized
        # evidence, not five prompt counters.  It is committed ONCE and never changed.
        self.terminal_evidence = None
        # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (A3c): a COMPATIBILITY receipt - one that
        # was constructed without a dispatch.  It is explicit, and it is outside the authoritative native admission:
        # only an ACTUAL dispatch contributes to the dispatched population.
        self.synthetic = False
        # the engine sent a measurement that is not a measurement (AMENDMENT-02, G1)
        self.measurements_invalid = False
        # the native figures cover one segment of the invocation only (AMENDMENT-02, A9)
        self.native_partial = False
        # the prompt this dispatch gave the engine (the invocation's OWN prompt domain)
        self.submitted_tokens = None
        # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (F2): the NAME of the prompt domain this
        # dispatch carried - "request", "continuation" or "other".  It is a word, not a hash and not content: the
        # prompt's LENGTH is not its identity.
        #
        # F2: the domain is a PROPERTY, so that naming it is recorded by the PARENT record even when this receipt
        # is later discarded: the request's own domain MULTIPLICITY must survive the retention of the receipts.
        self._prompt_domain = None
        self.rendered_tokens = None
        self.slot_id = None
        self.matched_prefix_tokens = None
        self.reused_prefix_tokens = None
        self.evaluated_tokens = None
        self.replayed_tokens = None
        self.non_prefix_reused_tokens = None
        self.evaluation_work_tokens = None
        self.first_divergent_token_index = None
        # the cache attribution
        self.cache_source = "unknown"
        self.cache_disposition = "unknown"
        self.cache_reason_code = None
        self.cache_restore_attempted = None
        self.cache_restore_succeeded = None
        self.cache_restore_ms = None
        self.cache_recurrent_state = None
        self.cache_attention_state = None
        self.cache_checkpoint_state = None
        self.cache_invalidations = None
        self.cache_evictions = None
        # the durations (milliseconds) and who measured them
        self.timing = {}
        self.timing_authority = {}
        # the generation
        self.requested_max_output_tokens = None
        self.effective_max_output_tokens = None
        self.generated_tokens = None
        self.emitted_tokens = None
        self.speculative_draft_tokens = None
        self.speculative_accepted_tokens = None
        self.finish_reason = None
        # why a measurement is missing
        self.unavailable = {}
        self.quality = COMPLETE
        self.accounting = {"state": "unevaluated", "valid": None, "problems": []}

    # ------------------------------------------------------------------ the prompt domain (F2)
    @property
    def prompt_domain(self):
        """The NAME of the prompt domain this dispatch carried ("request", "continuation", "other" or None)."""
        return self._prompt_domain

    @prompt_domain.setter
    def prompt_domain(self, value):
        """Naming the domain tells the PARENT that this dispatch carried it.

        ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (F2): the parent counts the dispatches
        per domain AT THE DISPATCH BOUNDARY.  The count lives in the parent, not in the receipts, so it survives
        the retention of the receipts: the request's own prompt coverage can never become exact because a
        receipt was DISCARDED.
        """
        self._prompt_domain = value
        parent = getattr(self, "_parent", None)
        if parent is not None:
            parent.note_prompt_domain(self.invocation_id, value)

    # ------------------------------------------------------------------ the measurements
    def mark_unavailable(self, field, reason, quality=UNSUPPORTED):
        """A measurement this invocation could not make: the field stays null and the receipt says why."""
        self.unavailable[field] = reason
        if quality == INSTRUMENTATION_ERROR:
            self.quality = INSTRUMENTATION_ERROR
        elif self.quality == COMPLETE:
            self.quality = PARTIAL

    def set_timing(self, name, ms, authority):
        """A duration in milliseconds, from a monotonic clock, with the authority that measured it.

        ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D1): the duration is admitted by the SHARED typed
        rule: a negative, a NaN and an infinity are refused (never published, never a measured zero), and the
        receipt says why.
        """
        from serve.reqtelemetry import accounting
        value = accounting.admit_duration(self, name, ms, field=f"timing_ms.{name}")
        if value is None:
            return
        self.timing[name] = round(float(value), 3)
        self.timing_authority[name] = authority

    def set_native_cache(self, *, matched_prefix=None, reused_prefix=None, evaluated=None, replayed=None,
                         non_prefix_reused=None, evaluation_work=None, first_divergent=None,
                         source=None, disposition=None, reason_code=None, restore_attempted=None,
                         restore_succeeded=None, restore_ms=None, recurrent_state=None, attention_state=None,
                         checkpoint_state=None, invalidations=None, evictions=None):
        """What the NATIVE ENGINE measured about the cache and the prompt, for THIS invocation.

        ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D1): every count and every duration goes through the
        SHARED typed admission.  An invalid value is refused (the field stays null and the receipt says why) - it
        is never clamped, rounded or coerced into a valid one.
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
            self.cache_restore_ms = accounting.admit_duration(
                self, "restore_ms", restore_ms, field="cache.restore_ms")
        if recurrent_state is not None:
            self.cache_recurrent_state = recurrent_state
        if attention_state is not None:
            self.cache_attention_state = attention_state
        if checkpoint_state is not None:
            self.cache_checkpoint_state = checkpoint_state
        if invalidations is not None:
            self.cache_invalidations = accounting.admit_count(
                self, "invalidations", invalidations, field="cache.invalidations")
        if evictions is not None:
            self.cache_evictions = accounting.admit_count(
                self, "evictions", evictions, field="cache.evictions")

    def set_generation(self, *, requested_max=None, effective_max=None, generated=None, emitted=None,
                       draft_tokens=None, accepted_tokens=None, finish_reason=None):
        """What this invocation generated.

        ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D1): the generation counters are COUNTS: a whole,
        non-negative integer.  A negative, a fraction and a bool are refused - never rounded into a valid count.
        """
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

    # ------------------------------------------------------------------ the accounting rules
    def seal(self):
        """Close the receipt: the structural zero of the reuse outside the prefix, and its own accounting state."""
        from serve.reqtelemetry import accounting
        if self.non_prefix_reused_tokens is None and self.reused_prefix_tokens is not None:
            # Strata's execution path reuses a CONTIGUOUS prefix only, so the reuse outside the prefix is a
            # STRUCTURAL ZERO, not an unmeasured value (include/strata/program/reqtelemetry.hpp).
            self.non_prefix_reused_tokens = 0
        # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D6): the invocation's OWN disposition, derived from
        # the SAME rules as the record's - from the evidence and nothing else.  An invocation whose reuse was not
        # measured has an unknown disposition, not a match without usable state and not a cold miss.
        self.cache_disposition = accounting.derive_disposition(self)
        self.accounting = self.accounting_state()
        if self.accounting["state"] == "violated" and self.quality == COMPLETE:
            self.quality = PARTIAL
        return self

    def conservation(self) -> list:
        """The accounting identities that must hold - CHECKED, never enforced."""
        from serve.reqtelemetry import accounting
        return accounting.conservation(self)

    def identity_evaluable(self) -> bool:
        """Whether the sum identity can be evaluated at all."""
        from serve.reqtelemetry import accounting
        return accounting.identity_evaluable(self)

    # ------------------------------------------------------------------ the receipt itself
    def to_dict(self) -> dict:
        """The receipt as it goes into the record: its own measurements, its own admission decisions."""
        from serve.reqtelemetry import accounting
        admission = {metric: accounting.invocation_admission(self, metric) for metric in accounting.METRICS}
        return {
            "identity": {
                "engine_invocation_id": self.invocation_id,
                "ordinal": self.ordinal,
                "engine_instance_id": self.engine_instance_id,
                "model_id": self.model_id,
                "build_revision": self.build_revision,
                "slot_id": self.slot_id,
            },
            "state": self.state,
            "prompt": {
                "rendered_tokens": self.rendered_tokens,
                "submitted_tokens": self.submitted_tokens,
                # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (C4): the prompt DOMAIN of this dispatch.
                # It is a word - never a hash and never content.
                "domain": self.prompt_domain,
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
                # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D4): the NATIVE invocation's finish reason.
                # It is not the physical HTTP request's finish reason: an invocation that exhausted its output
                # budget may be followed by a successful continuation.
                "finish_reason": self.finish_reason,
            },
            "measurement_quality": {
                "state": self.quality,
                "unavailable_fields": dict(sorted(self.unavailable.items())),
                "timing_authority": dict(sorted(self.timing_authority.items())),
                "native_correlation": self.correlation,
                "native_partial": self.native_partial,
                # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (A3a): whether this invocation's
                # terminal evidence was ACCEPTED.  A second terminal receipt is a duplicate against it.
                "terminal_accepted": bool(self.terminal_accepted),
                # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (A3c): a compatibility receipt was
                # constructed without a dispatch: it is not native evidence and it is not admitted to the native
                # aggregates.
                "compatibility_receipt": bool(self.synthetic),
                "measurement_valid": self.measurement_valid(),
                "accounting": {"state": self.accounting.get("state", "unevaluated"),
                               "valid": self.accounting.get("valid"),
                               "problems": list(self.accounting.get("problems") or [])},
                # the per-metric admission decisions of THIS invocation (G2): one global predicate for all
                # measurements is what made an uncorrelated duration and an unevaluated accounting admissible
                "admission": admission,
            },
        }


    def accounting_state(self) -> dict:
        """This invocation's own accounting state: satisfied, violated or unevaluated."""
        from serve.reqtelemetry import accounting
        return accounting.accounting_state(self)

    def same_measurements(self, matched, reused, evaluated, replayed, work) -> bool:
        """Whether these prompt measurements are the ones this receipt already accepted.

        ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (C3, D4): it is the DUPLICATE test.  A duplicate that
        carries the same numbers is the same evidence seen twice; a duplicate that carries different numbers is a
        conflict, and it is reported instead of overwriting the accepted measurements.
        """
        return (self.matched_prefix_tokens == matched
                and self.reused_prefix_tokens == reused
                and self.evaluated_tokens == evaluated
                and self.replayed_tokens == replayed
                and self.evaluation_work_tokens == work)

    def measurement_valid(self) -> bool:
        """Whether this receipt's own numbers are measurements at all."""
        from serve.reqtelemetry import accounting
        return accounting.measurement_valid(self)
