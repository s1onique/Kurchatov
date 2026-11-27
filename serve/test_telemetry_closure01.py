#!/usr/bin/env python3
"""serve/test_telemetry_closure01.py - the witnesses of ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01.

Every witness here drives the PRODUCTION path and checks a named defect:

    C1   the writer's acceptance boundary is the enqueue
    C2   the coverage denominators are independent of the retained receipts
    C3   every native invocation is terminalized on its own evidence
    C4   the prompt domain is not the prompt's length
    C5   the bounded accounting: the engine's counter domain and the invocation bytes
    D1   the typed measurement admission
    D2   the dispatch identity authority: terminal evidence never creates a dispatch
    D3   the HTTP measurements are admitted on their own terms
    D4   the native terminal record: the finish reason, the budget and the terminal state

    python -m unittest serve.test_telemetry_closure01
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serve.reqtelemetry import (RequestRecord, TelemetryStore, apply_engine, new_invocation_id,  # noqa: E402
                                validate)
from serve.reqtelemetry.vocabulary import MAX_INVOCATION_BYTES  # noqa: E402
from serve.server import ByteTokenizer, MockEngine, Service  # noqa: E402


class ScriptedEngine(MockEngine):
    """A mock engine that reports the figures of a real DONE line and echoes the INVOCATION's id.

    Each dispatch gets its own DONE, with its own figures and its own positional fields (the generated count, the
    prefill and decode time and the native finish reason) - exactly as the real engine writes them.
    """

    def __init__(self, tok, scripts, telemetry_by_call=None, done_by_call=None):
        super().__init__(tok, scripts, max_context=100000)
        self.telemetry_by_call = list(telemetry_by_call or [])
        self.done_by_call = list(done_by_call or [])
        self.calls = 0

    def generate(self, ids, max_new, sampling, cancel, embeddings=None):
        index = self.calls
        self.calls += 1
        rid = getattr(self, "request_id", lambda: None)()
        produced = 0
        try:
            for token in super().generate(ids, max_new, sampling, cancel, embeddings=embeddings):
                produced += 1
                yield token
        finally:
            done = dict(self.done_by_call[index] if index < len(self.done_by_call) else {})
            self.last = {"generated": done.get("generated", produced), "prompt_ms": done.get("prompt_ms", 10.0),
                         "decode_ms": done.get("decode_ms", 20.0), "finish": done.get("finish", "stop")}
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
    import threading
    return list(service.run(ids, thinking, [], max_new, sampling or {}, threading.Event()))


def _two_dispatch_service(tok, figures=None, done=None):
    """A request that dispatches TWICE: the thinking budget wraps the reasoning up and continues."""
    figures = figures or [
        {"matched": 100, "reused": 100, "evaluated": 20, "work": 20, "lookup_ms": 1234.0},
        {"matched": 40, "reused": 40, "evaluated": 60, "work": 60, "lookup_ms": 12.0},
    ]
    done = done or [{"generated": 20, "prompt_ms": 100.0, "decode_ms": 200.0, "finish": "length"},
                    {"generated": 60, "prompt_ms": 30.0, "decode_ms": 40.0, "finish": "stop"}]
    engine = ScriptedEngine(tok, ["<think>" + "thinking about it. " * 200, "the answer."],
                             telemetry_by_call=figures, done_by_call=done)
    return engine, _service(engine, tok)


def _record_with_evidence(invocation, figures, submitted=100, **kw):
    """A record with ONE dispatched invocation and its terminal evidence."""
    rec = RequestRecord("r1")
    rec.set_prompt_tokens(rendered=submitted, submitted=submitted)
    rec.begin_invocation(invocation, ordinal=1)
    rec.invocation_for(invocation).submitted_tokens = submitted
    # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (A2): the DISPATCH BOUNDARY names the prompt
    # domain.  Without a name the invocation is not the request's own prompt domain, and it does not enter the
    # request's prompt coverage.
    rec.invocation_for(invocation).prompt_domain = "request"
    figures = dict(figures)
    figures["rid"] = invocation
    apply_engine(rec, figures, expected_invocation_id=invocation, **kw)
    return rec


class TypedAdmission(unittest.TestCase):
    """D1: a measurement that is not a measurement is never published."""

    def _published(self, figures, generation=None):
        invocation_id = new_invocation_id()
        rec = _record_with_evidence(invocation_id, figures)
        receipt = rec.invocation_for(invocation_id)
        if generation is not None:
            receipt.set_generation(**generation)
        data = rec.to_dict()
        # the strict JSON: a NaN or an infinity must never reach the wire
        json.dumps(data, allow_nan=False)
        return data, data["invocations"][0]

    def test_a_negative_native_duration_is_not_published(self):
        """NEGATIVE_NATIVE_DURATION: a negative duration is not a measurement."""
        data, receipt = self._published({"matched": 90, "reused": 90, "evaluated": 10, "lookup_ms": -1.0})
        self.assertIsNone(receipt["timing_ms"].get("cache_lookup"))
        self.assertIn("timing_ms.cache_lookup", receipt["measurement_quality"]["unavailable_fields"])
        self.assertFalse(receipt["measurement_quality"]["measurement_valid"])
        self.assertEqual(validate(data), [])
        self.assertFalse(data["measurement_quality"]["measurement_valid"])

    def test_a_nonfinite_native_duration_is_not_published(self):
        """NONFINITE_NATIVE_DURATION: NaN is not a duration, and the strict JSON must hold."""
        data, receipt = self._published({"matched": 90, "reused": 90, "evaluated": 10,
                                         "lookup_ms": float("nan")})
        self.assertIsNone(receipt["timing_ms"].get("cache_lookup"))
        self.assertIn("timing_ms.cache_lookup", receipt["measurement_quality"]["unavailable_fields"])
        self.assertEqual(validate(data), [])
        json.dumps(data, allow_nan=False)          # the strict serialization must not raise

    def test_a_negative_generation_count_is_not_published(self):
        """NEGATIVE_GENERATION_COUNT: a negative count is not a count."""
        data, receipt = self._published({"matched": 90, "reused": 90, "evaluated": 10},
                                         generation={"generated": -1})
        self.assertIsNone(receipt["generation"]["generated_tokens"])
        self.assertIn("generation.generated_tokens", receipt["measurement_quality"]["unavailable_fields"])
        self.assertEqual(validate(data), [])

    def test_a_fractional_generation_count_is_not_published(self):
        """FRACTIONAL_GENERATION_COUNT: a fraction is not a count, and it is never rounded into one."""
        data, receipt = self._published({"matched": 90, "reused": 90, "evaluated": 10},
                                         generation={"generated": 2.5})
        self.assertIsNone(receipt["generation"]["generated_tokens"])
        self.assertEqual(validate(data), [])

    def test_a_boolean_generation_count_is_not_published(self):
        """BOOLEAN_GENERATION_COUNT: a bool is not a count."""
        data, receipt = self._published({"matched": 90, "reused": 90, "evaluated": 10},
                                         generation={"generated": True})
        self.assertIsNone(receipt["generation"]["generated_tokens"])
        self.assertEqual(validate(data), [])

    def test_a_negative_eviction_count_is_not_published(self):
        """NEGATIVE_EVICTION_COUNT: a negative cumulative counter is not a counter."""
        data, receipt = self._published({"matched": 90, "reused": 90, "evaluated": 10, "evictions": -2})
        self.assertIsNone(receipt["cache"]["evictions"])
        self.assertIn("cache.evictions", receipt["measurement_quality"]["unavailable_fields"])
        self.assertEqual(validate(data), [])

    def test_an_invalid_restore_duration_is_not_published(self):
        """INVALID_RESTORE_DURATION: an invalid restoration duration is refused."""
        data, receipt = self._published({"matched": 90, "reused": 90, "evaluated": 10, "restore_ms": -5.0})
        self.assertIsNone(receipt["cache"]["restore_ms"])
        self.assertIsNone(receipt["timing_ms"].get("cache_restore"))
        self.assertEqual(validate(data), [])

    def test_the_native_sentinel_of_not_measured_stays_null(self):
        """The engine writes -1 for a counter it did not measure: it is NOT a negative count."""
        data, receipt = self._published({"matched": 90, "reused": 90, "evaluated": 10, "evictions": -1})
        self.assertIsNone(receipt["cache"]["evictions"])
        self.assertEqual(validate(data), [])

    def test_an_invalid_measurement_never_enters_a_total(self):
        """The invalid measurement is excluded from the aggregates, and the valid ones are not."""
        store = TelemetryStore()
        invocation_id = new_invocation_id()
        rec = _record_with_evidence(invocation_id, {"matched": 90, "reused": 90, "evaluated": 10,
                                                    "lookup_ms": -1.0})
        store.add(rec.seal("completed", 200))
        counters = store.summary()["counters"]
        self.assertEqual(counters["prompt_tokens_evaluated"], 10)
        for histogram in store.summary()["histograms"].values():
            self.assertEqual(histogram["count"], 0)

    def test_an_invalid_measurement_does_not_change_the_inference_outcome(self):
        """The telemetry never decides an inference: an invalid measurement is a telemetry problem only."""
        rec = RequestRecord("r1")
        rec.set_native_cache(matched_prefix=90, reused_prefix=90, evaluated=10)
        rec.set_generation(generated=-1)
        rec.set_timing("prefill_wall", -1.0, "native_engine")
        data = rec.seal("completed", 200).to_dict()
        self.assertEqual(data["lifecycle"]["state"], "completed")
        self.assertEqual(data["lifecycle"]["http_status"], 200)


class DispatchIdentity(unittest.TestCase):
    """D2: the dispatch boundary is the only authority that may create a dispatch."""

    def test_an_explicitly_unknown_engine_identity_is_not_inherited(self):
        """EXPLICIT_UNKNOWN_IDENTITY_INHERITED: the preparation identity is not the execution identity."""
        rec = RequestRecord("r1", engine_instance_id="pid-old", model_id="old-model",
                            build_revision="old-build")
        invocation_id = new_invocation_id()
        rec.begin_invocation(invocation_id, ordinal=1, engine_instance_id=None, model_id=None,
                             build_revision=None)
        receipt = rec.invocation_for(invocation_id)
        self.assertIsNone(receipt.engine_instance_id)
        self.assertIsNone(receipt.model_id)
        self.assertIsNone(receipt.build_revision)

    def test_an_omitted_identity_still_falls_back_to_the_record(self):
        """The compatibility path: an argument that is NOT GIVEN falls back to the record's own identity."""
        rec = RequestRecord("r1", engine_instance_id="pid-1", model_id="m", build_revision="b")
        invocation_id = new_invocation_id()
        rec.begin_invocation(invocation_id, ordinal=1)
        receipt = rec.invocation_for(invocation_id)
        self.assertEqual(receipt.engine_instance_id, "pid-1")
        self.assertEqual(receipt.model_id, "m")
        self.assertEqual(receipt.build_revision, "b")

    def test_the_terminal_evidence_of_an_unknown_invocation_creates_no_dispatch(self):
        """TERMINAL_RECEIPT_CREATES_DISPATCH: the terminal path never creates a dispatch."""
        rec = RequestRecord("r1")
        first = new_invocation_id()
        rec.begin_invocation(first, ordinal=1)
        before = rec.invocations_total
        apply_engine(rec, {"rid": new_invocation_id(), "matched": 10, "reused": 10, "evaluated": 5},
                     expected_invocation_id=first)
        self.assertEqual(rec.invocations_total, before)
        self.assertEqual(len(rec.invocations), 1)

    def test_the_terminal_evidence_of_an_evicted_invocation_resurrects_nothing(self):
        """A receipt that did not fit the bounds is not resurrected by a later terminal evidence."""
        rec = RequestRecord("r1")
        ids = [new_invocation_id() for _ in range(12)]
        for index, invocation_id in enumerate(ids):
            rec.begin_invocation(invocation_id, ordinal=index + 1)
        retained = len(rec.invocations)
        dropped = rec.invocations_dropped
        self.assertGreater(dropped, 0)
        evicted = ids[0]                     # the oldest receipt: it was dropped
        self.assertIsNone(rec.invocation_for(evicted))
        before = rec.invocations_total
        apply_engine(rec, {"rid": evicted, "matched": 10, "reused": 10, "evaluated": 5},
                     expected_invocation_id=evicted)
        self.assertEqual(rec.invocations_total, before)
        self.assertEqual(len(rec.invocations), retained)

    def test_a_stale_receipt_does_not_touch_the_running_invocation(self):
        rec = RequestRecord("r1")
        first, second = new_invocation_id(), new_invocation_id()
        rec.begin_invocation(first, ordinal=1)
        rec.begin_invocation(second, ordinal=2)
        verdict = apply_engine(rec, {"rid": first, "matched": 10, "reused": 10, "evaluated": 5},
                                expected_invocation_id=second)
        self.assertEqual(verdict["correlation"], "rejected")
        self.assertFalse(verdict["admitted"])
        self.assertIsNone(rec.invocation_for(second).evaluated_tokens)


