"""serve/test_telemetry_amendment01.py - the witnesses of
ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (A1, A2, A3, A4, A5b).

Every witness here uses the PRODUCTION path: the dispatch boundary creates the invocation receipt and names its
prompt domain, and the engine's terminal evidence arrives through apply_engine.  The witnesses assert the
AGGREGATE counters and the POPULATION identities - never only the helper that classifies a domain.

The non-vacuity (the reversal of each correction) is in tools/test_telemetry_amendment01_mutations.py.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from serve.reqtelemetry import (RequestRecord, ServerTelemetry, TelemetryStore, apply_engine, new_invocation_id)


def _dispatched(record, ordinal=1, domain="request", submitted=100):
    """ONE native dispatch of `record`: the receipt, bound before the dispatch, with its prompt domain named."""
    invocation = new_invocation_id()
    record.begin_invocation(invocation, ordinal=ordinal)
    receipt = record.invocation_for(invocation)
    receipt.submitted_tokens = submitted
    receipt.prompt_domain = domain
    return invocation


def _evidence(invocation, **figures):
    """The engine's terminal evidence for one dispatch."""
    payload = {"rid": invocation}
    payload.update(figures)
    return payload


class DispatchPopulation(unittest.TestCase):
    """A1: the native dispatch population does not depend on the receipt's storage."""

    def test_a_lost_parent_receipt_keeps_the_native_dispatch_population(self):
        """LOST_PARENT_RECEIPT_REMOVES_NATIVE_DISPATCH_POPULATION: the population is the DISPATCHES."""
        tel = ServerTelemetry()
        # the first request: its receipt cannot be sealed (a failed seal)
        lost = tel.begin(api="openai", client_request_id="one", model_id="m")
        lost.set_prompt_tokens(rendered=100, submitted=100)
        invocation = _dispatched(lost)
        apply_engine(lost, _evidence(invocation, matched=90, reused=90, evaluated=10, work=10),
                     expected_invocation_id=invocation)

        def failing_seal(*args, **kwargs):
            raise RuntimeError("the seal failed")

        lost.seal = failing_seal
        with self.assertRaises(RuntimeError):
            tel.finish(lost, state="completed", http_status=200, finish_reason="stop")
        # the second request: it completes normally
        kept = tel.begin(api="openai", client_request_id="two", model_id="m")
        kept.set_prompt_tokens(rendered=100, submitted=100)
        invocation = _dispatched(kept)
        apply_engine(kept, _evidence(invocation, matched=90, reused=90, evaluated=10, work=10),
                     expected_invocation_id=invocation)
        tel.finish(kept, state="completed", http_status=200, finish_reason="stop")
        reuse = tel.store.summary()["cache_reuse"]
        # the population: both dispatches
        self.assertEqual(reuse["requests"], 2)
        self.assertEqual(reuse["invocations"], 2)
        # the evidence: one invocation was accounted, the other is missing
        self.assertEqual(reuse["eligible_invocations"], 1)
        self.assertEqual(reuse["missing_invocations"], 1)
        # both coverages fall, they do not improve
        self.assertEqual(reuse["request_coverage"], 0.5)
        self.assertEqual(reuse["coverage"], 0.5)

    def test_a_failed_store_does_not_shrink_the_population(self):
        """A failed store operation is a lost receipt, not a smaller population."""
        tel = ServerTelemetry()
        record = tel.begin(api="openai", model_id="m")
        record.set_prompt_tokens(rendered=100, submitted=100)
        invocation = _dispatched(record)
        apply_engine(record, _evidence(invocation, matched=90, reused=90, evaluated=10, work=10),
                     expected_invocation_id=invocation)
        original = tel.store.add

        def failing_add(_record):
            raise RuntimeError("the store failed")

        tel.store.add = failing_add
        with self.assertRaises(RuntimeError):
            tel.finish(record, state="completed", http_status=200, finish_reason="stop")
        tel.store.add = original
        reuse = tel.store.summary()["cache_reuse"]
        self.assertEqual(reuse["invocations"], 1)
        self.assertEqual(reuse["missing_invocations"], 1)
        self.assertEqual(reuse["eligible_invocations"], 0)
        self.assertEqual(reuse["coverage"], 0.0)

    def test_a_running_request_is_not_in_the_population_yet(self):
        """A request that is still running has no terminal outcome: its dispatches are not counted yet."""
        tel = ServerTelemetry()
        record = tel.begin(api="openai", model_id="m")
        record.set_prompt_tokens(rendered=100, submitted=100)
        _dispatched(record)
        self.assertEqual(tel.store.summary()["cache_reuse"]["invocations"], 0)
        self.assertEqual(tel.inflight(), 1)


