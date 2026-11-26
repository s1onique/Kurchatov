#!/usr/bin/env python3
"""serve/test_telemetry_integrity.py - the measurement-integrity witnesses of
ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-01 (G1, G2, G3, G4, G5, G6, G7).

These tests use the PRODUCTION exporter (serve/prometheus.py), the PRODUCTION store (serve/reqtelemetry/) and the
PRODUCTION HTTP handlers: a syntactically valid scrape is not enough - the numbers in it are checked.

  * G1: the duration histograms are real cumulative buckets, in seconds (the milliseconds are converted once);
  * G2: the native receipt is bound to the request that asked for it;
  * G3: a null is not a zero, and the conservation identity is checked, never repaired;
  * G4: the canonical fields are written where the quantity is measured;
  * G5: one authoritative terminal finalization per accepted physical HTTP request;
  * G7: the HTTP contract validates its inputs.
"""
from __future__ import annotations

import base64
import json
import math
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serve import prometheus  # noqa: E402
from serve.frontend import ChatTemplate  # noqa: E402
from serve.reqtelemetry import (DURATION_BUCKETS, INSTRUMENTATION_ERROR, PARTIAL, RequestRecord,  # noqa: E402
                                ServerTelemetry, TelemetryStore, apply_engine, encode_cursor)
from serve.server import ByteTokenizer, MockEngine, Service, serve  # noqa: E402

CTX = 4096


def _record(store, **timings):
    """One finished record with the given timings (milliseconds), added to the store."""
    rec = RequestRecord(request_id=f"r{store.seq + 1}")
    for name, ms in timings.items():
        rec.set_timing(name, ms, "http_server")
    rec.seal(state="completed", http_status=200, finish_reason="stop")
    store.add(rec)
    return rec


def _scrape(store) -> str:
    """The production Prometheus text for a store's telemetry."""
    summary = store.summary()
    summary["inflight"] = 0
    summary["enabled"] = True
    metrics = {"engine": {"model": "test"}, "live": {}, "totals": {}, "hardware": {}, "requests": [],
               "telemetry": summary}
    lat = {"ttft": ([0] * len(prometheus.BUCKETS), 0.0, 0),
           "itl": ([0] * len(prometheus.BUCKETS), 0.0, 0),
           "e2e": ([0] * len(prometheus.BUCKETS), 0.0, 0)}
    return prometheus.render(metrics, lat)


def _bucket(text: str, name: str, edge: str) -> int:
    """The value of one histogram bucket line of the scrape.

    ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-02 (A8): the canonical telemetry metrics are PROCESS-SCOPED:
    they carry no model_name label, because a process-lifetime total does not belong to the model that happens to
    be selected when the scrape happens.
    """
    for prefix in (f"{name}_bucket{{le=\"{edge}\"}}", f"{name}_bucket{{model_name=\"test\",le=\"{edge}\"}}"):
        for line in text.splitlines():
            if line.startswith(prefix + " "):
                return int(line.rsplit(" ", 1)[1])
    raise AssertionError(f"the scrape has no {name}_bucket for {edge}")


