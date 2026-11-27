#!/usr/bin/env python3
"""tools/test_telemetry_store_commit_correction_mutations.py - the non-vacuity witnesses of
ACT-STRATA-TELEMETRY-ATOMIC-STORE-COMMIT-01-CORRECTION-01.

Each witness here reverses ONE correction, IN MEMORY ONLY, and shows that the witness that guards it FAILS
without the correction.  Nothing is written to the repository's files: the reversal is a patch of the running
process, and it is undone when the test ends.  No mutation code is left in the production tree.

    python tools/test_telemetry_store_commit_correction_mutations.py
"""
from __future__ import annotations

import contextlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serve.reqtelemetry import store  # noqa: E402
from serve import test_telemetry_store_commit_correction as witnesses  # noqa: E402


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
    """Run ONE witness of the correction suite and let its assertion failure through."""
    case.setUp()
    try:
        getattr(case, name)()
    finally:
        case.tearDown()


class Mutations(unittest.TestCase):
    """Every witness fails when its correction is reversed."""

    def test_the_failed_aggregation_is_aggregated_again(self):
        """ONE_SHOT_AGGREGATION_WITNESS: the terminal aggregation is not one-shot."""
        def aggregating_again(self, record):
            # the reversal: the one-shot refusal is gone, so the retry aggregates the record again
            return

        with patched(store.TelemetryStore, "_one_shot_locked", aggregating_again):
            case = witnesses.TerminalAggregationIsOneShot(
                "test_the_failed_aggregation_is_not_aggregated_again")
            with self.assertRaises(AssertionError, msg="the twice aggregated record passes the witness"):
                _run_witness(case, "test_the_failed_aggregation_is_not_aggregated_again")

    def test_the_store_ownership_is_not_enforced(self):
        """STORE_OWNERSHIP_WITNESS: another store's committed record is taken."""
        def taking_anything(self, record):
            # the reversal: the ownership boundary is gone, so a foreign record is aggregated here
            return

        with patched(store.TelemetryStore, "_one_shot_locked", taking_anything):
            case = witnesses.StoreOwnership("test_a_record_of_another_store_is_refused")
            with self.assertRaises(AssertionError, msg="the foreign record passes the witness"):
                _run_witness(case, "test_a_record_of_another_store_is_refused")


if __name__ == "__main__":
    unittest.main()
