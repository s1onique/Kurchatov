#!/usr/bin/env python3
"""tools/test_telemetry_amendment01_final_mutations.py - the non-vacuity witnesses of
ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (F1-F5).

Each witness here reverses ONE correction, IN MEMORY ONLY, and shows that the witness that guards it FAILS
without the correction.  Nothing is written to the repository's files: the reversal is a patch of the running
process, and it is undone when the test ends.  No mutation code is left in the production tree.

    python tools/test_telemetry_amendment01_final_mutations.py
"""
from __future__ import annotations

import contextlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# the serving layer lives in terminal/, so `serve.` is a package under terminal/.
for _p in (ROOT, ROOT / "terminal"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from serve.reqtelemetry import correlation, store  # noqa: E402
from serve import test_telemetry_amendment01_final as witnesses  # noqa: E402


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
    """Run ONE witness of the amendment-01 suite and let its assertion failure through."""
    case.setUp()
    try:
        getattr(case, name)()
    finally:
        case.tearDown()


class Mutations(unittest.TestCase):
    """Every witness fails when its correction is reversed."""

    def test_the_concurrent_request_accounts_for_the_failed_one(self):
        """CONCURRENT_POPULATION_WITNESS: the GLOBAL counters are read again."""
        def global_counters(self, _record):
            # the reversal: the outcome is read from the GLOBAL counters instead of the request's own
            with self.lock:
                return self.counters["native_invocations_accounted"]

        with patched(store.TelemetryStore, "count_unaccounted_dispatches", global_counters):
            case = witnesses.ConcurrentPopulation(
                "test_a_concurrent_request_does_not_account_for_a_failed_one")
            with self.assertRaises(AssertionError, msg="the concurrent request passes the witness"):
                _run_witness(case, "test_a_concurrent_request_does_not_account_for_a_failed_one")

    def test_the_dispatch_population_is_counted_twice(self):
        """DISPATCH_POPULATION_IDEMPOTENCY: the population boundary is not idempotent."""
        def counting_again(self, record):
            # the reversal: the mark is assigned AFTER the count, so a second call counts it again
            dispatched = int(getattr(record, "invocations_total", 0) or 0)
            with self.lock:
                self.counters["native_invocations"] += dispatched
            record._population_counted = True
            return dispatched

        with patched(store.TelemetryStore, "count_dispatch_population", counting_again):
            case = witnesses.ConcurrentPopulation("test_the_dispatch_population_is_counted_exactly_once")
            with self.assertRaises(AssertionError, msg="the repeated count passes the witness"):
                _run_witness(case, "test_the_dispatch_population_is_counted_exactly_once")

    def test_the_retained_receipts_decide_the_request_domain(self):
        """DROPPED_DOMAIN_WITNESS: the uniqueness is decided by the RETAINED receipts again."""
        def from_the_receipts(self, invocations):
            # the reversal: the request's own domain multiplicity is read from the receipts that survived
            ids = []
            for invocation in invocations:
                prompt = invocation.get("prompt") or {}
                if prompt.get("domain") == "request":
                    ids.append((invocation.get("identity") or {}).get("engine_invocation_id"))
            return ids[:1] if len(ids) == 1 else []

        with patched(store.TelemetryStore, "_request_coverage_ids", from_the_receipts):
            case = witnesses.RetentionIndependentDomainAuthority(
                "test_two_request_domain_dispatches_with_the_first_discarded")
            with self.assertRaises(AssertionError, msg="the dropped domain passes the witness"):
                _run_witness(case, "test_two_request_domain_dispatches_with_the_first_discarded")

    def test_the_terminal_state_is_not_part_of_the_evidence(self):
        """TERMINAL_STATE_DUPLICATE_WITNESS: the effective state is left out of the comparison."""
        original = correlation.normalize_terminal_evidence

        def without_the_state(figures, positional=None):
            evidence = original(figures, positional)
            evidence.pop("state", None)
            return evidence

        with patched(correlation, "normalize_terminal_evidence", without_the_state):
            case = witnesses.OneNormalizedTerminalAuthority(
                "test_a_duplicate_with_a_changed_native_state_is_a_conflict")
            with self.assertRaises(AssertionError, msg="the changed state passes the witness"):
                _run_witness(case, "test_a_duplicate_with_a_changed_native_state_is_a_conflict")

    def test_the_partial_classification_is_not_part_of_the_evidence(self):
        """PARTIAL_CLASSIFICATION_DUPLICATE_WITNESS: the effective partial flag is left out."""
        original = correlation.normalize_terminal_evidence

        def without_the_partial(figures, positional=None):
            evidence = original(figures, positional)
            evidence.pop("partial", None)
            return evidence

        with patched(correlation, "normalize_terminal_evidence", without_the_partial):
            case = witnesses.OneNormalizedTerminalAuthority(
                "test_a_duplicate_with_a_changed_partial_classification_is_a_conflict")
            with self.assertRaises(AssertionError, msg="the changed partial classification passes the witness"):
                _run_witness(case, "test_a_duplicate_with_a_changed_partial_classification_is_a_conflict")

    def test_the_schema_ids_are_the_same(self):
        """DISTINCT_SCHEMA_IDS: the current contract borrows the historical resource identity."""
        from serve.reqtelemetry import schema as schema_module
        original = schema_module.SCHEMA_V2
        with patched(schema_module, "SCHEMA_V2", dict(original, **{"$id": schema_module.SCHEMA_V3["$id"]})):
            case = witnesses.SchemaResourceIdentity("test_the_schema_ids_are_distinct")
            with self.assertRaises(AssertionError, msg="the shared identity passes the witness"):
                _run_witness(case, "test_the_schema_ids_are_distinct")

    def test_the_failed_request_is_not_counted_as_missing(self):
        """CONCURRENT_POPULATION_WITNESS: the failed request's dispatch is not counted at all."""
        def counting_nothing(self, _record):
            # the reversal: the failed request's dispatches are neither accounted nor missing
            return 0

        with patched(store.TelemetryStore, "count_unaccounted_dispatches", counting_nothing):
            case = witnesses.ConcurrentPopulation(
                "test_a_concurrent_request_does_not_account_for_a_failed_one")
            with self.assertRaises(AssertionError, msg="the uncounted request passes the witness"):
                _run_witness(case, "test_a_concurrent_request_does_not_account_for_a_failed_one")


if __name__ == "__main__":
    unittest.main()