class HistogramIntegrity(unittest.TestCase):
    """G1: the histogram distribution and the unit."""

    def test_the_mandatory_witness(self):
        """The amendment's witness: 2000 ms, 20000 ms and 120000 ms are 2 s, 20 s and 120 s."""
        store = TelemetryStore()
        _record(store, total=2000)
        _record(store, total=20000)
        _record(store, total=120000)
        text = _scrape(store)
        self.assertEqual(_bucket(text, "strata_request_duration_seconds", "0.001"), 0)
        self.assertEqual(_bucket(text, "strata_request_duration_seconds", "1.0"), 0)
        self.assertEqual(_bucket(text, "strata_request_duration_seconds", "2.5"), 1)
        self.assertEqual(_bucket(text, "strata_request_duration_seconds", "5.0"), 1)
        self.assertEqual(_bucket(text, "strata_request_duration_seconds", "30.0"), 2)
        self.assertEqual(_bucket(text, "strata_request_duration_seconds", "120.0"), 3)
        self.assertEqual(_bucket(text, "strata_request_duration_seconds", "+Inf"), 3)
        self.assertIn("strata_request_duration_seconds_sum 142.0", text)
        self.assertIn("strata_request_duration_seconds_count 3", text)

    def test_no_bucket_claims_an_observation_that_did_not_happen(self):
        """The old exporter gave every bucket the total count: a long observation appeared in the small buckets too.

        A cumulative bucket says how many observations were at or below that edge, so a 120 s observation is in the
        120 s bucket and in +Inf - and NOT in the 1 s or the 30 s bucket.
        """
        store = TelemetryStore()
        _record(store, total=120000)                   # 120 s
        text = _scrape(store)
        self.assertEqual(_bucket(text, "strata_request_duration_seconds", "0.001"), 0)
        self.assertEqual(_bucket(text, "strata_request_duration_seconds", "1.0"), 0)
        self.assertEqual(_bucket(text, "strata_request_duration_seconds", "30.0"), 0)
        self.assertEqual(_bucket(text, "strata_request_duration_seconds", "120.0"), 1)
        self.assertEqual(_bucket(text, "strata_request_duration_seconds", "+Inf"), 1)

    def test_an_exact_boundary_lands_in_its_own_bucket(self):
        store = TelemetryStore()
        _record(store, total=2500)                      # exactly 2.5 s
        text = _scrape(store)
        self.assertEqual(_bucket(text, "strata_request_duration_seconds", "2.5"), 1)
        self.assertEqual(_bucket(text, "strata_request_duration_seconds", "10.0"), 1)

    def test_a_measured_zero_is_observed(self):
        store = TelemetryStore()
        _record(store, total=0)
        text = _scrape(store)
        self.assertEqual(_bucket(text, "strata_request_duration_seconds", "0.001"), 1)
        self.assertIn("strata_request_duration_seconds_sum 0.0", text)

    def test_a_missing_duration_is_not_observed_at_all(self):
        store = TelemetryStore()
        _record(store)                                  # no timing at all
        text = _scrape(store)
        self.assertNotIn("strata_request_duration_seconds_count", text)

    def test_a_broken_measurement_is_not_observed(self):
        """A negative or a non-finite duration is not a duration: it is not observed as a zero either."""
        store = TelemetryStore()
        _record(store, total=-5)
        _record(store, total=float("nan"))
        _record(store, total=float("inf"))
        text = _scrape(store)
        self.assertNotIn("strata_request_duration_seconds_count", text)

    def test_the_store_keeps_seconds(self):
        store = TelemetryStore()
        _record(store, total=1500)
        hist = store.summary()["histograms"]["request_duration"]
        self.assertAlmostEqual(hist["sum"], 1.5, places=9)
        self.assertEqual(hist["count"], 1)
        self.assertEqual(hist["buckets"]["2.5"], 1)

    def test_the_retention_does_not_change_the_aggregates(self):
        """Evicting a record from the bounded store does not move the process-lifetime counters."""
        store = TelemetryStore(max_records=2)
        for _ in range(5):
            _record(store, total=1000)
        summary = store.summary()
        self.assertEqual(summary["counters"]["requests_total"], 5)
        self.assertEqual(summary["histograms"]["request_duration"]["count"], 5)
        self.assertAlmostEqual(summary["histograms"]["request_duration"]["sum"], 5.0, places=9)
        self.assertEqual(summary["retention"]["records"], 2)
        self.assertGreater(summary["retention"]["evictions"], 0)

    def test_an_observation_while_the_scrape_runs(self):
        """A concurrent observation and a scrape do not corrupt each other."""
        store = TelemetryStore()
        stop = threading.Event()
        errors = []

        def observe():
            while not stop.is_set():
                try:
                    _record(store, total=500)
                except Exception as e:                   # noqa: BLE001
                    errors.append(e)
                    return

        worker = threading.Thread(target=observe, daemon=True)
        worker.start()
        try:
            for _ in range(20):
                self.assertNotIn("Traceback", _scrape(store))
        finally:
            stop.set()
            worker.join(timeout=5)
        self.assertEqual(errors, [])

    def test_the_buckets_are_the_store_s_own_edges(self):
        """The exporter and the store cannot disagree about the edges."""
        self.assertEqual(tuple(prometheus.TELEMETRY_BUCKETS), tuple(DURATION_BUCKETS))
        self.assertTrue(all(math.isfinite(b) and b > 0 for b in DURATION_BUCKETS))
        self.assertEqual(list(DURATION_BUCKETS), sorted(DURATION_BUCKETS))

    def test_the_cache_reuse_ratio_has_both_of_its_numbers(self):
        """G6: the numerator and the denominator come from the SAME eligible population.

        ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-02 (G1): the records are built through the PRODUCTION
        path (the engine's receipt, applied by apply_engine), so the reuse is a correlated measurement - an
        unattributed number would not enter the authoritative totals.
        """
        store = TelemetryStore()
        for reused, submitted in ((40, 100), (60, 100)):
            record = RequestRecord(f"r{store.seq + 1}")
            record.set_prompt_tokens(rendered=submitted, submitted=submitted)
            apply_engine(record, {"rid": record.request_id, "matched": reused, "reused": reused,
                                  "evaluated": submitted - reused, "work": submitted - reused})
            store.add(record.seal("completed", 200))
        summary = store.summary()
        reuse = summary["cache_reuse"]
        self.assertEqual(reuse["eligible_requests"], 2)
        self.assertEqual(reuse["submitted_tokens"], 200)
        self.assertEqual(reuse["reused_tokens"], 100)
        self.assertAlmostEqual(reuse["ratio"], 0.5, places=6)
        self.assertAlmostEqual(reuse["coverage"], 1.0, places=6)


