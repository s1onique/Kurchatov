"""serve/test_telemetry_store_commit.py - the witnesses of
ACT-STRATA-TELEMETRY-ATOMIC-STORE-COMMIT-01 (R1-R5).

The store's COMMIT is ATOMIC: the aggregation, the retention and the bookkeeping either all happen, or none of
them happens.  Every witness here injects a DETERMINISTIC failure AFTER the real aggregation ran, so the rollback
is measured against a transaction that really counted something.

The non-vacuity (the reversal of each correction) is in
tools/test_telemetry_store_commit_mutations.py.
"""
from __future__ import annotations

import copy
import json
import unittest

from serve.reqtelemetry import RequestRecord, ServerTelemetry, TelemetryStore, apply_engine, new_invocation_id


def _dispatched(record, ordinal=1, domain="request", submitted=100, engine=None):
    """ONE native dispatch of `record`: the receipt, bound before the dispatch, with its prompt domain named."""
    invocation = new_invocation_id()
    record.begin_invocation(invocation, ordinal=ordinal, engine_instance_id=engine)
    receipt = record.invocation_for(invocation)
    receipt.submitted_tokens = submitted
    receipt.prompt_domain = domain
    return invocation


def _evidence(invocation, **figures):
    """The engine's terminal evidence for one dispatch."""
    payload = {"rid": invocation}
    payload.update(figures)
    return payload


def _fixed_times(record):
    """The record's own timestamps, made FIXED: the content's LENGTH must not depend on the clock."""
    record.received_at = 1000.0
    record.started_at = 1000.0
    record.finished_at = 1000.0
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


class RetentionRollback(unittest.TestCase):
    """R1: a failed transaction does not touch the evidence that was already retained."""

    def test_the_existing_evidence_survives_a_failed_aggregation(self):
        """RETENTION_ROLLBACK_WITNESS: the record that was already kept is kept, and unchanged."""
        store = TelemetryStore(max_records=1)
        # request A: complete it, and keep its receipt
        first = RequestRecord("a")
        first.set_prompt_tokens(rendered=100, submitted=100)
        first_invocation = _dispatched(first)
        apply_engine(first, _evidence(first_invocation, matched=90, reused=90, evaluated=10, work=10),
                     expected_invocation_id=first_invocation)
        kept = store.add(first.seal("completed", 200, finish_reason="stop"))
        kept_bytes = store.bytes
        kept_counters = dict(store.counters)
        kept_histograms = copy.deepcopy(store.histograms)
        kept_evictions = store.counters["retention_evictions"]

        # request B: the REAL aggregation runs, and then it fails
        second = RequestRecord("b")
        second.set_prompt_tokens(rendered=100, submitted=100)
        second_invocation = _dispatched(second)
        apply_engine(second, _evidence(second_invocation, matched=90, reused=90, evaluated=10, work=10),
                     expected_invocation_id=second_invocation)
        with _Fault(store):
            with self.assertRaises(RuntimeError):
                store.add(second.seal("completed", 200, finish_reason="stop"))

        # A is still retained, and it is the SAME record
        self.assertEqual(len(store.records), 1, "the retained evidence was lost")
        self.assertEqual(store.records[0][1]["identity"]["request_id"], "a")
        self.assertEqual(store.records[0][1], kept)
        # the retained bytes describe A exactly
        self.assertEqual(store.bytes, kept_bytes)
        self.assertEqual(store.bytes, len(json.dumps(kept, ensure_ascii=False).encode("utf-8")))
        # the retention-eviction counter is unchanged
        self.assertEqual(store.counters["retention_evictions"], kept_evictions)
        # B is not retained
        self.assertIsNone(store.get("b"))
        # B's dispatch is counted as MISSING evidence
        counters = store.counters
        self.assertEqual(counters["native_invocations"], 2)
        self.assertEqual(counters["native_invocations_accounted"], 1)
        self.assertEqual(counters["native_invocations_missing"], 1)
        self.assertEqual(counters["native_invocations_unresolved"], 0)
        # the measurements that were accepted before are unchanged
        self.assertEqual(counters["prompt_tokens_evaluated"], kept_counters["prompt_tokens_evaluated"])
        self.assertEqual(counters["prompt_tokens_reused"], kept_counters["prompt_tokens_reused"])
        self.assertEqual(counters["native_positions_evaluated_total"],
                         kept_counters["native_positions_evaluated_total"])
        self.assertEqual(counters["requests_total"], kept_counters["requests_total"])
        self.assertEqual(store.histograms, kept_histograms)

    def test_the_failed_transaction_keeps_the_sequence_and_the_bytes(self):
        """The sequence state and the byte accounting survive a failed transaction."""
        store = TelemetryStore(max_records=4)
        for index in range(2):
            record = RequestRecord(f"r{index}")
            record.set_prompt_tokens(rendered=100, submitted=100)
            store.add(record.seal("completed", 200, finish_reason="stop"))
        seq_before = store.seq
        bytes_before = store.bytes
        records_before = list(store.records)

        failing = RequestRecord("boom")
        failing.set_prompt_tokens(rendered=100, submitted=100)
        with _Fault(store):
            with self.assertRaises(RuntimeError):
                store.add(failing.seal("completed", 200, finish_reason="stop"))

        self.assertEqual(store.seq, seq_before, "the sequence moved without a commit")
        self.assertEqual(store.bytes, bytes_before)
        self.assertEqual(store.records, records_before)
        self.assertEqual(store.counters["receipts_created"], 2)


