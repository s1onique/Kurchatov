"""serve/test_telemetry_store_commit_correction.py - the witnesses of
ACT-STRATA-TELEMETRY-ATOMIC-STORE-COMMIT-01-CORRECTION-01.

The store's terminal aggregation is ONE-SHOT, and the store OWNS the record it aggregated.  A failed aggregation
resolves the dispatched population of its record as MISSING evidence: aggregating that record again would
account the SAME invocation a second time, and the population would be counted twice (accounted AND missing).

The witnesses of R1-R5 (serve/test_telemetry_store_commit.py) are preserved unchanged.

The non-vacuity (the reversal of each correction) is in
tools/test_telemetry_store_commit_correction_mutations.py.
"""
from __future__ import annotations

import unittest

from serve.reqtelemetry import RequestRecord, TelemetryStore, apply_engine, new_invocation_id
from serve.reqtelemetry.store import COMMITTED_RECORDS_LIMIT


def _dispatched(record, ordinal=1, domain="request", submitted=100):
    """ONE native dispatch of `record`: the receipt, bound before the dispatch, with its prompt domain named."""
    invocation = new_invocation_id()
    record.begin_invocation(invocation, ordinal=ordinal)
    receipt = record.invocation_for(invocation)
    receipt.submitted_tokens = submitted
    receipt.prompt_domain = domain
    return invocation


def _record(request_id="r1"):
    """A request with ONE dispatch whose terminal evidence arrived."""
    record = RequestRecord(request_id)
    record.set_prompt_tokens(rendered=100, submitted=100)
    invocation = _dispatched(record)
    apply_engine(record, {"rid": invocation, "matched": 90, "reused": 90, "evaluated": 10, "work": 10},
                 expected_invocation_id=invocation)
    return record


class _Fault:
    """A DETERMINISTIC fault injection: the REAL aggregation runs, and then the failure comes."""

    def __init__(self, store, error="the aggregation failed"):
        self.store = store
        self.error = error
        self.real = store._count_locked

    def _failing(self, data):
        self.real(data)                    # the REAL aggregation: it counts everything it would count
        raise RuntimeError(self.error)

    def __enter__(self):
        self.store._count_locked = self._failing
        return self

    def __exit__(self, *exc):
        self.store._count_locked = self.real
        return False


def _population(store):
    """The four numbers of the invocation population."""
    counters = store.counters
    return (counters["native_invocations"], counters["native_invocations_accounted"],
            counters["native_invocations_missing"], counters["native_invocations_unresolved"])


class TerminalAggregationIsOneShot(unittest.TestCase):
    """The terminal aggregation of a record happens once."""

    def test_the_failed_aggregation_is_not_aggregated_again(self):
        """ONE_SHOT_AGGREGATION_WITNESS: the retry of a failed aggregation is refused."""
        store = TelemetryStore()
        record = _record()
        with _Fault(store):
            with self.assertRaises(RuntimeError):
                store.add(record.seal("completed", 200))
        self.assertEqual(_population(store), (1, 0, 1, 0))

        # the RETRY of the same record through the store's own API
        with self.assertRaises(ValueError):
            store.add(record)

        # the population is unchanged: the same invocation is NOT accounted a second time
        self.assertEqual(_population(store), (1, 0, 1, 0))
        counters = store.counters
        # and it still conserves: dispatched = accounted + missing + unresolved
        self.assertEqual(counters["native_invocations"],
                         counters["native_invocations_accounted"]
                         + counters["native_invocations_missing"]
                         + counters["native_invocations_unresolved"])
        # the failed record was not kept
        self.assertEqual(store.records, [])
        self.assertEqual(store.bytes, 0)

    def test_the_refused_retry_changes_nothing_at_all(self):
        """The refused retry does not move a single counter."""
        store = TelemetryStore()
        record = _record()
        with _Fault(store):
            with self.assertRaises(RuntimeError):
                store.add(record.seal("completed", 200))
        counters_before = dict(store.counters)
        records_before = list(store.records)
        bytes_before = store.bytes
        seq_before = store.seq

        with self.assertRaises(ValueError):
            store.add(record)

        self.assertEqual(store.counters, counters_before)
        self.assertEqual(store.records, records_before)
        self.assertEqual(store.bytes, bytes_before)
        self.assertEqual(store.seq, seq_before)

    def test_a_record_that_never_reached_the_aggregation_may_be_aggregated(self):
        """A record whose terminal aggregation never RAN is not refused: it never resolved anything."""
        store = TelemetryStore()
        record = _record()
        store.add(record.seal("completed", 200))
        self.assertEqual(store.counters["native_invocations_accounted"], 1)