class TerminalDuplicates(unittest.TestCase):
    """C3: an accepted terminal receipt is never silently overwritten."""

    def test_an_identical_duplicate_is_ignored(self):
        invocation_id = new_invocation_id()
        figures = {"rid": invocation_id, "matched": 40, "reused": 40, "evaluated": 60, "work": 60}
        rec = RequestRecord("r1")
        rec.begin_invocation(invocation_id, ordinal=1)
        rec.invocation_for(invocation_id).prompt_domain = "request"
        apply_engine(rec, figures, expected_invocation_id=invocation_id)
        store = TelemetryStore()
        apply_engine(rec, dict(figures), expected_invocation_id=invocation_id)
        store.add(rec.seal("completed", 200))
        counters = store.summary()["counters"]
        self.assertEqual(counters["prompt_tokens_evaluated"], 60)
        self.assertEqual(counters["prompt_evaluation_work_tokens"], 60)
        self.assertEqual(counters["native_invocations"], 1)

    def test_a_conflicting_duplicate_is_reported_and_keeps_the_accepted_measurements(self):
        """CONFLICTING_DUPLICATE_TERMINAL_RECEIPT_ACCEPTED: the conflict is explicit evidence."""
        invocation_id = new_invocation_id()
        rec = RequestRecord("r1")
        rec.begin_invocation(invocation_id, ordinal=1)
        apply_engine(rec, {"rid": invocation_id, "matched": 40, "reused": 40, "evaluated": 60},
                     expected_invocation_id=invocation_id)
        verdict = apply_engine(rec, {"rid": invocation_id, "matched": 40, "reused": 40, "evaluated": 90},
                                expected_invocation_id=invocation_id)
        self.assertTrue(verdict.get("conflict"))
        self.assertFalse(verdict["admitted"])
        receipt = rec.invocation_for(invocation_id)
        self.assertEqual(receipt.evaluated_tokens, 60)          # the accepted measurement is kept
        self.assertIn("engine_telemetry", receipt.unavailable)
        self.assertEqual(rec.quality, "instrumentation_error")