class OversizedReceiptRollback(unittest.TestCase):
    """R2: a receipt that does not fit the budget rolls back cleanly."""

    def _oversized(self, request_id="big"):
        """A record whose serialized receipt is larger than the store's byte budget."""
        record = RequestRecord(request_id)
        record.set_prompt_tokens(rendered=100, submitted=100)
        invocation = _dispatched(record)
        apply_engine(record, _evidence(invocation, matched=90, reused=90, evaluated=10, work=10),
                     expected_invocation_id=invocation)
        record.seal("completed", 200, detail="x" * 5000)
        size = len(json.dumps(record.to_dict(), ensure_ascii=False).encode("utf-8"))
        self.assertGreater(size, 4096, "the receipt is not oversized")
        return record

    def test_the_original_exception_survives_an_oversized_receipt(self):
        """OVERSIZED_ROLLBACK_WITNESS: the failure is the failure, and nothing was touched."""
        store = TelemetryStore(max_bytes=4096)
        record = self._oversized()
        with _Fault(store, "the aggregation failed"):
            with self.assertRaises(RuntimeError) as caught:
                store.add(record)
        self.assertEqual(str(caught.exception), "the aggregation failed")
        # the rollback did not remove a record that does not exist
        self.assertEqual(store.records, [])
        self.assertEqual(store.bytes, 0)
        # the sequence and the retention accounting are consistent
        self.assertEqual(store.seq, 0)
        self.assertEqual(store.counters["retention_evictions"], 0)
        # the dispatch population conserves
        counters = store.counters
        self.assertEqual(counters["native_invocations"], 1)
        self.assertEqual(counters["native_invocations_accounted"], 0)
        self.assertEqual(counters["native_invocations_missing"], 1)
        self.assertEqual(counters["native_invocations_unresolved"], 0)

    def test_the_previously_retained_records_are_unchanged(self):
        """The records that were already retained survive the failed oversized receipt."""
        store = TelemetryStore(max_bytes=4096)
        kept = RequestRecord("kept")
        kept.set_prompt_tokens(rendered=100, submitted=100)
        store.add(kept.seal("completed", 200, finish_reason="stop"))
        records_before = list(store.records)
        bytes_before = store.bytes

        record = self._oversized()
        with _Fault(store):
            with self.assertRaises(RuntimeError):
                store.add(record)

        self.assertEqual(store.records, records_before)
        self.assertEqual(store.bytes, bytes_before)
        self.assertEqual(store.counters["retention_evictions"], 0)

    def test_the_successful_oversized_receipt_keeps_the_retention_policy(self):
        """The documented retention policy of an oversized receipt is unchanged."""
        store = TelemetryStore(max_bytes=4096)
        record = self._oversized()
        store.add(record)
        # the receipt does not fit: it is dropped at once, and the store stays inside its bounds
        self.assertEqual(store.records, [])
        self.assertEqual(store.bytes, 0)
        self.assertEqual(store.counters["retention_evictions"], 1)
        # the request itself is committed: its measurements are counted
        self.assertEqual(store.counters["requests_total"], 1)
        self.assertEqual(store.counters["receipts_created"], 1)