class PromptDomainConservation(unittest.TestCase):
    """A2: the request's own prompt coverage is counted ONCE, and never summed."""

    def _store_with(self, *invocations):
        """A store with ONE request that dispatched the given (domain, figures) pairs."""
        store = TelemetryStore()
        record = RequestRecord("r1")
        record.set_prompt_tokens(rendered=100, submitted=100)
        for index, (domain, submitted, figures) in enumerate(invocations, start=1):
            invocation = _dispatched(record, ordinal=index, domain=domain, submitted=submitted)
            apply_engine(record, _evidence(invocation, **figures), expected_invocation_id=invocation)
        store.add(record.seal("completed", 200, finish_reason="stop"))
        return store

    def test_the_same_prompt_dispatched_twice_is_not_counted_twice(self):
        """REPEATED_REQUEST_PROMPT_POSITIONS_ACCUMULATED: the same prompt twice is ONE coverage."""
        store = self._store_with(("request", 100, {"matched": 90, "reused": 90, "evaluated": 10, "work": 10}),
                                 ("request", 100, {"matched": 90, "reused": 90, "evaluated": 10, "work": 10}))
        counters = store.summary()["counters"]
        # the request's own prompt coverage: NOT 20, and NOT 180 - the prompt was executed twice
        self.assertEqual(counters["prompt_tokens_evaluated"], 0)
        self.assertEqual(counters["prompt_tokens_reused"], 0)
        self.assertEqual(counters["prompt_tokens_submitted"], 100)
        # the cumulative native work: both invocations, every time
        self.assertEqual(counters["native_positions_evaluated_total"], 20)
        self.assertEqual(counters["native_positions_reused_total"], 180)
        # the request-level coverage is UNAVAILABLE, and it says so
        self.assertEqual(counters["requests_with_ambiguous_prompt_coverage"], 1)

    def test_two_measurements_of_the_same_prompt_do_not_accumulate(self):
        """The same prompt with DIFFERENT measurements is still one prompt."""
        store = self._store_with(("request", 100, {"matched": 90, "reused": 90, "evaluated": 10, "work": 10}),
                                 ("request", 100, {"matched": 50, "reused": 50, "evaluated": 50, "work": 50}))
        counters = store.summary()["counters"]
        self.assertEqual(counters["prompt_tokens_evaluated"], 0)
        self.assertEqual(counters["prompt_tokens_reused"], 0)
        self.assertEqual(counters["native_positions_evaluated_total"], 60)
        self.assertEqual(counters["native_positions_reused_total"], 140)
        self.assertEqual(counters["requests_with_ambiguous_prompt_coverage"], 1)

    def test_two_prompts_of_the_same_length_are_two_domains(self):
        """The LENGTH is not the identity: the request's own domain is the one the dispatch boundary named."""
        store = self._store_with(("request", 100, {"matched": 90, "reused": 90, "evaluated": 10, "work": 10}),
                                 ("other", 40, {"matched": 40, "reused": 0, "evaluated": 40, "work": 40}))
        counters = store.summary()["counters"]
        # the request's own prompt coverage: the ONE invocation that carried the request's prompt
        self.assertEqual(counters["prompt_tokens_evaluated"], 10)
        self.assertEqual(counters["prompt_tokens_reused"], 90)
        # the other domain's positions are work, published apart
        self.assertEqual(counters["native_positions_evaluated_total"], 50)
        self.assertEqual(counters["native_positions_reused_total"], 90)
        self.assertEqual(counters["requests_with_ambiguous_prompt_coverage"], 0)

    def test_an_unknown_prompt_domain_is_not_the_request_s_own(self):
        """UNKNOWN_PROMPT_DOMAIN_ADMITTED_AS_REQUEST: an unnamed domain is never the request's own."""
        store = self._store_with((None, 100, {"matched": 90, "reused": 90, "evaluated": 10, "work": 10}),)
        counters = store.summary()["counters"]
        self.assertEqual(counters["prompt_tokens_evaluated"], 0)
        self.assertEqual(counters["prompt_tokens_reused"], 0)
        # the cumulative work is still counted
        self.assertEqual(counters["native_positions_evaluated_total"], 10)
        # and it is not in the eligible population of the request's coverage either
        self.assertEqual(counters["requests_with_complete_accounting"], 0)

    def test_a_reasoning_continuation_is_not_the_request_s_own_prompt(self):
        """A CONTINUATION carries the request's prompt plus what was generated: it is another domain."""
        store = self._store_with(("request", 100, {"matched": 90, "reused": 90, "evaluated": 10, "work": 10}),
                                 ("continuation", 120, {"matched": 120, "reused": 110, "evaluated": 10, "work": 10}))
        counters = store.summary()["counters"]
        self.assertEqual(counters["prompt_tokens_evaluated"], 10)
        self.assertEqual(counters["prompt_tokens_reused"], 90)
        self.assertEqual(counters["native_positions_evaluated_total"], 20)
        self.assertEqual(counters["native_positions_reused_total"], 200)

    def test_the_invocation_weighted_ratio_may_hold_both_invocations(self):
        """The ratio's numerator and denominator come from the SAME population: the invocations."""
        store = self._store_with(("request", 100, {"matched": 90, "reused": 90, "evaluated": 10, "work": 10}),
                                 ("request", 100, {"matched": 90, "reused": 90, "evaluated": 10, "work": 10}))
        reuse = store.summary()["cache_reuse"]
        self.assertEqual(reuse["eligible_invocations"], 2)
        self.assertEqual(reuse["reused_tokens"], 180)
        self.assertEqual(reuse["submitted_tokens"], 200)
        self.assertAlmostEqual(reuse["ratio"], 0.9, places=6)


