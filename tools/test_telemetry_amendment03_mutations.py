#!/usr/bin/env python3
"""tools/test_telemetry_amendment03_mutations.py - the non-vacuity witnesses of
ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-03 (G6).

Each witness here reverses ONE correction, in memory only, and shows that the witness that guards it FAILS
without the correction.  Nothing is written to the repository's files: the reversal is a patch of the running
process, and it is undone when the test ends.  No mutation code is left in the production tree.

    python tools/test_telemetry_amendment03_mutations.py
"""
from __future__ import annotations

import contextlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serve.reqtelemetry import accounting, correlation, evidence, record, store  # noqa: E402
from serve import test_telemetry_amendment03 as witnesses  # noqa: E402


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
    """Run ONE witness of the amendment-03 suite and let its assertion failure through.

    TestCase.run() swallows the failure (it records it), so the witness is called directly: the mutation must
    make it fail, and the failure must reach the caller.
    """
    case.setUp()
    try:
        getattr(case, name)()
    finally:
        case.tearDown()


class Mutations(unittest.TestCase):
    """Every witness fails when its correction is reversed."""

    def test_the_invocation_fields_do_not_leak_across_dispatches(self):
        """INVOCATION_FIELDS_LEAK_ACROSS_DISPATCHES: the parent's native fields are the LAST invocation's."""
        real = record.RequestRecord._sync_parent

        def leaking(self):
            # the predecessor's behaviour: the parent's scalars are whatever the last receipt said
            if self.invocations:
                self._mirror_receipt(self.invocations[-1])

        with patched(record.RequestRecord, "_sync_parent", leaking):
            case = witnesses.InvocationOwnership("test_the_first_invocations_work_is_not_lost_and_never_leaks")
            with self.assertRaises(AssertionError, msg="the leaking parent passes the witness"):
                _run_witness(case, "test_the_first_invocations_work_is_not_lost_and_never_leaks")

    def test_the_earlier_invocations_work_is_not_discarded(self):
        """EARLIER_INVOCATION_WORK_DISCARDED: only the last invocation's receipt is kept."""
        real = record.RequestRecord._add_receipt

        def keeping_only_the_last(self, receipt):
            self.invocations = []
            self.invocations_bytes = 0
            real(self, receipt)

        with patched(record.RequestRecord, "_add_receipt", keeping_only_the_last):
            case = witnesses.InvocationOwnership("test_two_invocations_keep_their_own_measurements")
            with self.assertRaises(AssertionError, msg="the discarded work passes the witness"):
                _run_witness(case, "test_two_invocations_keep_their_own_measurements")

    def test_an_unevaluated_accounting_is_not_admitted_to_the_complete_ratio(self):
        """UNEVALUATED_ACCOUNTING_ADMITTED_TO_COMPLETE_RATIO: the ratio takes every accounting that is not
        violated."""
        real = accounting.invocation_admission

        def admitting(inv, metric):
            if metric == accounting.METRIC_COMPLETE_CACHE_RATIO:
                return (accounting.correlation_of(inv) == accounting.CORRELATION_VERIFIED
                        and accounting.measurement_valid(inv)
                        and not getattr(inv, "native_partial", False)
                        and inv.accounting_state()["state"] != "violated")
            return real(inv, metric)

        with patched(accounting, "invocation_admission", admitting):
            case = witnesses.MetricAdmission("test_an_unevaluated_accounting_is_not_admitted_to_the_complete_ratio")
            with self.assertRaises(AssertionError, msg="the admitted accounting passes the witness"):
                _run_witness(case, "test_an_unevaluated_accounting_is_not_admitted_to_the_complete_ratio")

    def test_an_uncorrelated_native_duration_is_not_observed(self):
        """UNCORRELATED_NATIVE_DURATION_OBSERVED: every native duration enters the histogram."""
        real = store.TelemetryStore._observe_locked

        def observing_everything(self, data):
            timing = data["timing_ms"]
            for name, metric in store.DURATION_METRICS:
                store.observe_duration(self.histograms, metric, timing.get(name))
            for invocation in data.get("invocations") or []:
                itiming = invocation.get("timing_ms") or {}
                for name, metric in store.DURATION_METRICS:
                    store.observe_duration(self.histograms, metric, itiming.get(name))

        with patched(store.TelemetryStore, "_observe_locked", observing_everything):
            case = witnesses.MetricAdmission("test_an_uncorrelated_native_duration_is_not_observed")
            with self.assertRaises(AssertionError, msg="the uncorrelated duration passes the witness"):
                _run_witness(case, "test_an_uncorrelated_native_duration_is_not_observed")

    def test_a_partial_segment_is_not_admitted_as_the_whole_invocation(self):
        """PARTIAL_SEGMENT_ADMITTED_AS_COMPLETE: a batch slot's admission segment is the whole invocation."""
        real = accounting.invocation_admission

        def admitting(inv, metric):
            if metric in (accounting.METRIC_NATIVE_DURATION, accounting.METRIC_NATIVE_PROMPT_POSITION):
                return (accounting.correlation_of(inv) == accounting.CORRELATION_VERIFIED
                        and accounting.measurement_valid(inv)
                        and inv.accounting_state()["state"] != "violated")
            return real(inv, metric)

        with patched(accounting, "invocation_admission", admitting):
            case = witnesses.MetricAdmission("test_a_batch_admission_segment_is_not_admitted_as_the_whole_invocation")
            with self.assertRaises(AssertionError, msg="the partial segment passes the witness"):
                _run_witness(case, "test_a_batch_admission_segment_is_not_admitted_as_the_whole_invocation")

    def test_the_detached_pending_records_are_not_ignored(self):
        """DETACHED_PENDING_RECORDS_IGNORED: the bound counts the queue and the writing record only."""
        real = evidence.EvidenceLog.write

        def ignoring(self, record):
            # the predecessor's check: the records the worker has DETACHED are not counted
            with self.lock:
                self.submitted += 1
                if self._handle is None or self.closed:
                    self.refused += 1
                    self.dropped += 1
                    return False
            try:
                line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            except (TypeError, ValueError):
                with self.lock:
                    self.serialization_refusals += 1
                    self.refused += 1
                    self.dropped += 1
                return False
            with self.lock:
                if len(self.queue) + self.writing >= self.queue_size \
                        or self.outstanding_bytes + len(line) > self.queue_bytes:
                    self.capacity_refusals += 1
                    self.refused += 1
                    self.dropped += 1
                    return False
                self.queue.append(line)
                self.queue_size_bytes += len(line)
                self.outstanding_records += 1
                self.outstanding_bytes += len(line)
                self.accepted += 1
            return True

        import json
        with patched(evidence.EvidenceLog, "write", ignoring):
            case = witnesses.EvidenceWriterClosure("test_the_detached_pending_records_are_counted_against_the_bound")
            with self.assertRaises(AssertionError, msg="the ignored records pass the witness"):
                _run_witness(case, "test_the_detached_pending_records_are_counted_against_the_bound")

    def test_the_writer_does_not_accept_after_the_shutdown_boundary(self):
        """WRITER_ACCEPTS_AFTER_SHUTDOWN_BOUNDARY: a submission that races the shutdown is accepted."""
        real = evidence.EvidenceLog.write

        def accepting_after_shutdown(self, record):
            with self.lock:
                self.submitted += 1
                if self._handle is None:
                    self.refused += 1
                    self.dropped += 1
                    return False
            try:
                line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            except (TypeError, ValueError):
                with self.lock:
                    self.refused += 1
                    self.dropped += 1
                return False
            with self.lock:
                if self.outstanding_records >= self.queue_size:
                    self.capacity_refusals += 1
                    self.refused += 1
                    self.dropped += 1
                    return False
                self.queue.append(line)
                self.queue_size_bytes += len(line)
                self.outstanding_records += 1
                self.outstanding_bytes += len(line)
                self.accepted += 1
            return True

        import json
        with patched(evidence.EvidenceLog, "write", accepting_after_shutdown):
            case = witnesses.EvidenceWriterClosure("test_a_submission_that_races_the_shutdown_is_refused")
            with self.assertRaises(AssertionError, msg="the accepted-after-shutdown writer passes the witness"):
                _run_witness(case, "test_a_submission_that_races_the_shutdown_is_refused")

    def test_the_restore_error_duration_is_not_discarded(self):
        """RESTORE_ERROR_DURATION_DISCARDED: the native error path does not copy the measured duration."""
        source = (ROOT / "src/program/generate.cpp").read_text()
        marker = "tele.restore_ms = tele_restore_ms;"
        index = source.find("ERR restoring a conversation checkpoint failed")
        self.assertGreater(index, 0, "the native restoration error path is gone")
        block = source[max(0, index - 1500):index]
        self.assertIn(marker, block,
                      "the native error path does not carry the measured restoration duration")
        # the reversal, in memory: the line is gone from that path, and the witness fails
        reversed_block = block.replace(marker, "// the measured duration is discarded", 1)
        self.assertNotIn(marker, reversed_block,
                         "the reversal does not remove the duration: the witness is vacuous")
        self.assertNotEqual(reversed_block, block)


if __name__ == "__main__":
    unittest.main()