class MembershipFilterRollback(unittest.TestCase):
    """R3: a failed transaction does not mark an uncommitted counter domain as observed."""

    def _engine_record(self, request_id, engine, evictions):
        """A request of ONE engine, reporting its cumulative eviction counter."""
        record = RequestRecord(request_id)
        record.engine_instance_id = engine
        invocation = new_invocation_id()
        record.begin_invocation(invocation, ordinal=1, engine_instance_id=engine)
        apply_engine(record, {"rid": invocation, "evictions": evictions}, expected_invocation_id=invocation)
        return record

    def test_the_failed_transaction_does_not_mark_the_engine_as_seen(self):
        """MEMBERSHIP_FILTER_ROLLBACK_WITNESS: the counter domain of a failed transaction stays uncommitted."""
        store = TelemetryStore()
        record = self._engine_record("r1", "engine-x", 10)
        with _Fault(store):
            with self.assertRaises(RuntimeError):
                store.add(record.seal("completed", 200))
        counters = store.counters
        # the authoritative total of the failed transaction is rolled back
        self.assertEqual(counters["cache_evictions"], 0)
        self.assertEqual(counters["cache_evictions_unattributed"], 0)
        # and the engine is NOT marked as previously observed
        self.assertNotIn("engine-x", store._seen_engines)

        # the next request of the SAME engine reports 11 cumulative evictions
        following = self._engine_record("r2", "engine-x", 11)
        store.add(following.seal("completed", 200))
        counters = store.counters
        self.assertEqual(counters["cache_evictions"], 11)
        self.assertEqual(counters["cache_evictions_unattributed"], 0)
        self.assertEqual(counters["cache_evictions_attribution_unavailable"], 0)


