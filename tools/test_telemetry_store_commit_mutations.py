#!/usr/bin/env python3
"""tools/test_telemetry_store_commit_mutations.py - the non-vacuity witnesses of
ACT-STRATA-TELEMETRY-ATOMIC-STORE-COMMIT-01 (R1-R5).

Each witness here reverses ONE correction, IN MEMORY ONLY, and shows that the witness that guards it FAILS
without the correction.  Nothing is written to the repository's files: the reversal is a patch of the running
process, and it is undone when the test ends.  No mutation code is left in the production tree.

    python tools/test_telemetry_store_commit_mutations.py
"""
from __future__ import annotations

import contextlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serve.reqtelemetry import store  # noqa: E402
from serve import test_telemetry_store_commit as witnesses  # noqa: E402


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
    """Run ONE witness of the store-commit suite and let its assertion failure through."""
    case.setUp()
    try:
        getattr(case, name)()
    finally:
        case.tearDown()


def predecessor_add(self, record):
    """The reversal of R1 and R2: the retention commits BEFORE the aggregation.

    This is the predecessor's ordering: the record is kept (and the old records are evicted) before the
    aggregation runs, and the rollback removes the record again.  A failed transaction therefore evicts the
    evidence that was already retained, and a receipt that does not fit the budget is removed a second time -
    a record that does not exist.
    """
    data = record.to_dict()
    size = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    with self.lock:
        self.seq += 1
        record.seq = self.seq
        data["seq"] = self.seq
        self.records.append((self.seq, data, size))
        self.bytes += size
        self._evict_locked()
        snapshot = dict(self.counters)
        try:
            self._count_locked(data)
        except Exception:
            self.counters.clear()
            self.counters.update(snapshot)
            self.records.pop()               # the reversal: the record that may not be there is removed
            self.bytes -= size
            self.seq -= 1
            record.seq = 0
            raise
    return data


class Mutations(unittest.TestCase):
    """Every witness fails when its correction is reversed."""

    def test_the_retention_commits_before_the_aggregation(self):
        """RETENTION_ROLLBACK_WITNESS: the evidence that was retained is evicted by a failed transaction."""
        with patched(store.TelemetryStore, "add", predecessor_add):
            case = witnesses.RetentionRollback(
                "test_the_existing_evidence_survives_a_failed_aggregation")
            with self.assertRaises(AssertionError, msg="the evicted evidence passes the witness"):
                _run_witness(case, "test_the_existing_evidence_survives_a_failed_aggregation")

    def test_the_rollback_removes_a_record_that_does_not_exist(self):
        """OVERSIZED_ROLLBACK_WITNESS: the rollback removes a record that the retention already dropped."""
        with patched(store.TelemetryStore, "add", predecessor_add):
            case = witnesses.OversizedReceiptRollback(
                "test_the_original_exception_survives_an_oversized_receipt")
            with self.assertRaises(IndexError, msg="the lost exception passes the witness"):
                _run_witness(case, "test_the_original_exception_survives_an_oversized_receipt")

    def test_the_failed_transaction_marks_the_engine_as_seen(self):
        """MEMBERSHIP_FILTER_ROLLBACK_WITNESS: the membership filter is written before the commit."""
        real = store.TelemetryStore._count_evictions_locked

        def remembering_at_once(self, c, instance, evictions):
            # the reversal: the identity is remembered in the filter at once, and not at the commit
            real(self, c, instance, evictions)
            self._seen_engines.add(instance)

        with patched(store.TelemetryStore, "_count_evictions_locked", remembering_at_once):
            case = witnesses.MembershipFilterRollback(
                "test_the_failed_transaction_does_not_mark_the_engine_as_seen")
            with self.assertRaises(AssertionError, msg="the marked engine passes the witness"):
                _run_witness(case, "test_the_failed_transaction_does_not_mark_the_engine_as_seen")

    def test_the_sequence_field_is_not_accounted(self):
        """RETAINED_BYTES_WITNESS: the retained size is measured before the sequence field is inserted."""
        def without_the_sequence(payload, seq):
            # the reversal: the size of the record WITHOUT its sequence field
            return len(payload)

        with patched(store.TelemetryStore, "_kept_size", staticmethod(without_the_sequence)):
            case = witnesses.ExactRetainedBytes("test_the_retained_bytes_are_the_exact_serialized_size")
            with self.assertRaises(AssertionError, msg="the short size passes the witness"):
                _run_witness(case, "test_the_retained_bytes_are_the_exact_serialized_size")

    def test_the_committed_record_is_committed_again(self):
        """STORE_COMMIT_IDEMPOTENCY_WITNESS: the committed identity is not recognized."""
        def never_committed(self, record, digest):
            # the reversal: a record that is already committed is committed again
            return False

        with patched(store.TelemetryStore, "_is_committed_locked", never_committed):
            case = witnesses.StoreCommitIdempotency(
                "test_the_same_committed_record_is_not_committed_twice")
            with self.assertRaises(AssertionError, msg="the twice committed record passes the witness"):
                _run_witness(case, "test_the_same_committed_record_is_not_committed_twice")


if __name__ == "__main__":
    unittest.main()