class NullSemantics(unittest.TestCase):
    """G3: a null is not a zero, and the conservation identity is checked, never repaired."""

    def test_a_null_reuse_is_not_a_zero(self):
        """The amendment's witness: matched 90, reuse not measured -> the disposition is UNKNOWN."""
        r = RequestRecord("abc")
        r.set_native_cache(matched_prefix=90)
        self.assertIsNone(r.reused_prefix_tokens)
        self.assertEqual(r.derive_disposition(), "unknown")
        r.seal("completed", 200)
        self.assertEqual(r.cache_disposition, "unknown")

    def test_a_measured_zero_reuse_is_a_match_without_usable_state(self):
        """The tokens matched, the state did not: that is a MEASURED zero, and it has its own disposition."""
        r = RequestRecord("abc")
        r.set_native_cache(matched_prefix=90, reused_prefix=0, evaluated=10)
        self.assertEqual(r.derive_disposition(), "match_without_usable_state")

    def test_the_non_closing_accounting_is_reported(self):
        """The amendment's witness: 90 reused + 0 outside the prefix + 8 evaluated is not the 100 submitted."""
        r = RequestRecord("abc")
        r.set_prompt_tokens(rendered=100, submitted=100)
        r.set_native_cache(matched_prefix=90, reused_prefix=90, evaluated=8)
        r.seal("completed", 200)
        self.assertEqual(r.accounting_state()["state"], "violated")
        self.assertFalse(r.accounting_state()["valid"])
        self.assertEqual(r.quality, PARTIAL)
        # the measurement is NOT adjusted to make the identity come out right
        self.assertEqual(r.evaluated_tokens, 8)
        self.assertEqual(r.submitted_tokens, 100)

    def test_an_unevaluated_identity_is_not_satisfied(self):
        """A cancelled request's accounting is not complete: the identity is UNEVALUATED, never "satisfied"."""
        r = RequestRecord("abc")
        r.set_prompt_tokens(rendered=100, submitted=100)
        r.set_native_cache(matched_prefix=90, reused_prefix=90, evaluated=8)
        r.seal("cancelled", 499)
        self.assertEqual(r.accounting_state()["state"], "unevaluated")
        self.assertIsNone(r.accounting_state()["valid"])

    def test_the_non_prefix_reuse_is_a_documented_structural_zero(self):
        """Strata reuses a CONTIGUOUS prefix only: the reuse outside it is a structural zero, not a missing value."""
        r = RequestRecord("abc")
        r.set_prompt_tokens(rendered=100, submitted=100)
        r.set_native_cache(matched_prefix=40, reused_prefix=40, evaluated=60)
        r.seal("completed", 200)
        self.assertEqual(r.non_prefix_reused_tokens, 0)
        self.assertEqual(r.accounting_state()["state"], "satisfied")
        self.assertTrue(r.accounting_state()["valid"])

    def test_the_accounting_is_published_in_the_record(self):
        r = RequestRecord("abc")
        r.set_prompt_tokens(rendered=100, submitted=100)
        r.set_native_cache(matched_prefix=90, reused_prefix=90, evaluated=8)
        data = r.seal("completed", 200).to_dict()
        self.assertEqual(data["measurement_quality"]["accounting"]["state"], "violated")
        self.assertFalse(data["measurement_quality"]["accounting"]["valid"])
        self.assertTrue(data["measurement_quality"]["accounting"]["problems"])