class ImmutableTerminalEvidence(unittest.TestCase):
    """A3: the terminal evidence of an invocation is committed ONCE and never overwritten."""

    def _accepted(self, **figures):
        """A record with ONE dispatch whose terminal evidence was already accepted."""
        record = RequestRecord("r1")
        record.set_prompt_tokens(rendered=100, submitted=100)
        invocation = _dispatched(record)
        apply_engine(record, _evidence(invocation, **figures), expected_invocation_id=invocation)
        return record, invocation

    def test_an_identical_duplicate_updates_nothing(self):
        """PARTIAL_PAYLOAD_DUPLICATE_COMPARISON: the comparison covers the COMPLETE evidence."""
        record, invocation = self._accepted(matched=90, reused=90, evaluated=10, work=10, lookup_ms=12.0)
        receipt = record.invocation_for(invocation)
        before = receipt.to_dict()
        verdict = apply_engine(record, _evidence(invocation, matched=90, reused=90, evaluated=10, work=10,
                                                 lookup_ms=12.0),
                               expected_invocation_id=invocation)
        self.assertTrue(verdict.get("duplicate"))
        self.assertTrue(verdict.get("admitted"))
        self.assertEqual(receipt.to_dict(), before)
        self.assertEqual(receipt.correlation, "verified")

    def test_a_duplicate_with_a_changed_duration_is_a_conflict(self):
        """The durations are part of the terminal evidence, not only the token counters."""
        record, invocation = self._accepted(matched=90, reused=90, evaluated=10, work=10, lookup_ms=12.0)
        receipt = record.invocation_for(invocation)
        verdict = apply_engine(record, _evidence(invocation, matched=90, reused=90, evaluated=10, work=10,
                                                 lookup_ms=999.0),
                               expected_invocation_id=invocation)
        self.assertTrue(verdict.get("conflict"))
        self.assertFalse(verdict.get("admitted"))
        self.assertEqual(receipt.timing.get("cache_lookup"), 12.0)
        self.assertEqual(receipt.correlation, "verified")

    def test_a_duplicate_with_changed_positional_durations_is_a_conflict(self):
        """The POSITIONAL DONE fields are part of the terminal evidence too."""
        record = RequestRecord("r1")
        record.set_prompt_tokens(rendered=100, submitted=100)
        invocation = _dispatched(record)
        apply_engine(record, _evidence(invocation, matched=90, reused=90, evaluated=10, work=10),
                     expected_invocation_id=invocation,
                     positional={"prompt_ms": 11.0, "decode_ms": 22.0, "generated": 5, "finish": "stop"},
                     native_state="completed")
        receipt = record.invocation_for(invocation)
        verdict = apply_engine(record, _evidence(invocation, matched=90, reused=90, evaluated=10, work=10),
                               expected_invocation_id=invocation,
                               positional={"prompt_ms": 99.0, "decode_ms": 22.0, "generated": 5, "finish": "stop"},
                               native_state="completed")
        self.assertTrue(verdict.get("conflict"))
        self.assertEqual(receipt.timing.get("prefill_wall"), 11.0)

    def test_a_duplicate_with_a_changed_generation_count_is_a_conflict(self):
        record = RequestRecord("r1")
        record.set_prompt_tokens(rendered=100, submitted=100)
        invocation = _dispatched(record)
        apply_engine(record, _evidence(invocation, matched=90, reused=90, evaluated=10, work=10),
                     expected_invocation_id=invocation,
                     positional={"generated": 5, "finish": "stop"}, native_state="completed")
        receipt = record.invocation_for(invocation)
        verdict = apply_engine(record, _evidence(invocation, matched=90, reused=90, evaluated=10, work=10),
                               expected_invocation_id=invocation,
                               positional={"generated": 6, "finish": "stop"}, native_state="completed")
        self.assertTrue(verdict.get("conflict"))
        self.assertEqual(receipt.generated_tokens, 5)

    def test_a_duplicate_with_a_changed_restoration_outcome_is_a_conflict(self):
        record, invocation = self._accepted(matched=90, reused=90, evaluated=10, work=10,
                                            restore="succeeded", restore_ms=3.0)
        receipt = record.invocation_for(invocation)
        verdict = apply_engine(record, _evidence(invocation, matched=90, reused=90, evaluated=10, work=10,
                                                 restore="failed", restore_ms=3.0),
                               expected_invocation_id=invocation)
        self.assertTrue(verdict.get("conflict"))
        self.assertEqual(receipt.cache_restore_succeeded, True)

    def test_a_foreign_receipt_after_the_accepted_one_keeps_the_accepted_receipt(self):
        """FOREIGN_DUPLICATE_MUTATES_ACCEPTED_RECEIPT: the accepted snapshot is not touched."""
        record, invocation = self._accepted(matched=90, reused=90, evaluated=10, work=10)
        receipt = record.invocation_for(invocation)
        verdict = apply_engine(record, {"rid": "another-invocation", "matched": 90, "reused": 90,
                                        "evaluated": 10, "work": 10},
                               expected_invocation_id=invocation)
        self.assertTrue(verdict.get("conflict"))
        self.assertTrue(verdict.get("foreign"))
        self.assertFalse(verdict.get("admitted"))
        # the accepted receipt keeps its correlation and its measurements
        self.assertEqual(receipt.correlation, "verified")
        self.assertEqual(receipt.evaluated_tokens, 10)

    def test_a_compatibility_receipt_is_outside_the_dispatched_population(self):
        """A receipt built WITHOUT a dispatch is explicit, and it is not native evidence."""
        record = RequestRecord("r1")
        record.set_prompt_tokens(rendered=100, submitted=100)
        apply_engine(record, {"rid": "never-dispatched", "matched": 90, "reused": 90, "evaluated": 10,
                              "work": 10})
        receipt = record.invocations[0]
        self.assertTrue(receipt.synthetic)
        self.assertEqual(record.invocations_total, 0)
        data = record.seal("completed", 200, finish_reason="stop").to_dict()
        self.assertTrue(data["invocations"][0]["measurement_quality"]["compatibility_receipt"])
        store = TelemetryStore()
        store.add(record.seal("completed", 200, finish_reason="stop"))
        counters = store.summary()["counters"]
        self.assertEqual(counters["native_invocations"], 0)
        self.assertEqual(counters["native_invocations_accounted"], 0)
        self.assertEqual(counters["native_invocations_missing"], 0)
        self.assertEqual(counters["prompt_tokens_evaluated"], 0)

    def test_an_invocation_without_native_evidence_is_unknown(self):
        """Unavailable native outcomes remain unknown."""
        record = RequestRecord("r1")
        record.set_prompt_tokens(rendered=100, submitted=100)
        _dispatched(record)
        data = record.seal("completed", 200, finish_reason="stop").to_dict()
        self.assertEqual(data["invocations"][0]["state"], "unknown")


