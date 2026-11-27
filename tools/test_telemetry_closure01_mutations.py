#!/usr/bin/env python3
"""tools/test_telemetry_closure01_mutations.py - the non-vacuity witnesses of
ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (C6, D8).

Each witness here reverses ONE correction, IN MEMORY ONLY, and shows that the witness that guards it FAILS
without the correction.  Nothing is written to the repository's files: the reversal is a patch of the running
process, and it is undone when the test ends.  No mutation code is left in the production tree.

    python tools/test_telemetry_closure01_mutations.py
"""
from __future__ import annotations

import contextlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serve.reqtelemetry import accounting, correlation, record, store  # noqa: E402
from serve.reqtelemetry import invocation as invocation_module  # noqa: E402
from serve import test_telemetry_closure01 as witnesses  # noqa: E402


@contextlib.contextmanager
def patched(obj, name, replacement):
    """Replace one attribute for the duration of the block, and put it back afterwards."""
    old = getattr(obj, name)
    setattr(obj, name, replacement)
    try:
        yield
    finally:
        setattr(obj, name, old)


def _run_witness(case, name):
    """Run ONE witness of the closure-01 suite and let its assertion failure through."""
    case.setUp()
    try:
        getattr(case, name)()
    finally:
        case.tearDown()


class Mutations(unittest.TestCase):
    """Every witness fails when its correction is reversed."""

    def test_an_invalid_duration_is_not_published(self):
        """INVALID_DURATION_PUBLISHED: the receipt publishes a duration that is not a duration."""

        def publishing(self, name, ms, authority):
            value = accounting.admit_duration(self, name, ms, field=f"timing_ms.{name}")
            if value is None:
                # the reversal: the invalid value is published anyway
                self.timing[name] = float(ms)
                self.timing_authority[name] = authority
                return
            self.timing[name] = round(float(value), 3)
            self.timing_authority[name] = authority

        with patched(invocation_module.InvocationReceipt, "set_timing", publishing):
            case = witnesses.TypedAdmission("test_a_negative_native_duration_is_not_published")
            with self.assertRaises(AssertionError, msg="the published duration passes the witness"):
                _run_witness(case, "test_a_negative_native_duration_is_not_published")

    def test_an_invalid_generation_count_is_not_published(self):
        """INVALID_GENERATION_COUNT_PUBLISHED: the receipt publishes a count that is not a count."""

        def publishing(self, *, requested_max=None, effective_max=None, generated=None, emitted=None,
                       draft_tokens=None, accepted_tokens=None, finish_reason=None):
            if generated is not None:
                self.generated_tokens = generated            # the reversal: no typed admission
            if finish_reason is not None:
                self.finish_reason = finish_reason

        with patched(invocation_module.InvocationReceipt, "set_generation", publishing):
            case = witnesses.TypedAdmission("test_a_negative_generation_count_is_not_published")
            with self.assertRaises(AssertionError, msg="the published count passes the witness"):
                _run_witness(case, "test_a_negative_generation_count_is_not_published")

    def test_an_explicitly_unknown_identity_is_not_inherited(self):
        """EXPLICIT_UNKNOWN_IDENTITY_INHERITED: the preparation identity is substituted for the unknown one."""
        real = record.RequestRecord.begin_invocation

        def inheriting(self, invocation_id, ordinal=None, engine_instance_id=record.OMITTED, model_id=record.OMITTED,
                       build_revision=record.OMITTED):
            # the reversal: an explicitly unknown identity inherits the record's own
            return real(self, invocation_id, ordinal=ordinal,
                        engine_instance_id=self.engine_instance_id if engine_instance_id is None else engine_instance_id,
                        model_id=self.model_id if model_id is None else model_id,
                        build_revision=self.build_revision if build_revision is None else build_revision)

        with patched(record.RequestRecord, "begin_invocation", inheriting):
            case = witnesses.DispatchIdentity("test_an_explicitly_unknown_engine_identity_is_not_inherited")
            with self.assertRaises(AssertionError, msg="the inherited identity passes the witness"):
                _run_witness(case, "test_an_explicitly_unknown_engine_identity_is_not_inherited")

    def test_the_terminal_evidence_creates_no_dispatch(self):
        """TERMINAL_RECEIPT_CREATES_DISPATCH: the terminal path creates a dispatch."""
        real = correlation.apply_engine

        def creating(record_, figures, expected_invocation_id=None, receipt=None, terminal_state="completed",
                     native_segment_only=False):
            if receipt is None:
                receipt = record_.invocation_for(expected_invocation_id)
            if receipt is None:
                # the reversal: a new dispatch is created
                receipt = record_.begin_invocation(expected_invocation_id)
            return real(record_, figures, expected_invocation_id=expected_invocation_id, receipt=receipt,
                        terminal_state=terminal_state, native_segment_only=native_segment_only)

        with patched(witnesses, "apply_engine", creating):
            case = witnesses.DispatchIdentity(
                "test_the_terminal_evidence_of_an_evicted_invocation_resurrects_nothing")
            with self.assertRaises(AssertionError, msg="the resurrected receipt passes the witness"):
                _run_witness(case, "test_the_terminal_evidence_of_an_evicted_invocation_resurrects_nothing")

    def test_a_conflicting_duplicate_is_reported(self):
        """CONFLICTING_DUPLICATE_TERMINAL_RECEIPT_ACCEPTED: the conflict overwrites the measurements."""

        def always_same(figures, positional=None):
            # the reversal: every duplicate looks the same, so a conflicting one is never noticed
            return {"the same": True}

        with patched(correlation, "normalize_terminal_evidence", always_same):
            case = witnesses.TerminalDuplicates(
                "test_a_conflicting_duplicate_is_reported_and_keeps_the_accepted_measurements")
            with self.assertRaises(AssertionError, msg="the accepted conflict passes the witness"):
                _run_witness(case,
                             "test_a_conflicting_duplicate_is_reported_and_keeps_the_accepted_measurements")

    def test_the_http_counter_is_not_suppressed(self):
        """HTTP_COUNTER_SUPPRESSED_BY_NATIVE_ACCOUNTING: the native accounting suppresses the HTTP counter."""
        real = store.TelemetryStore._count_locked

        def suppressing(self, data):
            # the reversal: the HTTP counters are counted only when the native accounting is not violated
            quality = data["measurement_quality"]
            if (quality.get("accounting") or {}).get("state") == "violated":
                return
            return real(self, data)

        with patched(store.TelemetryStore, "_count_locked", suppressing):
            case = witnesses.HttpAuthority("test_a_broken_native_accounting_does_not_suppress_the_http_counter")
            with self.assertRaises(AssertionError, msg="the suppressed counter passes the witness"):
                _run_witness(case, "test_a_broken_native_accounting_does_not_suppress_the_http_counter")

    def test_a_retired_engine_is_not_counted_again(self):
        """RETIRED_ENGINE_COUNTER_COUNTED_AGAIN: the retired engine's counter domain is forgotten."""

        def forgetting(self, c, instance, evictions):
            # the reversal: the retired mark is deleted, so the late observation looks like a first one
            if not instance:
                c["cache_evictions_unattributed"] += evictions
                return
            previous = self._evictions_by_engine.get(instance, 0)
            if evictions >= previous:
                c["cache_evictions"] += evictions - previous
                self._evictions_by_engine[instance] = evictions
            while len(self._evictions_by_engine) > 64:
                oldest = next(iter(self._evictions_by_engine))
                del self._evictions_by_engine[oldest]

        with patched(store.TelemetryStore, "_count_evictions_locked", forgetting):
            case = witnesses.BoundedAccounting("test_a_retired_engine_is_not_counted_again")
            with self.assertRaises(AssertionError, msg="the counted-again engine passes the witness"):
                _run_witness(case, "test_a_retired_engine_is_not_counted_again")

    def test_the_invocation_bytes_are_revalidated(self):
        """INVOCATION_BYTES_NOT_REVALIDATED: the byte bound is not checked after the terminal measurements."""

        def not_revalidating(self):
            return                                     # the reversal: the bound is never checked again

        with patched(record.RequestRecord, "revalidate_invocation_bytes", not_revalidating):
            case = witnesses.BoundedAccounting("test_the_retained_bytes_stay_inside_the_budget")
            with self.assertRaises(AssertionError, msg="the unbounded receipts pass the witness"):
                _run_witness(case, "test_the_retained_bytes_stay_inside_the_budget")

    def test_the_dropped_receipts_lower_the_coverage(self):
        """DROPPED_INVOCATIONS_EXCLUDED_FROM_DENOMINATOR: the dropped receipts are not in the population."""
        real = store.TelemetryStore._count_locked

        def excluding(self, data):
            # the reversal: the population is the RETAINED receipts only
            real(self, data)
            self.counters["native_invocations_missing"] -= max(
                0, int((data["measurement_quality"] or {}).get("invocations_dispatched") or 0)
                - len(data.get("invocations") or []))

        with patched(store.TelemetryStore, "_count_locked", excluding):
            case = witnesses.Coverage("test_a_dropped_receipt_lowers_the_coverage")
            with self.assertRaises(AssertionError, msg="the excluded receipts pass the witness"):
                _run_witness(case, "test_a_dropped_receipt_lowers_the_coverage")


if __name__ == "__main__":
    unittest.main()