class Correlation(unittest.TestCase):
    """G2: the native receipt is bound to the request that asked for it."""

    def test_a_matching_id_is_applied(self):
        r = RequestRecord("abc123")
        apply_engine(r, {"rid": "abc123", "matched": 40, "reused": 40, "evaluated": 60})
        self.assertEqual(r.matched_prefix_tokens, 40)
        self.assertEqual(r.engine_invocation_id, "abc123")

    def test_a_foreign_id_is_not_applied(self):
        """A receipt that carries another request's id is FOREIGN: its numbers are not attached here."""
        r = RequestRecord("abc123")
        apply_engine(r, {"rid": "somebody-else", "matched": 40, "reused": 40, "evaluated": 60})
        self.assertIsNone(r.matched_prefix_tokens)
        self.assertIsNone(r.reused_prefix_tokens)
        self.assertIsNone(r.engine_invocation_id)
        self.assertEqual(r.quality, INSTRUMENTATION_ERROR)
        self.assertIn("engine_telemetry", r.unavailable)

    def test_a_foreign_receipt_does_not_contaminate_the_aggregates(self):
        store = TelemetryStore()
        r = RequestRecord("abc123")
        apply_engine(r, {"rid": "somebody-else", "matched": 4000, "reused": 4000, "evaluated": 0})
        store.add(r.seal("completed", 200))
        summary = store.summary()
        self.assertEqual(summary["counters"]["prompt_tokens_matched"], 0)
        self.assertEqual(summary["counters"]["prompt_tokens_reused"], 0)

    def test_a_missing_id_leaves_the_correlation_unavailable(self):
        """An older engine does not echo the id: the correlation is unavailable, never an asserted join."""
        r = RequestRecord("abc123")
        apply_engine(r, {"matched": 40, "reused": 40, "evaluated": 60})
        self.assertEqual(r.matched_prefix_tokens, 40)          # the request's own DONE line is still its own
        self.assertIsNone(r.engine_invocation_id)
        self.assertIn("identity.engine_invocation_id", r.unavailable)

    def test_two_physical_requests_with_the_same_client_id_are_two_records(self):
        tel = ServerTelemetry()
        first = tel.begin(client_request_id="same")
        second = tel.begin(client_request_id="same")
        self.assertNotEqual(first.request_id, second.request_id)
        tel.finish(first, state="completed", http_status=200)
        tel.finish(second, state="completed", http_status=200)
        self.assertEqual(len(tel.store.list()["records"]), 2)

    def test_a_record_is_finished_at_most_once(self):
        tel = ServerTelemetry()
        record = tel.begin()
        tel.finish(record, state="completed", http_status=200)
        self.assertIsNone(tel.finish(record, state="completed", http_status=200))
        self.assertEqual(tel.store.summary()["counters"]["requests_total"], 1)
        self.assertEqual(tel.inflight(), 0)

    def test_the_telemetry_off_allocates_nothing(self):
        """G6: with the telemetry off there is no receipt, no id and no extended engine command."""
        tel = ServerTelemetry()
        tel.enabled = False
        self.assertIsNone(tel.begin())
        self.assertEqual(tel.store.list()["records"], [])


class FiguresEngine(MockEngine):
    """A mock engine that reports the figures a real engine's DONE line carries, with the request's own id.

    The real engine echoes the request's id on its DONE line (include/strata/program/reqtelemetry.hpp); this
    fixture does the same, so the server's reader is exercised exactly as it is in production.
    """

    def __init__(self, tok, **figs):
        super().__init__(tok, "ok", max_context=CTX)
        self.figs = figs
        self.last = {}

    def generate(self, ids, max_new, sampling, cancel, embeddings=None):
        rid = getattr(self, "request_id", lambda: None)()
        try:
            for token in super().generate(ids, max_new, sampling, cancel, embeddings):
                yield token
        finally:
            self.last = dict(self.last or {})
            self.last.update(self.figs)
            if rid:
                self.last["telemetry"] = {**dict(self.figs.get("telemetry") or {}), "rid": rid}