class EngineCounterDomain(unittest.TestCase):
    """A4: a forgotten engine identity is never a new one."""

    def test_a_forgotten_engine_counter_is_not_counted_again(self):
        """FORGOTTEN_ENGINE_COUNTER_COUNTED_AGAIN: the work that was counted is not counted twice."""
        from serve.reqtelemetry.vocabulary import MAX_ENGINE_INSTANCES
        store = TelemetryStore()
        counters = store.counters
        for index in range(MAX_ENGINE_INSTANCES * 3 + 1):
            store._count_evictions_locked(counters, "engine-%d" % index, 10)
        before = counters["cache_evictions"]
        self.assertEqual(before, (MAX_ENGINE_INSTANCES * 3 + 1) * 10)
        # a FORGOTTEN engine: its identity is in none of the bounded collections
        forgotten = None
        for index in range(MAX_ENGINE_INSTANCES * 3 + 1):
            name = "engine-%d" % index
            if (name not in store._evictions_by_engine and name not in store._retired_evictions
                    and name not in store._unattributable_engines):
                forgotten = name
                break
        self.assertIsNotNone(forgotten, "an engine identity was forgotten by the bounded state")
        # its DELAYED cumulative counter arrives
        store._count_evictions_locked(counters, forgotten, 11)
        after = counters["cache_evictions"]
        # the work that was already counted is not counted again: the delta is recovered exactly, or the
        # observation is refused - never the whole counter
        self.assertIn(after - before, (0, 1))
        self.assertLess(after - before, 11)

    def test_the_accepted_delayed_observation_still_recovers_its_delta(self):
        """The accepted 74 -> 75 witness of the closure-01 still holds."""
        store = TelemetryStore()
        counters = store.counters
        store._count_evictions_locked(counters, "A", 10)
        for index in range(64):
            store._count_evictions_locked(counters, "E%d" % index, 1)
        self.assertEqual(counters["cache_evictions"], 74)
        store._count_evictions_locked(counters, "A", 11)
        self.assertEqual(counters["cache_evictions"], 75)


