#!/usr/bin/env python3
"""serve/test_telemetry_amendment03.py - the witnesses of
ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-03.

Every witness here drives the PRODUCTION code: the real store (serve/reqtelemetry/store.py), the real correlation
(serve/reqtelemetry/correlation.py), the real evidence writer (serve/reqtelemetry/evidence.py), the real HTTP
handlers (serve/server.py) and the real exporter (serve/prometheus.py).  A witness that only calls a setter does
not qualify.

  * G1: every native dispatch owns its OWN measurement receipt; a measurement of one invocation is never published
    under the identity of another one;
  * G2: the admission is METRIC-SPECIFIC - the complete ratio, the durations and the work counters each have
    their own rule;
  * G3: the evidence writer's acceptance boundary is atomic and its counter domains are exact;
  * G4: the native error evidence keeps the duration that was already measured;
  * G5: the lifecycle and the boundedness checks.
"""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serve.reqtelemetry import (RequestRecord, ServerTelemetry, TelemetryStore, apply_engine,  # noqa: E402
                                new_invocation_id)
from serve.reqtelemetry.accounting import (METRIC_COMPLETE_CACHE_RATIO, METRIC_NATIVE_DURATION,  # noqa: E402
                                            METRIC_NATIVE_EXECUTION_WORK, METRIC_NATIVE_PROMPT_POSITION)
from serve.reqtelemetry.evidence import EvidenceLog  # noqa: E402
from serve.server import ByteTokenizer, MockEngine, Service  # noqa: E402


class ScriptedEngine(MockEngine):
    """A mock engine that reports the figures of a real DONE line and echoes the INVOCATION's id.

    The real engine echoes the id of the invocation it is running (include/strata/program/reqtelemetry.hpp); this
    fixture does the same, so the server's reader is exercised exactly as it is in production.  Each dispatch gets
    its own DONE, with its own figures.
    """

    def __init__(self, tok, scripts, telemetry_by_call=None, raise_after=None):
        super().__init__(tok, scripts, max_context=100000)
        self.telemetry_by_call = list(telemetry_by_call or [])
        self.raise_after = raise_after
        self.calls = 0
        self.prompts = []

    def generate(self, ids, max_new, sampling, cancel, embeddings=None):
        index = self.calls
        self.calls += 1
        self.prompts.append(list(ids))
        rid = getattr(self, "request_id", lambda: None)()
        produced = 0
        try:
            for token in super().generate(ids, max_new, sampling, cancel, embeddings=embeddings):
                produced += 1
                yield token
                if self.raise_after is not None and produced >= self.raise_after:
                    raise RuntimeError("the engine broke after the answer had started")
        finally:
            # this dispatch's DONE line: its own figures and its own invocation's id
            self.last = {"generated": produced, "prompt_ms": 10.0, "decode_ms": 20.0, "finish": "stop"}
            figures = dict(self.telemetry_by_call[index] if index < len(self.telemetry_by_call) else {})
            if rid:
                figures["rid"] = rid
            self.last["telemetry"] = figures


def _service(engine, tok):
    service = Service(engine, tok, None)
    service.answer_room = False
    return service


def _run(service, ids, sampling=None, thinking=True, max_new=40000):
    """The PRODUCTION dispatch loop: the same code the HTTP handler runs."""
    return list(service.run(ids, thinking, [], max_new, sampling or {}, threading.Event()))