class StoreOwnership(unittest.TestCase):
    """The store that resolved a record's terminal aggregation owns it."""

    def test_a_record_of_another_store_is_refused(self):
        """STORE_OWNERSHIP_WITNESS: another store's committed record is refused, not returned."""
        first = TelemetryStore()
        record = _record()
        receipt = first.add(record.seal("completed", 200))

        second = TelemetryStore()
        with self.assertRaises(ValueError):
            second.add(record)

        # the second store did not aggregate the foreign record, and it did not return the first store's receipt
        self.assertEqual(second.counters["native_invocations"], 0)
        self.assertEqual(second.counters["native_invocations_accounted"], 0)
        self.assertEqual(second.records, [])
        self.assertIsNone(second.get(record.request_id))
        # the receipt is still exactly where it belongs: in the store that committed it
        self.assertIs(first.get(record.request_id), receipt)

    def test_the_owning_store_keeps_its_own_receipt(self):
        """The store that committed the record returns the SAME receipt, and counts nothing twice."""
        store = TelemetryStore()
        record = _record()
        first = store.add(record.seal("completed", 200))
        second = store.add(record)
        self.assertIs(first, second)
        self.assertEqual(store.counters["native_invocations_accounted"], 1)
        self.assertEqual(store.counters["requests_total"], 1)
        self.assertEqual(len(store.records), 1)

    def test_the_failed_record_of_another_store_is_refused(self):
        """A record whose terminal aggregation failed elsewhere is refused here too."""
        first = TelemetryStore()
        record = _record()
        with _Fault(first):
            with self.assertRaises(RuntimeError):
                first.add(record.seal("completed", 200))

        second = TelemetryStore()
        with self.assertRaises(ValueError):
            second.add(record)
        self.assertEqual(second.counters["native_invocations"], 0)
        self.assertEqual(second.counters["native_invocations_accounted"], 0)


class BoundedDeduplication(unittest.TestCase):
    """The content-based deduplication is bounded, and it is per store."""

    def test_the_committed_identities_are_bounded(self):
        """BOUNDED_DEDUPLICATION_WITNESS: the store's own state does not grow without limit."""
        store = TelemetryStore()
        for index in range(COMMITTED_RECORDS_LIMIT + 5):
            record = RequestRecord(f"r{index}")
            record.set_prompt_tokens(rendered=100, submitted=100)
            store.add(record.seal("completed", 200))
        self.assertLessEqual(len(store._committed), COMMITTED_RECORDS_LIMIT)
        self.assertEqual(store.counters["requests_total"], COMMITTED_RECORDS_LIMIT + 5)

    def test_the_deduplication_is_per_store(self):
        """The deduplication belongs to the store that committed: another store has its own."""
        first = TelemetryStore()
        second = TelemetryStore()
        for index in range(3):
            record = RequestRecord(f"r{index}")
            record.set_prompt_tokens(rendered=100, submitted=100)
            first.add(record.seal("completed", 200))
        self.assertEqual(first.counters["requests_total"], 3)
        self.assertEqual(second.counters["requests_total"], 0)
        self.assertEqual(len(first._committed), 3)
        self.assertEqual(len(second._committed), 0)


if __name__ == "__main__":
    unittest.main()