class RetentionIntegrity(unittest.TestCase):
    """A5b: a discarded receipt leaves no stale measurement on its parent."""

    def test_a_dropped_sole_invocation_clears_the_parent_mirror(self):
        """DROPPED_INVOCATION_PARENT_MIRROR_SURVIVES: the parent's native fields are cleared."""
        import serve.reqtelemetry.record as record_module
        record = RequestRecord("r1")
        record.set_prompt_tokens(rendered=100, submitted=100)
        invocation = _dispatched(record)
        apply_engine(record, _evidence(invocation, matched=90, reused=90, evaluated=10, work=10),
                     expected_invocation_id=invocation)
        self.assertEqual(record.reused_prefix_tokens, 90)
        self.assertEqual(record.evaluated_tokens, 10)
        # the receipt does not fit in the record's bounds: it is discarded
        original = record_module.MAX_INVOCATION_BYTES
        try:
            record_module.MAX_INVOCATION_BYTES = 16
            record.revalidate_invocation_bytes()
        finally:
            record_module.MAX_INVOCATION_BYTES = original
        self.assertEqual(len(record.invocations), 0)
        self.assertEqual(record.invocations_dropped, 1)
        # the parent's mirrored native measurements are GONE
        self.assertIsNone(record.reused_prefix_tokens)
        self.assertIsNone(record.evaluated_tokens)
        self.assertIsNone(record.matched_prefix_tokens)
        # the HTTP-owned fields stay
        self.assertEqual(record.submitted_tokens, 100)
        data = record.seal("completed", 200, finish_reason="stop").to_dict()
        self.assertIsNone(data["prompt"]["reused_prefix_tokens"])
        self.assertEqual(data["prompt"]["submitted_tokens"], 100)