class HttpCase(unittest.TestCase):
    """The shared fixture of the HTTP witnesses: a real server, a mock engine, no GPU and no model pack."""

    def setUp(self):
        self.tok = ByteTokenizer()
        self.engine = FiguresEngine(self.tok, generated=7, prompt_ms=12.0, decode_ms=30.0, finish="stop",
                                    telemetry={"matched": 4, "reused": 4, "evaluated": 8, "work": 8,
                                               "cache_source": "live", "cache_reason": "EXACT_MATCH",
                                               "restore": "none", "slot": 0})
        self.svc = Service(self.engine, self.tok, ChatTemplate(ROOT / "serve/chat_template.jinja"))
        self.httpd = serve(self.svc, port=0)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def get(self, path):
        req = urllib.request.Request(self.base + path)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def chat(self, text="hi", **kw):
        body = {"model": "m", "messages": [{"role": "user", "content": text}]}
        body.update(kw)
        return self.post("/v1/chat/completions", body)

    def one_record(self):
        _, body = self.get("/v1/telemetry/requests")
        self.assertEqual(len(body["records"]), 1)
        return body["records"][0]


class ProductionWiring(HttpCase):
    """G4: the canonical fields are written where the quantity is measured, through the real HTTP handlers."""

    def test_the_requested_and_the_effective_budget_are_different_numbers(self):
        """The client asks for more than the context allows: the requested budget and the effective one differ."""
        self.svc.fit_max_tokens = True
        self.chat(max_tokens=100000)
        record = self.one_record()
        self.assertEqual(record["generation"]["requested_max_output_tokens"], 100000)
        self.assertIsNotNone(record["generation"]["effective_max_output_tokens"])
        self.assertLess(record["generation"]["effective_max_output_tokens"], 100000)

    def test_the_rendered_prompt_and_the_submitted_one_are_different_numbers(self):
        """A prompt that is truncated: what was rendered is not what was submitted."""
        self.svc.truncate_middle = True
        self.chat(text="x" * 8000)
        record = self.one_record()
        self.assertIsNotNone(record["prompt"]["rendered_tokens"])
        self.assertIsNotNone(record["prompt"]["submitted_tokens"])
        self.assertGreater(record["prompt"]["rendered_tokens"], record["prompt"]["submitted_tokens"])

    def test_the_generated_and_the_emitted_tokens_are_different_numbers(self):
        """The engine's count and what the client received are two different numbers.

        ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-02 (A3): the generation loop's count is NOT the emitted
        count.  The response is transformed (the reasoning, the tool calls, the stop handling), so the number of
        tokens written to the client cannot be attributed there: it stays null and says why.  A null is not a zero.
        """
        self.chat()
        record = self.one_record()
        self.assertEqual(record["generation"]["generated_tokens"], 7)     # the engine's own count
        self.assertIsNone(record["generation"]["emitted_tokens"])       # not attributable: not a measured zero
        self.assertIn("generation.emitted_tokens", record["measurement_quality"]["unavailable_fields"])

    def test_the_durations_come_from_a_monotonic_clock(self):
        self.chat()
        record = self.one_record()
        timing = record["timing_ms"]
        self.assertIn("total", timing)
        self.assertIn("tokenization", timing)
        authority = record["measurement_quality"]["timing_authority"]
        self.assertEqual(authority.get("total"), "http_server")
        self.assertEqual(authority.get("tokenization"), "http_server")
        self.assertGreaterEqual(timing["total"], 0)

    def test_the_native_measurements_reach_the_record_through_the_real_parser(self):
        """The engine's DONE figures are parsed and applied, with the request's own id."""
        self.chat()
        record = self.one_record()
        self.assertEqual(record["prompt"]["matched_prefix_tokens"], 4)
        self.assertEqual(record["prompt"]["reused_prefix_tokens"], 4)
        self.assertEqual(record["prompt"]["evaluated_tokens"], 8)
        self.assertEqual(record["identity"]["slot_id"], 0)
        self.assertTrue(record["identity"]["engine_invocation_id"])

    def test_two_concurrent_requests_keep_their_own_measurements(self):
        """No cross-request attribution: two requests, two records, two identities."""
        results = []

        def one():
            results.append(self.chat()[0])

        threads = [threading.Thread(target=one) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        _, body = self.get("/v1/telemetry/requests")
        self.assertEqual(len(body["records"]), 2)
        self.assertEqual(len({r["identity"]["request_id"] for r in body["records"]}), 2)
        for record in body["records"]:
            self.assertIsNotNone(record["timing_ms"].get("total"))


class LifecycleOwnership(HttpCase):
    """G5: one authoritative terminal finalization per accepted physical HTTP request."""

    def test_every_accepted_request_produces_exactly_one_receipt(self):
        for _ in range(3):
            self.chat()
        _, body = self.get("/v1/telemetry/requests")
        self.assertEqual(len(body["records"]), 3)
        summary = self.svc.telemetry_requests.store.summary()["counters"]
        self.assertEqual(summary["requests_total"], 3)
        self.assertEqual(summary["requests_completed"], 3)
        self.assertEqual(self.svc.telemetry_requests.inflight(), 0)

    def test_a_refused_request_still_gets_a_receipt(self):
        """A request the server refuses (its prompt does not fit) is RECEIVED and refused - never lost."""
        code, _ = self.chat(text="x" * 100000)
        self.assertEqual(code, 400)
        _, body = self.get("/v1/telemetry/requests")
        self.assertEqual(len(body["records"]), 1)
        self.assertEqual(body["records"][0]["lifecycle"]["state"], "rejected")
        self.assertEqual(self.svc.telemetry_requests.inflight(), 0)

    def test_the_invariant_at_quiescence(self):
        """accepted = completed + cancelled + failed + rejected, and nothing is in flight."""
        self.chat()
        self.chat(text="x" * 100000)
        counters = self.svc.telemetry_requests.store.summary()["counters"]
        self.assertEqual(counters["requests_total"],
                         counters["requests_completed"] + counters["requests_cancelled"]
                         + counters["requests_failed"])
        self.assertEqual(self.svc.telemetry_requests.inflight(), 0)


class HttpContract(HttpCase):
    """G7: the HTTP contract - the inputs are validated, and a refused input is an error, not an empty page."""

    def test_an_expired_cursor_is_refused(self):
        """An expired cursor must not impersonate an exhausted collection."""
        store = TelemetryStore()
        for i in range(3):
            store.add(RequestRecord(f"r{i}").seal("completed", 200))
        stale = base64.urlsafe_b64encode(
            f"seq:1:{store.server_instance_id}:{int(time.time()) - 7200}".encode()).decode().rstrip("=")
        with self.assertRaises(ValueError):
            store.list(cursor=stale)

    def test_a_cursor_of_another_server_is_refused(self):
        store = TelemetryStore(server_instance_id="server-a")
        for i in range(3):
            store.add(RequestRecord(f"r{i}").seal("completed", 200))
        foreign = encode_cursor(1, "server-b")
        with self.assertRaises(ValueError):
            store.list(cursor=foreign)

    def test_a_filter_that_names_nothing_is_an_error(self):
        code, _ = self.get("/v1/telemetry/requests?request_status=nonsense")
        self.assertEqual(code, 400)
        code, _ = self.get("/v1/telemetry/requests?cache_disposition=nonsense")
        self.assertEqual(code, 400)
        code, _ = self.get("/v1/telemetry/requests?client_request_id=has%20space")
        self.assertEqual(code, 400)

    def test_a_request_id_that_is_not_one_of_ours_is_an_error(self):
        code, _ = self.get("/v1/telemetry/requests/not-an-id")
        self.assertEqual(code, 400)
        code, _ = self.get("/v1/telemetry/requests/" + "a" * 32)
        self.assertEqual(code, 404)          # a well-formed id that is not kept: not found, not an error

    def test_the_page_size_is_capped(self):
        code, _ = self.get("/v1/telemetry/requests?limit=100000")
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main()