class Coverage(unittest.TestCase):
    """C2: the denominators are independent of the retained receipts."""

    def test_a_dropped_receipt_lowers_the_coverage(self):
        store = TelemetryStore()
        rec = RequestRecord("r1")
        rec.set_prompt_tokens(rendered=100, submitted=100)
        for index in range(10):
            invocation_id = new_invocation_id()
            rec.begin_invocation(invocation_id, ordinal=index + 1)
            rec.invocation_for(invocation_id).submitted_tokens = 100
            apply_engine(rec, {"rid": invocation_id, "matched": 90, "reused": 90, "evaluated": 10},
                         expected_invocation_id=invocation_id)
        store.add(rec.seal("completed", 200))
        reuse = store.summary()["cache_reuse"]
        self.assertEqual(reuse["invocations"], 10)
        self.assertEqual(reuse["eligible_invocations"], 8)
        self.assertEqual(reuse["missing_invocations"], 2)
        self.assertAlmostEqual(reuse["coverage"], 0.8, places=6)

    def test_a_lost_terminal_receipt_lowers_the_request_coverage(self):
        """A lost receipt must never improve the coverage."""
        store = TelemetryStore()
        # ONE physical request reached its terminal outcome, but its receipt was LOST: the outcome is counted
        # anyway, so the request stays in the population.
        store.begin_request()
        store.end_request("completed")
        # the SECOND request delivered a receipt with a complete accounting
        rec = _record_with_evidence(new_invocation_id(), {"matched": 90, "reused": 90, "evaluated": 10})
        store.add(rec.seal("completed", 200))
        reuse = store.summary()["cache_reuse"]
        self.assertEqual(reuse["requests_with_complete_accounting"], 1)
        self.assertAlmostEqual(reuse["request_coverage"], 0.5, places=6)