class NativeOutcomeAuthority(unittest.TestCase):
    """A3b: the native outcome of a dispatch is the NATIVE dispatch's own.

    These witnesses exercise the ACTUAL production dispatch and terminal processing path: the same dispatch loop
    and the same finalizer the HTTP handler runs.
    """

    def setUp(self):
        from serve.server import ByteTokenizer
        self.tok = ByteTokenizer()
        self.ids = self.tok.encode("user\nSolve this task\nassistant\n", parse_special=True)

    def _service(self, done=None):
        from serve.test_telemetry_closure01 import _two_dispatch_service
        return _two_dispatch_service(self.tok, done=done)

    def test_a_failed_native_invocation_stays_failed_when_the_request_recovers(self):
        """NATIVE_OUTCOME_INFERRED_FROM_HTTP_OUTCOME: the earlier dispatch failed, and it stays failed."""
        from serve.test_telemetry_closure01 import _run
        done = [{"generated": 20, "prompt_ms": 100.0, "decode_ms": 200.0, "finish": "error"},
                {"generated": 60, "prompt_ms": 30.0, "decode_ms": 40.0, "finish": "stop"}]
        engine, service = self._service(done=done)
        record = service.telemetry_requests.begin(model_id="m")
        service.telemetry_trace.record = record
        _run(service, self.ids, sampling={"reasoning_budget_tokens": 50})
        data = service.telemetry_requests.finish(record, state="completed", http_status=200)
        first, second = data["invocations"]
        self.assertEqual(first["state"], "failed")
        self.assertEqual(second["state"], "completed")
        # the request itself completed: the recovery worked
        self.assertEqual(data["lifecycle"]["state"], "completed")

    def test_a_completed_native_invocation_stays_completed_when_the_delivery_fails(self):
        """The HTTP outcome does not rewrite the native outcome."""
        from serve.test_telemetry_closure01 import _run
        engine, service = self._service()
        record = service.telemetry_requests.begin(model_id="m")
        service.telemetry_trace.record = record
        _run(service, self.ids, sampling={"reasoning_budget_tokens": 50})
        # the HTTP delivery fails AFTER the engine answered
        sealed = service._seal_telemetry(record, record={"http_status": 200}, failed=True)
        self.assertEqual(sealed["lifecycle"]["state"], "failed")
        for receipt in sealed["invocations"]:
            self.assertEqual(receipt["state"], "completed")