class InvocationOwnership(unittest.TestCase):
    """G1: one native dispatch owns one measurement receipt."""

    def setUp(self):
        self.tok = ByteTokenizer()
        self.ids = self.tok.encode('user\nSolve this task\nassistant\n', parse_special=True)

    def _two_dispatch_service(self, telemetry_by_call=None):
        """A request that dispatches TWICE: the thinking budget wraps the reasoning up and continues."""
        figures = telemetry_by_call or [
            {"matched": 100, "reused": 100, "evaluated": 20, "work": 20, "lookup_ms": 1234.0},
            {"matched": 40, "reused": 40, "evaluated": 60, "work": 60, "lookup_ms": 12.0},
        ]
        engine = ScriptedEngine(self.tok, ["<think>" + "thinking about it. " * 200, "the answer."],
                                telemetry_by_call=figures)
        service = _service(engine, self.tok)
        return engine, service

    def test_one_request_and_one_invocation_keep_their_own_measurements(self):
        engine = ScriptedEngine(self.tok, ["hello"], telemetry_by_call=[
            {"matched": 40, "reused": 40, "evaluated": 60, "work": 60, "lookup_ms": 7.0}])
        service = _service(engine, self.tok)
        record = service.telemetry_requests.begin(model_id="m")
        service.telemetry_trace.record = record
        _run(service, self.ids, thinking=False, max_new=64)
        data = service.telemetry_requests.finish(record, state="completed", http_status=200)
        self.assertEqual(engine.calls, 1)
        self.assertEqual(len(data["invocations"]), 1)
        receipt = data["invocations"][0]
        self.assertEqual(receipt["prompt"]["evaluated_tokens"], 60)
        self.assertEqual(receipt["timing_ms"]["cache_lookup"], 7.0)
        self.assertEqual(receipt["measurement_quality"]["native_correlation"], "verified")

    def test_two_invocations_keep_their_own_measurements(self):
        engine, service = self._two_dispatch_service()
        record = service.telemetry_requests.begin(model_id="m")
        service.telemetry_trace.record = record
        _run(service, self.ids, sampling={"reasoning_budget_tokens": 50})
        data = service.telemetry_requests.finish(record, state="completed", http_status=200)
        self.assertEqual(engine.calls, 2)
        self.assertEqual(len(data["invocations"]), 2)
        first, second = data["invocations"]
        self.assertEqual(first["prompt"]["evaluated_tokens"], 20)
        self.assertEqual(second["prompt"]["evaluated_tokens"], 60)
        self.assertEqual(first["timing_ms"]["cache_lookup"], 1234.0)
        self.assertEqual(second["timing_ms"]["cache_lookup"], 12.0)
        self.assertNotEqual(first["identity"]["engine_invocation_id"], second["identity"]["engine_invocation_id"])

    def test_the_first_invocations_work_is_not_lost_and_never_leaks(self):
        """The witness of G1: invocation B's numbers stay B's; invocation C never inherits them."""
        engine, service = self._two_dispatch_service()
        record = service.telemetry_requests.begin(model_id="m")
        service.telemetry_trace.record = record
        _run(service, self.ids, sampling={"reasoning_budget_tokens": 50})
        data = service.telemetry_requests.finish(record, state="completed", http_status=200)
        first, second = data["invocations"]
        # B's work is preserved
        self.assertEqual(first["prompt"]["evaluated_tokens"], 20)
        self.assertEqual(first["prompt"]["reused_prefix_tokens"], 100)
        # C does not inherit it: the parent's native scalars are ambiguous and null
        self.assertIsNone(data["prompt"]["evaluated_tokens"])
        self.assertIsNone(data["prompt"]["reused_prefix_tokens"])
        self.assertIsNone(data["timing_ms"].get("cache_lookup"))
        # and C's own numbers are C's
        self.assertEqual(second["prompt"]["evaluated_tokens"], 60)

    def test_a_field_the_first_reported_and_the_second_omitted_stays_null_in_the_second(self):
        engine, service = self._two_dispatch_service(telemetry_by_call=[
            {"matched": 100, "reused": 100, "evaluated": 20, "work": 20, "lookup_ms": 1234.0},
            {"matched": 40, "reused": 40},          # no evaluated, no lookup
        ])
        record = service.telemetry_requests.begin(model_id="m")
        service.telemetry_trace.record = record
        _run(service, self.ids, sampling={"reasoning_budget_tokens": 50})
        data = service.telemetry_requests.finish(record, state="completed", http_status=200)
        first, second = data["invocations"]
        self.assertEqual(first["prompt"]["evaluated_tokens"], 20)
        self.assertEqual(first["timing_ms"]["cache_lookup"], 1234.0)
        # the second invocation did not report them: they are null, not the first invocation's
        self.assertIsNone(second["prompt"]["evaluated_tokens"])
        self.assertIsNone(second["timing_ms"].get("cache_lookup"))
        self.assertIn("prompt.evaluated_tokens", second["measurement_quality"]["unavailable_fields"])

    def test_a_stale_receipt_from_an_earlier_invocation_is_refused(self):
        """The receipt of an invocation that is not the one being waited for carries somebody else's numbers."""
        record = RequestRecord("r1")
        first, second = new_invocation_id(), new_invocation_id()
        record.begin_invocation(first, ordinal=1)
        record.begin_invocation(second, ordinal=2)
        verdict = apply_engine(record, {"rid": first, "matched": 10, "reused": 10, "evaluated": 5},
                                expected_invocation_id=second)
        self.assertEqual(verdict["correlation"], "rejected")
        self.assertFalse(verdict["admitted"])
        # the stale receipt did not touch the invocation that is running
        self.assertIsNone(record.invocation_for(second).evaluated_tokens)
        self.assertIsNone(record.invocation_for(first).evaluated_tokens)

    def test_a_duplicate_terminal_receipt_does_not_count_the_work_twice(self):
        store = TelemetryStore()
        record = RequestRecord("r1")
        invocation = new_invocation_id()
        record.begin_invocation(invocation, ordinal=1)
        figures = {"rid": invocation, "matched": 40, "reused": 40, "evaluated": 60, "work": 60}
        apply_engine(record, figures, expected_invocation_id=invocation)
        apply_engine(record, figures, expected_invocation_id=invocation)      # the same receipt, twice
        store.add(record.seal("completed", 200))
        counters = store.summary()["counters"]
        self.assertEqual(counters["prompt_tokens_evaluated"], 60)
        self.assertEqual(counters["prompt_evaluation_work_tokens"], 60)
        self.assertEqual(counters["native_invocations"], 1)

    def test_two_concurrent_requests_keep_their_own_measurements(self):
        """Two requests at once, with different figures: no cross-request attribution."""
        engine = ScriptedEngine(self.tok, ["a", "b"], telemetry_by_call=[
            {"matched": 10, "reused": 10, "evaluated": 5, "work": 5},
            {"matched": 20, "reused": 20, "evaluated": 80, "work": 80},
        ])
        service = _service(engine, self.tok)
        records = []
        errors = []

        def one(index):
            try:
                record = service.telemetry_requests.begin(model_id="m")
                service.telemetry_trace.record = record
                _run(service, self.ids, thinking=False, max_new=32)
                records.append((index, service.telemetry_requests.finish(record, state="completed",
                                                                         http_status=200)))
            except Exception as e:                       # noqa: BLE001 - the witness reports it
                errors.append(e)

        threads = [threading.Thread(target=one, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual(errors, [])
        seen = sorted((data["prompt"]["evaluated_tokens"], data["identity"]["request_id"]) for _, data in records)
        self.assertEqual([value for value, _ in seen], [5, 80])
        self.assertEqual(len({rid for _, rid in seen}), 2)

    def test_an_engine_restart_between_the_preparation_and_the_dispatch(self):
        """The engine's identity is bound BEFORE the dispatch: a restart gives the next invocation its own
        identity, and the two counters do not merge."""
        record = RequestRecord("r1")
        first = new_invocation_id()
        record.begin_invocation(first, ordinal=1, engine_instance_id="pid-1-gen-0")
        apply_engine(record, {"rid": first, "matched": 10, "reused": 10, "evaluated": 5, "evictions": 4},
                     expected_invocation_id=first)
        second = new_invocation_id()
        record.begin_invocation(second, ordinal=2, engine_instance_id="pid-2-gen-0")
        apply_engine(record, {"rid": second, "matched": 10, "reused": 10, "evaluated": 5, "evictions": 7},
                     expected_invocation_id=second)
        self.assertEqual(record.invocation_for(first).engine_instance_id, "pid-1-gen-0")
        self.assertEqual(record.invocation_for(second).engine_instance_id, "pid-2-gen-0")
        self.assertNotEqual(record.invocation_for(first).invocation_id, record.invocation_for(second).invocation_id)

    def test_a_recovery_invocation_with_another_prompt_length_is_another_domain(self):
        """The positions of an invocation that worked on ANOTHER prompt are never this prompt's coverage."""
        store = TelemetryStore()
        record = RequestRecord("r1")
        record.set_prompt_tokens(rendered=100, submitted=100)
        first = new_invocation_id()
        record.begin_invocation(first, ordinal=1)
        record.invocation_for(first).submitted_tokens = 100
        apply_engine(record, {"rid": first, "matched": 100, "reused": 100, "evaluated": 0, "work": 0},
                     expected_invocation_id=first)
        second = new_invocation_id()
        record.begin_invocation(second, ordinal=2)
        record.invocation_for(second).submitted_tokens = 40          # the recovery sent another prompt
        apply_engine(record, {"rid": second, "matched": 40, "reused": 0, "evaluated": 40, "work": 40},
                     expected_invocation_id=second)
        store.add(record.seal("completed", 200))
        counters = store.summary()["counters"]
        # the request's own prompt domain: the first invocation's positions
        self.assertEqual(counters["prompt_tokens_evaluated"], 0)
        self.assertEqual(counters["prompt_tokens_reused"], 100)
        # the other domain's positions are work, published apart
        self.assertEqual(counters["native_positions_evaluated_total"], 40)
        self.assertEqual(counters["native_positions_reused_total"], 100)

    def test_the_invocation_history_is_bounded_and_the_loss_is_counted(self):
        record = RequestRecord("r1")
        for index in range(12):
            record.begin_invocation(new_invocation_id(), ordinal=index + 1)
        self.assertLessEqual(len(record.invocations), 8)
        self.assertGreater(record.invocations_dropped, 0)
        data = record.to_dict()
        self.assertGreaterEqual(data["measurement_quality"]["invocations_dropped"], 1)
        self.assertIn("invocations", data["measurement_quality"]["unavailable_fields"])


class MetricAdmission(unittest.TestCase):
    """G2: the admission is metric-specific."""

    def _record_with(self, figures, submitted=100, **kw):
        store = TelemetryStore()
        record = RequestRecord("r1")
        record.set_prompt_tokens(rendered=submitted, submitted=submitted)
        invocation = new_invocation_id()
        record.begin_invocation(invocation, ordinal=1)
        record.invocation_for(invocation).submitted_tokens = submitted
        figures = dict(figures)
        figures["rid"] = invocation
        apply_engine(record, figures, expected_invocation_id=invocation, **kw)
        store.add(record.seal("completed", 200))
        return store, record

    def test_an_unevaluated_accounting_is_not_admitted_to_the_complete_ratio(self):
        """The witness of G2a: the accounting did not close, so the prompt is not in the ratio's population."""
        store, record = self._record_with({"matched": 90, "reused": 90, "evaluated": None})
        receipt = record.to_dict()["invocations"][0]
        self.assertEqual(receipt["measurement_quality"]["accounting"]["state"], "unevaluated")
        self.assertFalse(receipt["measurement_quality"]["admission"][METRIC_COMPLETE_CACHE_RATIO])
        counters = store.summary()["counters"]
        self.assertEqual(counters["requests_reuse_accounted"], 0)
        self.assertEqual(counters["native_invocations_accounted"], 0)
        self.assertEqual(counters["native_invocations_missing"], 1)

    def test_a_valid_partial_work_counter_stays_eligible(self):
        """G2a: a measured work counter keeps its own authority when the complete accounting is unavailable."""
        store, record = self._record_with({"matched": 90, "reused": 90, "evaluated": None, "work": 12, "replayed": 2})
        receipt = record.to_dict()["invocations"][0]
        self.assertEqual(receipt["measurement_quality"]["accounting"]["state"], "unevaluated")
        self.assertTrue(receipt["measurement_quality"]["admission"][METRIC_NATIVE_EXECUTION_WORK])
        counters = store.summary()["counters"]
        self.assertEqual(counters["prompt_evaluation_work_tokens"], 12)
        self.assertEqual(counters["prompt_tokens_replayed"], 2)

    def test_an_uncorrelated_native_duration_is_not_observed(self):
        """The witness of G2b: no correlation, no native duration observation; the HTTP one is observed."""
        store = TelemetryStore()
        record = RequestRecord("r1")
        record.set_prompt_tokens(rendered=100, submitted=100)
        record.set_timing("total", 1500.0, "http_server")
        invocation = new_invocation_id()
        record.begin_invocation(invocation, ordinal=1)
        record.invocation_for(invocation).submitted_tokens = 100
        # the engine did not echo the id: the correlation is unavailable, never an asserted join.
        # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D2b): the receipt is the one this request
        # DISPATCHED - the terminal evidence never creates a dispatch, so the uncorrelated duration is measured
        # on a receipt that really exists, and it must still not be observed.
        apply_engine(record, {"matched": 90, "reused": 90, "evaluated": 10, "lookup_ms": 1234.0},
                     expected_invocation_id=invocation)
        store.add(record.seal("completed", 200))
        histograms = store.summary()["histograms"]
        self.assertEqual(histograms.get("cache_lookup_duration", {}).get("count", 0), 0)
        self.assertEqual(histograms["request_duration"]["count"], 1)

    def test_a_correlated_native_duration_is_observed(self):
        store, record = self._record_with({"matched": 90, "reused": 90, "evaluated": 10, "lookup_ms": 1234.0})
        histograms = store.summary()["histograms"]
        self.assertEqual(histograms["cache_lookup_duration"]["count"], 1)
        self.assertAlmostEqual(histograms["cache_lookup_duration"]["sum"], 1.234, places=6)

    def test_a_foreign_invocation_identity_does_not_admit_a_duration(self):
        store = TelemetryStore()
        record = RequestRecord("r1")
        record.set_prompt_tokens(rendered=100, submitted=100)
        invocation = new_invocation_id()
        record.begin_invocation(invocation, ordinal=1)
        verdict = apply_engine(record, {"rid": new_invocation_id(), "matched": 90, "reused": 90,
                                        "evaluated": 10, "lookup_ms": 1234.0},
                               expected_invocation_id=invocation)
        self.assertEqual(verdict["correlation"], "rejected")
        store.add(record.seal("completed", 200))
        histograms = store.summary()["histograms"]
        self.assertEqual(histograms.get("cache_lookup_duration", {}).get("count", 0), 0)

    def test_an_invalid_token_count_does_not_invalidate_a_native_duration(self):
        """The duration is independently trustworthy: a broken token count does not turn it into a guess."""
        store = TelemetryStore()
        record = RequestRecord("r1")
        record.set_prompt_tokens(rendered=100, submitted=100)
        invocation = new_invocation_id()
        record.begin_invocation(invocation, ordinal=1)
        record.invocation_for(invocation).submitted_tokens = 100
        apply_engine(record, {"rid": invocation, "matched": -5, "reused": 90, "evaluated": 10,
                              "lookup_ms": 1234.0}, expected_invocation_id=invocation)
        store.add(record.seal("completed", 200))
        histograms = store.summary()["histograms"]
        self.assertEqual(histograms["cache_lookup_duration"]["count"], 1)

    def test_an_invalid_duration_is_not_observed(self):
        store, record = self._record_with({"matched": 90, "reused": 90, "evaluated": 10, "lookup_ms": -1.0})
        histograms = store.summary()["histograms"]
        self.assertEqual(histograms.get("cache_lookup_duration", {}).get("count", 0), 0)

    def test_a_batch_admission_segment_is_not_admitted_as_the_whole_invocation(self):
        """A slot's admission segment is a diagnostic: its duration never enters the whole-invocation histogram."""
        store, record = self._record_with({"matched": 90, "reused": 90, "evaluated": 10, "lookup_ms": 1234.0},
                                          native_segment_only=True)
        receipt = record.to_dict()["invocations"][0]
        self.assertTrue(receipt["measurement_quality"]["native_partial"])
        self.assertFalse(receipt["measurement_quality"]["admission"][METRIC_NATIVE_DURATION])
        self.assertFalse(receipt["measurement_quality"]["admission"][METRIC_NATIVE_PROMPT_POSITION])
        histograms = store.summary()["histograms"]
        self.assertEqual(histograms.get("cache_lookup_duration", {}).get("count", 0), 0)
        counters = store.summary()["counters"]
        self.assertEqual(counters["prompt_tokens_evaluated"], 0)

    def test_a_fully_correlated_completion_is_admitted(self):
        store, record = self._record_with({"matched": 90, "reused": 90, "evaluated": 10, "work": 10,
                                           "lookup_ms": 5.0})
        receipt = record.to_dict()["invocations"][0]
        self.assertEqual(receipt["measurement_quality"]["accounting"]["state"], "satisfied")
        for metric in (METRIC_NATIVE_PROMPT_POSITION, METRIC_NATIVE_EXECUTION_WORK, METRIC_NATIVE_DURATION,
                       METRIC_COMPLETE_CACHE_RATIO):
            self.assertTrue(receipt["measurement_quality"]["admission"][metric], metric)
        counters = store.summary()["counters"]
        self.assertEqual(counters["prompt_tokens_evaluated"], 10)
        self.assertEqual(counters["requests_reuse_accounted"], 1)

    def test_the_coverage_publishes_both_populations(self):
        """G2c: the eligible population and the missing population are both published."""
        store = TelemetryStore()
        record = RequestRecord("r1")
        record.set_prompt_tokens(rendered=100, submitted=100)
        invocation = new_invocation_id()
        record.begin_invocation(invocation, ordinal=1)
        record.invocation_for(invocation).submitted_tokens = 100
        apply_engine(record, {"rid": invocation, "matched": 90, "reused": 90, "evaluated": 10},
                     expected_invocation_id=invocation)
        store.add(record.seal("completed", 200))
        # a second invocation whose receipt never arrives: the receipt exists, the evidence does not
        lost = RequestRecord("r2")
        lost.set_prompt_tokens(rendered=100, submitted=100)
        lost.begin_invocation(new_invocation_id(), ordinal=1)
        store.add(lost.seal("completed", 200))
        reuse = store.summary()["cache_reuse"]
        self.assertEqual(reuse["eligible_invocations"], 1)
        self.assertEqual(reuse["missing_invocations"], 1)
        self.assertEqual(reuse["invocations"], 2)
        self.assertAlmostEqual(reuse["coverage"], 0.5, places=6)
        self.assertAlmostEqual(reuse["request_coverage"], 0.5, places=6)


class BlockingHandle:
    """A file handle whose write blocks until the witness lets it through."""

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.closed = False

    def write(self, line):
        self.started.set()
        self.release.wait(20)

    def flush(self):
        pass

    def close(self):
        self.closed = True


class EvidenceWriterClosure(unittest.TestCase):
    """G3: the writer's acceptance boundary is atomic and its counter domains are exact."""

    def setUp(self):
        import tempfile
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "e.jsonl"

    def tearDown(self):
        self.folder.cleanup()

    def test_the_detached_pending_records_are_counted_against_the_bound(self):
        """The witness of G3: the worker holds the records it has DETACHED, so they are against the bound."""
        log = EvidenceLog(self.path, queue_size=2)
        handle = BlockingHandle()
        log._handle = handle
        self.assertTrue(log.write({"a": 1}))                  # accepted
        self.assertTrue(log.write({"a": 2}))                  # accepted
        self.assertTrue(handle.started.wait(5))               # the worker took the first record and is blocked
        counters = log.counters()
        self.assertEqual(counters["outstanding_records"], 2)  # both records are held (one detached, one queued)
        self.assertFalse(log.write({"a": 3}))                 # the third one does not fit: it is refused
        counters = log.counters()
        self.assertEqual(counters["accepted_records"], 2)
        self.assertEqual(counters["capacity_refusals"], 1)
        self.assertEqual(counters["outstanding_records"], 2)
        handle.release.set()
        log.close()

    def test_the_counter_domains_conserve(self):
        log = EvidenceLog(self.path, queue_size=4)
        for index in range(3):
            log.write({"a": index})
        log.write({"bad": object()})                          # cannot be serialized: refused
        counters = log.counters()
        self.assertEqual(counters["submitted_records"],
                         counters["accepted_records"] + counters["refused_records"])
        self.assertEqual(counters["accepted_records"],
                         counters["written_records"] + counters["failed_records"]
                         + counters["outstanding_records"])
        self.assertEqual(counters["serialization_refusals"], 1)
        log.close()
        self.assertTrue(log.flush(timeout=5))

    def test_a_submission_that_races_the_shutdown_is_refused(self):
        log = EvidenceLog(self.path, queue_size=4)
        log.write({"a": 1})
        log.close()
        self.assertFalse(log.write({"a": 2}))
        counters = log.counters()
        self.assertEqual(counters["shutdown_refusals"], 1)
        self.assertEqual(counters["accepted_records"], 1)
        self.assertEqual(counters["submitted_records"], 2)

    def test_the_handle_is_closed_after_a_timed_out_shutdown(self):
        """The handle is never closed while the worker may be using it; it is closed when the worker stopped."""
        log = EvidenceLog(self.path, queue_size=4)
        handle = BlockingHandle()
        log._handle = handle
        log.write({"a": 1})
        self.assertTrue(handle.started.wait(5))
        closer = threading.Thread(target=log.close)
        closer.start()
        closer.join(30)
        self.assertFalse(closer.is_alive())
        # the worker was still blocked: the handle was NOT closed under it
        self.assertFalse(handle.closed)
        handle.release.set()
        deadline = time.time() + 10
        while time.time() < deadline and not handle.closed:
            time.sleep(0.02)
        self.assertTrue(handle.closed)


class LifecycleAndBounds(unittest.TestCase):
    """G5: the lifecycle and the boundedness checks."""

    def test_an_unexpected_handler_exception_after_a_200_is_not_a_completed_outcome(self):
        """The production seal: an exception that is still travelling out of the handler is a failure."""
        tok = ByteTokenizer()
        service = _service(MockEngine(tok, "ok"), tok)
        record = service.telemetry_requests.begin(model_id="m")
        data = service.telemetry_requests.finish(record, state="completed", http_status=200)
        self.assertEqual(data["lifecycle"]["state"], "completed")
        # the same production function, told that an exception is on its way out
        record = service.telemetry_requests.begin(model_id="m")
        service.telemetry_requests.finish(record, state="failed", http_status=200)
        sealed = service._seal_telemetry(record, {"outcome": "completed"}, http_status=200, failed=True)
        self.assertIsNone(sealed)                 # the record was already finished: at most one receipt

    def test_the_lifecycle_does_not_depend_on_the_api_monitor(self):
        """The monitor is off: the lifecycle accounting still balances."""
        telemetry = ServerTelemetry()
        telemetry.begin(api="openai")
        summary = telemetry.store.summary()
        self.assertEqual(summary["lifecycle"]["accepted"], 1)
        self.assertEqual(summary["lifecycle"]["completed"], 0)

    def test_a_lost_terminal_receipt_stays_visible_in_the_lifecycle_accounting(self):
        telemetry = ServerTelemetry()
        record = telemetry.begin(api="openai")

        def broken(*args, **kwargs):
            raise RuntimeError("the seal failed")

        record.seal = broken
        with self.assertRaises(RuntimeError):
            telemetry.finish(record, state="completed", http_status=200)
        summary = telemetry.store.summary()
        self.assertEqual(summary["lifecycle"]["accepted"], 1)
        self.assertEqual(summary["lifecycle"]["completed"], 1)
        self.assertEqual(summary["lifecycle"]["receipt_delivery_failures"], 1)

    def test_the_evidence_delivery_loss_is_visible_on_its_own(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "e.jsonl"
            telemetry = ServerTelemetry(evidence_path=path)
            record = telemetry.begin(api="openai")
            # the writer refuses the line: the receipt is in the store, the evidence line is missing
            telemetry.evidence.write = lambda _record: False
            telemetry.finish(record, state="completed", http_status=200)
            summary = telemetry.store.summary()
            self.assertEqual(summary["counters"]["evidence_delivery_failures"], 1)
            self.assertEqual(summary["counters"]["receipt_delivery_failures"], 0)
            self.assertEqual(summary["lifecycle"]["completed"], 1)
            telemetry.close()

    def test_the_retired_engine_instances_are_bounded(self):
        from serve.reqtelemetry.vocabulary import MAX_ENGINE_INSTANCES
        store = TelemetryStore()
        for index in range(MAX_ENGINE_INSTANCES + 20):
            record = RequestRecord(f"r{index}")
            record.engine_instance_id = f"engine-{index}"
            invocation = new_invocation_id()
            record.begin_invocation(invocation, ordinal=1, engine_instance_id=f"engine-{index}")
            apply_engine(record, {"rid": invocation, "evictions": 1}, expected_invocation_id=invocation)
            store.add(record.seal("completed", 200))
        self.assertLessEqual(len(store._evictions_by_engine), MAX_ENGINE_INSTANCES)

    def test_an_unknown_engine_identity_does_not_merge_the_domains(self):
        store = TelemetryStore()
        for evictions in (10, 8, 11):
            record = RequestRecord("r1")
            invocation = new_invocation_id()
            record.begin_invocation(invocation, ordinal=1)
            apply_engine(record, {"rid": invocation, "evictions": evictions}, expected_invocation_id=invocation)
            store.add(record.seal("completed", 200))
        counters = store.summary()["counters"]
        # the engine's identity is unknown: the counter cannot be attributed to a domain
        self.assertEqual(counters["cache_evictions"], 0)
        self.assertEqual(counters["cache_evictions_unattributed"], 29)

    def test_the_cursor_validation_and_the_page_come_from_one_snapshot(self):
        """The cursor's validation and the page it returns describe the same state of the store."""
        from serve.reqtelemetry import encode_cursor
        store = TelemetryStore(max_records=2)
        for index in range(5):
            store.add(RequestRecord(f"r{index}").seal("completed", 200))
        cursor = encode_cursor(1, store.server_instance_id)
        with self.assertRaises(ValueError):
            store.list(cursor=cursor)


class HttpLifecycle(unittest.TestCase):
    """G5: the witnesses that go through the REAL HTTP transport."""

    def setUp(self):
        import json
        import urllib.error
        import urllib.request
        self.json = json
        self.urllib = urllib
        self.tok = ByteTokenizer()
        # the engine breaks AFTER the answer has started: the 200 header is already out
        self.engine = ScriptedEngine(self.tok, ["hello there"], raise_after=2)
        from serve.frontend import ChatTemplate
        from serve.server import serve
        self.svc = Service(self.engine, self.tok, ChatTemplate(ROOT / "serve/chat_template.jinja"))
        self.svc.answer_room = False
        self.httpd = serve(self.svc, port=0)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def _post(self, path, body):
        req = self.urllib.request.Request(self.base + path, data=self.json.dumps(body).encode(),
                                           headers={"Content-Type": "application/json"})
        try:
            with self.urllib.request.urlopen(req, timeout=30) as response:
                return response.status, response.read()
        except self.urllib.error.HTTPError as e:
            with e:
                return e.code, e.read()
        except Exception:                          # the connection broke: the server failed mid-stream
            return None, b""

    def _get(self, path):
        req = self.urllib.request.Request(self.base + path)
        with self.urllib.request.urlopen(req, timeout=30) as response:
            return self.json.loads(response.read())

    def test_an_unexpected_exception_after_the_200_is_a_failed_request(self):
        """G5: the 200 header went out, the handler blew up: the outcome is NOT a completed one."""
        self._post("/v1/chat/completions", {"model": "m", "messages": [{"role": "user", "content": "hi"}],
                                            "stream": True})
        body = self._get("/v1/telemetry/requests")
        self.assertEqual(len(body["records"]), 1)
        record = body["records"][0]
        self.assertEqual(record["lifecycle"]["state"], "failed")
        summary = self.svc.telemetry_requests.store.summary()
        self.assertEqual(summary["lifecycle"]["accepted"], 1)
        self.assertEqual(summary["lifecycle"]["completed"], 0)
        self.assertEqual(summary["lifecycle"]["failed"], 1)

    def test_an_ordinary_request_is_completed_and_has_one_receipt(self):
        """The control: the ordinary request is completed, and it has exactly one receipt."""
        self.engine.raise_after = None
        status, _ = self._post("/v1/chat/completions",
                               {"model": "m", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(status, 200)
        body = self._get("/v1/telemetry/requests")
        self.assertEqual(len(body["records"]), 1)
        record = body["records"][0]
        self.assertEqual(record["lifecycle"]["state"], "completed")
        summary = self.svc.telemetry_requests.store.summary()
        self.assertEqual(summary["lifecycle"]["accepted"], 1)
        self.assertEqual(summary["lifecycle"]["completed"], 1)
        self.assertEqual(summary["lifecycle"]["failed"], 0)