class HttpAuthority(unittest.TestCase):
    """D3: the HTTP-owned counters do not depend on the native accounting."""

    def test_a_broken_native_accounting_does_not_suppress_the_http_counter(self):
        store = TelemetryStore()
        rec = RequestRecord("r1")
        rec.set_prompt_tokens(rendered=100, submitted=100)
        apply_engine(rec, {"rid": "r1", "matched": 100, "reused": 120, "evaluated": 0})
        rec.seal("completed", 200)
        data = rec.to_dict()
        self.assertEqual(data["measurement_quality"]["accounting"]["state"], "violated")
        self.assertTrue(data["measurement_quality"]["admission"]["http"])
        store.add(rec)
        self.assertEqual(store.summary()["counters"]["prompt_tokens_submitted"], 100)


class BoundedAccounting(unittest.TestCase):
    """C5: the engine's counter domain and the invocation bytes."""

    def test_a_retired_engine_is_not_counted_again(self):
        """RETIRED_ENGINE_COUNTER_COUNTED_AGAIN: the same cumulative work is never counted twice."""
        store = TelemetryStore()
        store._count_evictions_locked(store.counters, "A", 10)
        for index in range(64):
            store._count_evictions_locked(store.counters, "E%d" % index, 1)
        self.assertEqual(store.counters["cache_evictions"], 74)
        # the delayed observation of the retired engine: only its DELTA is new work
        store._count_evictions_locked(store.counters, "A", 11)
        self.assertEqual(store.counters["cache_evictions"], 75)

    def test_an_oversized_single_receipt_is_refused(self):
        """OVERSIZED_SINGLE_RECEIPT_ADMITTED: a receipt that cannot fit is refused, not admitted."""
        rec = RequestRecord("r1")
        invocation_id = new_invocation_id()
        rec.begin_invocation(invocation_id, ordinal=1)
        receipt = rec.invocation_for(invocation_id)
        receipt.model_id = "é" * 40000            # a multibyte identifier: big in BYTES
        rec.revalidate_invocation_bytes()
        self.assertEqual(len(rec.invocations), 0)
        self.assertGreaterEqual(rec.invocations_dropped, 1)
        data = rec.to_dict()
        self.assertEqual(data["measurement_quality"]["invocation_count"], 0)
        self.assertGreaterEqual(data["measurement_quality"]["invocations_dropped"], 1)

    def test_the_retained_bytes_stay_inside_the_budget(self):
        """INVOCATION_BYTES_NOT_REVALIDATED: the bound is checked after the terminal measurements."""
        import json
        rec = RequestRecord("r1")
        for index in range(8):
            invocation_id = new_invocation_id()
            rec.begin_invocation(invocation_id, ordinal=index + 1)
        for receipt in rec.invocations:
            receipt.model_id = "é" * 5000          # every receipt grows past the budget
        rec.revalidate_invocation_bytes()
        self.assertLessEqual(rec.invocations_bytes, MAX_INVOCATION_BYTES)
        self.assertLessEqual(len(rec.invocations), 8)
        # the ACTUAL retained size is inside the budget too - the counter is not a promise
        actual = sum(len(json.dumps(receipt.to_dict(), ensure_ascii=False).encode("utf-8"))
                     for receipt in rec.invocations)
        self.assertLessEqual(actual, MAX_INVOCATION_BYTES)

    def test_the_dropped_bytes_are_published(self):
        rec = RequestRecord("r1")
        for index in range(12):
            rec.begin_invocation(new_invocation_id(), ordinal=index + 1)
        data = rec.to_dict()
        self.assertGreaterEqual(data["measurement_quality"]["invocation_dropped_bytes"], 0)
        self.assertGreater(data["measurement_quality"]["invocations_dropped"], 0)