class HttpSerialization(unittest.TestCase):
    """A5a: the telemetry's HTTP boundary writes STRICT JSON."""

    def setUp(self):
        import json
        import urllib.error
        import urllib.request
        from serve.frontend import ChatTemplate
        from serve.server import ByteTokenizer, MockEngine, Service, serve
        self.json = json
        self.urllib = (urllib.request, urllib.error)
        root = Path(__file__).resolve().parents[1]
        self.tok = ByteTokenizer()
        self.engine = MockEngine(self.tok, ["the answer."], max_context=100000)
        self.svc = Service(self.engine, self.tok, ChatTemplate(root / "serve/chat_template.jinja"))
        self.httpd = serve(self.svc, port=0)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def _get(self, path):
        request, error = self.urllib
        try:
            with request.urlopen(self.base + path, timeout=30) as response:
                return response.status, response.read()
        except error.HTTPError as e:
            with e:
                return e.code, e.read()

    def _strict(self, raw):
        """Parse the response bytes with a STRICT reader: a bare NaN or Infinity is an error."""
        def refuse(name):
            raise ValueError(f"the body carries a {name}: it is not JSON")

        return self.json.loads(raw.decode("utf-8"), parse_constant=refuse)

    def _populate(self):
        """A real record, through the production lifecycle."""
        from serve.reqtelemetry import apply_engine, new_invocation_id
        tel = self.svc.telemetry_requests
        record = tel.begin(api="openai", client_request_id="abc", model_id="m")
        record.set_prompt_tokens(rendered=100, submitted=100)
        invocation = new_invocation_id()
        record.begin_invocation(invocation, ordinal=1)
        record.invocation_for(invocation).submitted_tokens = 100
        record.invocation_for(invocation).prompt_domain = "request"
        apply_engine(record, {"rid": invocation, "matched": 90, "reused": 90, "evaluated": 10, "work": 10},
                     expected_invocation_id=invocation)
        tel.finish(record, state="completed", http_status=200, finish_reason="stop")
        return record.request_id

    def test_the_http_boundary_writes_strict_json(self):
        """A non-finite value is refused at the telemetry's HTTP boundary."""
        request_id = self._populate()
        for path in ("/v1/telemetry/status", "/v1/telemetry/summary", "/v1/telemetry/requests",
                     f"/v1/telemetry/requests/{request_id}"):
            status, raw = self._get(path)
            self.assertEqual(status, 200, path)
            self._strict(raw)          # the strict reader accepts the body
        # the inference is not touched by the telemetry
        body = self.json.dumps({"model": "test", "messages": [{"role": "user", "content": "hi"}],
                                "max_tokens": 8, "stream": False}).encode()
        req = self.urllib[0].Request(self.base + "/v1/chat/completions", data=body,
                                     headers={"Content-Type": "application/json"})
        with self.urllib[0].urlopen(req, timeout=60) as response:
            self.assertEqual(response.status, 200)
        # now a NON-FINITE value at the telemetry's serialization boundary
        store = self.svc.telemetry_requests.store
        with store.lock:
            data = store.records[0][1]
            data["timing_ms"]["prefill_wall"] = float("nan")
        status, raw = self._get(f"/v1/telemetry/requests/{request_id}")
        # the answer is a proper JSON answer: the body never carries a bare NaN
        self._strict(raw)
        self.assertIn(status, (200, 500))
        if status == 500:
            self.assertIn("telemetry_serialization_error", raw.decode("utf-8"))
        # and the inference still works after the refusal
        with self.urllib[0].urlopen(req, timeout=60) as response:
            self.assertEqual(response.status, 200)
