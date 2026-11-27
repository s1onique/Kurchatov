#!/usr/bin/env python3
"""tools/test_telemetry_amendment01_mutations.py - the non-vacuity witnesses of
ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (A7).

Each witness here reverses ONE correction, IN MEMORY ONLY, and shows that the witness that guards it FAILS
without the correction.  Nothing is written to the repository's files: the reversal is a patch of the running
process, and it is undone when the test ends.  No mutation code is left in the production tree.

    python tools/test_telemetry_amendment01_mutations.py
"""
from __future__ import annotations

import contextlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import serve.reqtelemetry as rt  # noqa: E402
from serve.reqtelemetry import correlation, record, store  # noqa: E402
from serve import test_telemetry_amendment01 as witnesses  # noqa: E402


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

    def test_a_lost_parent_receipt_removes_the_native_dispatch_population(self):
        """LOST_PARENT_RECEIPT_REMOVES_NATIVE_DISPATCH_POPULATION."""
        def no_population(self, record_):
            # the reversal: the population is counted only when the receipt is stored
            return 0

        with patched(store.TelemetryStore, "count_dispatch_population", no_population):
            case = witnesses.DispatchPopulation(
                "test_a_lost_parent_receipt_keeps_the_native_dispatch_population")
            with self.assertRaises(AssertionError, msg="the lost parent receipt passes the witness"):
                _run_witness(case, "test_a_lost_parent_receipt_keeps_the_native_dispatch_population")

    def test_repeated_request_prompt_positions_accumulated(self):
        """REPEATED_REQUEST_PROMPT_POSITIONS_ACCUMULATED."""
        def every_domain(self, invocations):
            # the reversal: every invocation of the request's own domain is summed into the coverage
            ids = []
            for invocation in invocations:
                prompt = invocation.get("prompt") or {}
                if prompt.get("domain") == "request":
                    ids.append((invocation.get("identity") or {}).get("engine_invocation_id"))
            return ids

        with patched(store.TelemetryStore, "_request_coverage_ids", every_domain):
            case = witnesses.PromptDomainConservation(
                "test_the_same_prompt_dispatched_twice_is_not_counted_twice")
            with self.assertRaises(AssertionError, msg="the accumulated positions pass the witness"):
                _run_witness(case, "test_the_same_prompt_dispatched_twice_is_not_counted_twice")

    def test_unknown_prompt_domain_admitted_as_request(self):
        """UNKNOWN_PROMPT_DOMAIN_ADMITTED_AS_REQUEST: the length comparison is the reversal."""
        def by_length(self, invocations):
            # the reversal: an unnamed domain is the request's own domain
            ids = []
            for invocation in invocations:
                prompt = invocation.get("prompt") or {}
                domain = prompt.get("domain")
                same = domain == "request"
                if domain is None and prompt.get("submitted_tokens") is not None:
                    same = True
                if same:
                    ids.append((invocation.get("identity") or {}).get("engine_invocation_id"))
            return ids[:1] if len(ids) == 1 else []

        with patched(store.TelemetryStore, "_request_coverage_ids", by_length):
            case = witnesses.PromptDomainConservation(
                "test_an_unknown_prompt_domain_is_not_the_request_s_own")
            with self.assertRaises(AssertionError, msg="the unknown domain passes the witness"):
                _run_witness(case, "test_an_unknown_prompt_domain_is_not_the_request_s_own")

    def test_partial_payload_duplicate_comparison(self):
        """PARTIAL_PAYLOAD_DUPLICATE_COMPARISON: five prompt counters are not the terminal evidence."""
        def counters_only(figures, positional=None):
            figures = figures or {}
            return {key: figures.get(key) for key in ("matched", "reused", "evaluated", "replayed", "work")}

        with patched(correlation, "normalize_terminal_evidence", counters_only):
            case = witnesses.ImmutableTerminalEvidence(
                "test_a_duplicate_with_a_changed_duration_is_a_conflict")
            with self.assertRaises(AssertionError, msg="the partial comparison passes the witness"):
                _run_witness(case, "test_a_duplicate_with_a_changed_duration_is_a_conflict")

    def test_foreign_duplicate_mutates_the_accepted_receipt(self):
        """FOREIGN_DUPLICATE_MUTATES_ACCEPTED_RECEIPT."""
        original = correlation._duplicate_verdict

        def rejecting(record_, receipt, incoming, expected):
            # the reversal: the foreign receipt changes the accepted receipt's correlation
            receipt.correlation = "rejected"
            return original(record_, receipt, incoming, expected)

        with patched(correlation, "_duplicate_verdict", rejecting):
            case = witnesses.ImmutableTerminalEvidence(
                "test_a_foreign_receipt_after_the_accepted_one_keeps_the_accepted_receipt")
            with self.assertRaises(AssertionError, msg="the mutated receipt passes the witness"):
                _run_witness(case, "test_a_foreign_receipt_after_the_accepted_one_keeps_the_accepted_receipt")

    def test_native_outcome_inferred_from_the_http_outcome(self):
        """NATIVE_OUTCOME_INFERRED_FROM_HTTP_OUTCOME: every invocation ends as the request ended."""
        def always_completed(finish):
            return "completed"

        with patched(rt, "native_terminal_state", always_completed):
            case = witnesses.NativeOutcomeAuthority(
                "test_a_failed_native_invocation_stays_failed_when_the_request_recovers")
            with self.assertRaises(AssertionError, msg="the inferred outcome passes the witness"):
                _run_witness(case, "test_a_failed_native_invocation_stays_failed_when_the_request_recovers")

    def test_forgotten_engine_counter_counted_again(self):
        """FORGOTTEN_ENGINE_COUNTER_COUNTED_AGAIN: a forgotten identity looks new."""
        def never_seen(self, key):
            return False

        with patched(store._SeenEngines, "__contains__", never_seen):
            case = witnesses.EngineCounterDomain(
                "test_a_forgotten_engine_counter_is_not_counted_again")
            with self.assertRaises(AssertionError, msg="the counted-again counter passes the witness"):
                _run_witness(case, "test_a_forgotten_engine_counter_is_not_counted_again")

    def test_dropped_invocation_parent_mirror_survives(self):
        """DROPPED_INVOCATION_PARENT_MIRROR_SURVIVES: the stale mirror is kept."""
        def keep(self):
            return None

        with patched(record.RequestRecord, "_clear_native_fields", keep):
            case = witnesses.RetentionIntegrity("test_a_dropped_sole_invocation_clears_the_parent_mirror")
            with self.assertRaises(AssertionError, msg="the stale mirror passes the witness"):
                _run_witness(case, "test_a_dropped_sole_invocation_clears_the_parent_mirror")


if __name__ == "__main__":
    unittest.main()