class InvocationTerminalization(unittest.TestCase):
    """C3, D4: every native dispatch is terminalized on its OWN evidence."""

    def setUp(self):
        self.tok = ByteTokenizer()
        self.ids = self.tok.encode("user\nSolve this task\nassistant\n", parse_special=True)

    def _two_invocations(self, figures=None, done=None):
        engine, service = _two_dispatch_service(self.tok, figures=figures, done=done)
        record = service.telemetry_requests.begin(model_id="m")
        service.telemetry_trace.record = record
        _run(service, self.ids, sampling={"reasoning_budget_tokens": 50})
        data = service.telemetry_requests.finish(record, state="completed", http_status=200)
        return engine, data

    def test_the_positional_done_fields_of_every_invocation_are_kept(self):
        """EARLIER_POSITIONAL_DONE_FIELDS_DISCARDED: the earlier invocation keeps ITS OWN DONE fields."""
        engine, data = self._two_invocations()
        self.assertEqual(engine.calls, 2)
        self.assertEqual(len(data["invocations"]), 2)
        first, second = data["invocations"]
        # the cache measurements
        self.assertEqual(first["prompt"]["evaluated_tokens"], 20)
        self.assertEqual(second["prompt"]["evaluated_tokens"], 60)
        # the prefill and the decode each invocation measured
        self.assertEqual(first["timing_ms"]["prefill_wall"], 100.0)
        self.assertEqual(second["timing_ms"]["prefill_wall"], 30.0)
        self.assertEqual(first["timing_ms"]["decode_wall"], 200.0)
        self.assertEqual(second["timing_ms"]["decode_wall"], 40.0)
        # the generated counts
        self.assertEqual(first["generation"]["generated_tokens"], 20)
        self.assertEqual(second["generation"]["generated_tokens"], 60)
        # the NATIVE finish reasons (D4): the first invocation exhausted its budget, the second answered
        self.assertEqual(first["generation"]["finish_reason"], "length")
        self.assertEqual(second["generation"]["finish_reason"], "stop")
        # the terminal states
        self.assertEqual(first["state"], "completed")
        self.assertEqual(second["state"], "completed")
        # the physical HTTP finish reason is NOT the native invocation's finish reason
        self.assertEqual(data["lifecycle"]["finish_reason"], "stop")

    def test_a_field_the_first_reported_and_the_second_omitted_stays_null_in_the_second(self):
        engine, data = self._two_invocations(figures=[
            {"matched": 100, "reused": 100, "evaluated": 20, "work": 20, "lookup_ms": 1234.0},
            {"matched": 40, "reused": 40},
        ])
        first, second = data["invocations"]
        self.assertEqual(first["prompt"]["evaluated_tokens"], 20)
        self.assertIsNone(second["prompt"]["evaluated_tokens"])
        self.assertIsNone(second["timing_ms"].get("cache_lookup"))

    def test_the_effective_output_budget_is_the_dispatch_s_own(self):
        """EFFECTIVE_OUTPUT_BUDGET_WITNESS: the budget of a dispatch is the budget it was given."""
        engine, data = self._two_invocations()
        first, second = data["invocations"]
        self.assertEqual(first["generation"]["requested_max_output_tokens"], 40000)
        self.assertIsNotNone(first["generation"]["effective_max_output_tokens"])
        self.assertIsNotNone(second["generation"]["effective_max_output_tokens"])
        # the continuation had LESS room than the first dispatch
        self.assertLess(second["generation"]["effective_max_output_tokens"],
                        first["generation"]["effective_max_output_tokens"])

    def test_the_two_invocations_keep_their_own_prompt_domains(self):
        """C4: the prompt domain is named by the dispatch boundary, not by the prompt's length."""
        engine, data = self._two_invocations()
        first, second = data["invocations"]
        self.assertEqual(first["prompt"]["domain"], "request")
        # the continuation carries the request's prompt plus what was generated: another domain
        self.assertEqual(second["prompt"]["domain"], "continuation")
        self.assertNotEqual(first["prompt"]["domain"], second["prompt"]["domain"])

    def test_the_invocations_keep_their_own_cache_disposition(self):
        """D6: the disposition is derived from the invocation's own evidence."""
        engine, data = self._two_invocations()
        first, second = data["invocations"]
        self.assertEqual(first["cache"]["disposition"], "full_hit")
        self.assertEqual(second["cache"]["disposition"], "partial_hit")

    def test_no_invocation_is_presented_as_running_at_the_end(self):
        """D4: an invocation whose terminal evidence never arrived is not presented as running."""
        engine, data = self._two_invocations()
        for receipt in data["invocations"]:
            self.assertNotEqual(receipt["state"], "running")
            self.assertIn(receipt["state"], ("completed", "cancelled", "failed", "unknown"))
        # an invocation that never got its evidence says so
        rec = RequestRecord("r1")
        invocation_id = new_invocation_id()
        rec.begin_invocation(invocation_id, ordinal=1)
        sealed = rec.seal("completed", 200).to_dict()
        self.assertEqual(sealed["invocations"][0]["state"], "unknown")
        self.assertIn("terminal_evidence", sealed["invocations"][0]["measurement_quality"]["unavailable_fields"])
        # the request itself is still a completed request: missing telemetry is not an inference failure
        self.assertEqual(sealed["lifecycle"]["state"], "completed")