class ExactRetainedBytes(unittest.TestCase):
    """R4: the retained size is the EXACT size of the record that is kept."""

    def test_the_retained_bytes_are_the_exact_serialized_size(self):
        """RETAINED_BYTES_WITNESS: the store's byte accounting is the size of the documents it keeps."""
        store = TelemetryStore()
        for index in range(12):
            record = _fixed_times(RequestRecord(f"r{index:03d}"))
            record.set_prompt_tokens(rendered=100, submitted=100)
            record.seal("completed", 200, finish_reason="stop")
            _fixed_times(record)              # the seal sets the finish time: it is fixed again
            store.add(record)
        total = 0
        for seq, data, size in store.records:
            exact = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            self.assertEqual(size, exact, f"the retained size of the record {seq} is not its exact size")
            total += exact
        self.assertEqual(store.bytes, total)

    def test_the_sequence_width_is_accounted(self):
        """The sequence's own width is part of the size: 9 -> 10 and 99 -> 100."""
        for seq in (9, 10, 99, 100):
            record = _fixed_times(RequestRecord("r"))
            record.set_prompt_tokens(rendered=100, submitted=100)
            record.seal("completed", 200, finish_reason="stop")
            data = record.to_dict()
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            kept = TelemetryStore._kept_size(payload, seq)
            data["seq"] = seq
            exact = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            self.assertEqual(kept, exact, f"the size of the record {seq} is not its exact size")
        # the width transitions cost exactly one byte
        record = _fixed_times(RequestRecord("r"))
        record.set_prompt_tokens(rendered=100, submitted=100)
        record.seal("completed", 200, finish_reason="stop")
        payload = json.dumps(record.to_dict(), ensure_ascii=False).encode("utf-8")
        self.assertEqual(TelemetryStore._kept_size(payload, 10) - TelemetryStore._kept_size(payload, 9), 1)
        self.assertEqual(TelemetryStore._kept_size(payload, 100) - TelemetryStore._kept_size(payload, 99), 1)

    def test_the_stored_records_account_for_their_own_width(self):
        """The transition happens in the store itself: the record 10 is one byte larger than the record 9."""
        store = TelemetryStore()
        sizes = {}
        for index in range(101):
            record = _fixed_times(RequestRecord(f"r{index:03d}"))
            record.set_prompt_tokens(rendered=100, submitted=100)
            record.seal("completed", 200, finish_reason="stop")
            _fixed_times(record)              # the seal sets the finish time: it is fixed again
            store.add(record)
            sizes[store.seq] = store.records[-1][2]
        self.assertEqual(sizes[10] - sizes[9], 1)
        self.assertEqual(sizes[100] - sizes[99], 1)
        self.assertEqual(store.bytes, sum(sizes.values()))


class StoreCommitIdempotency(unittest.TestCase):
    """R5: a committed record is not committed again."""

    def test_the_same_committed_record_is_not_committed_twice(self):
        """STORE_COMMIT_IDEMPOTENCY_WITNESS: the same measurement is counted exactly once."""
        tel = ServerTelemetry()
        record = tel.begin(api="openai", client_request_id="a", model_id="m")
        record.set_prompt_tokens(rendered=100, submitted=100)
        invocation = _dispatched(record)
        apply_engine(record, _evidence(invocation, matched=90, reused=90, evaluated=10, work=10),
                     expected_invocation_id=invocation)
        tel.finish(record, state="completed", http_status=200, finish_reason="stop")
        before = tel.store.summary()
        self.assertEqual(before["cache_reuse"]["requests"], 1)
        self.assertEqual(before["cache_reuse"]["eligible_requests"], 1)
        self.assertEqual(before["cache_reuse"]["invocations"], 1)
        self.assertEqual(before["cache_reuse"]["eligible_invocations"], 1)
        self.assertEqual(before["cache_reuse"]["coverage"], 1.0)
        self.assertEqual(before["cache_reuse"]["request_coverage"], 1.0)

        # the SAME committed record, through the store's own API
        tel.store.add(record)
        after = tel.store.summary()
        self.assertEqual(after["cache_reuse"]["requests"], 1)
        self.assertEqual(after["cache_reuse"]["eligible_requests"], 1)
        self.assertEqual(after["cache_reuse"]["invocations"], 1)
        self.assertEqual(after["cache_reuse"]["eligible_invocations"], 1)
        self.assertEqual(after["cache_reuse"]["coverage"], 1.0)
        self.assertEqual(after["cache_reuse"]["request_coverage"], 1.0)
        # the authoritative measurements and the histograms are not counted again
        self.assertEqual(after["counters"], before["counters"])
        self.assertEqual(after["histograms"], before["histograms"])
        self.assertEqual(after["retention"]["records"], before["retention"]["records"])

    def test_a_different_record_is_still_committed(self):
        """The idempotency is about the SAME record: a different one is committed as usual."""
        store = TelemetryStore()
        for index in range(3):
            record = RequestRecord(f"r{index}")
            record.set_prompt_tokens(rendered=100, submitted=100)
            store.add(record.seal("completed", 200, finish_reason="stop"))
        self.assertEqual(store.counters["requests_total"], 3)
        self.assertEqual(len(store.records), 3)


if __name__ == "__main__":
    unittest.main()