class PromptDomains(unittest.TestCase):
    """C4: the prompt length is not the prompt's identity."""

    def test_two_different_prompts_of_the_same_length_are_two_domains(self):
        from serve.server import _prompt_domain
        first = [1, 2, 3, 4]
        second = [9, 8, 7, 6]
        self.assertEqual(_prompt_domain(first, first), "request")
        self.assertEqual(_prompt_domain(second, second), "request")
        # the SAME length, but the second prompt is not the request's own prompt: another domain
        self.assertEqual(_prompt_domain(second, first), "other")

    def test_two_invocations_of_the_identical_prompt_are_one_domain(self):
        from serve.server import _prompt_domain
        prompt = [1, 2, 3, 4]
        self.assertEqual(_prompt_domain(prompt, prompt), "request")
        self.assertEqual(_prompt_domain(prompt, prompt), "request")

    def test_a_continuation_is_another_domain(self):
        from serve.server import _prompt_domain
        prompt = [1, 2, 3, 4]
        self.assertEqual(_prompt_domain(prompt + [5, 6], prompt), "continuation")

    def test_an_unavailable_prompt_length_keeps_the_null_semantics(self):
        """A prompt length that was not measured stays null - it is not a measured zero."""
        rec = RequestRecord("r1")
        invocation_id = new_invocation_id()
        rec.begin_invocation(invocation_id, ordinal=1)
        receipt = rec.invocation_for(invocation_id)
        self.assertIsNone(receipt.submitted_tokens)
        receipt.submitted_tokens = 100
        self.assertIsNone(receipt.prompt_domain)      # not named: it is unknown, not "request"


if __name__ == "__main__":
    unittest.main()
