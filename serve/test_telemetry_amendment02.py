#!/usr/bin/env python3
"""serve/test_telemetry_amendment02.py - the witnesses of
ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-02 (and its FULL_DIFF_REVIEW_01 addendum).

Every witness here drives the PRODUCTION code: the real store (serve/reqtelemetry/store.py), the real correlation
(serve/reqtelemetry/correlation.py), the real evidence writer (serve/reqtelemetry/evidence.py), the real HTTP
handlers (serve/server.py) and the real exporter (serve/prometheus.py).  A witness that only calls a setter does
not qualify.

  * G1: an invalid, unattributed or broken measurement never enters an authoritative aggregate;
  * G2/A2: the native receipt is bound to the INVOCATION, not to the request;
  * G5: the engine's eviction counter is a high-water mark;
  * G6: a cursor that names nothing is refused;
  * A4: the lifecycle accounting is independent of the receipt's delivery;
  * A5: the evidence writer's bounds and its flush are exact;
  * A8: a process-lifetime total is not relabelled when the model changes.
"""
from __future__ import annotations

import json
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
from serve.reqtelemetry import (RequestRecord, ServerTelemetry, TelemetryStore, apply_engine,  # noqa: E402
                                decode_cursor, encode_cursor, new_invocation_id)
from serve.reqtelemetry.evidence import EvidenceLog  # noqa: E402
from serve.server import ByteTokenizer, MockEngine, Service, serve  # noqa: E402

CTX = 4096


def _store_with(**counters):
    """A finished record in a store, built through the PRODUCTION path (the engine's receipt)."""
    store = TelemetryStore()
    record = RequestRecord(f"r{store.seq + 1}")
    record.set_prompt_tokens(rendered=counters.get("submitted"), submitted=counters.get("submitted"))
    apply_engine(record, {"rid": record.request_id, "matched": counters.get("matched"),
                          "reused": counters.get("reused"), "evaluated": counters.get("evaluated"),
                          "work": counters.get("work", counters.get("evaluated"))})
    store.add(record.seal("completed", 200))
    return store, record


class Admission(unittest.TestCase):
    """G1: what may enter an authoritative aggregate."""

    def test_a_reused_prefix_longer_than_the_submitted_prompt_is_violated_and_excluded(self):
        store, record = _store_with(submitted=100, matched=100, reused=120, evaluated=0)
        data = record.to_dict()
        self.assertEqual(data["measurement_quality"]["accounting"]["state"], "violated")
        self.assertFalse(data["measurement_quality"]["aggregate_eligible"])
        self.assertEqual(store.summary()["counters"]["prompt_tokens_reused"], 0)
        self.assertEqual(store.summary()["counters"]["prompt_tokens_matched"], 0)

    def test_a_negative_token_count_is_not_a_measurement_and_is_not_counted(self):
        store = TelemetryStore()
        record = RequestRecord("r1")
        record.set_prompt_tokens(rendered=100, submitted=100)
        apply_engine(record, {"rid": "r1", "matched": 100, "reused": -5, "evaluated": 105})
        data = record.seal("completed", 200).to_dict()
        self.assertFalse(data["measurement_quality"]["measurement_valid"])
        self.assertFalse(data["measurement_quality"]["aggregate_eligible"])
        self.assertIsNone(data["prompt"]["reused_prefix_tokens"])
        store.add(record)
        self.assertEqual(store.summary()["counters"]["prompt_tokens_reused"], 0)

    def test_a_broken_sum_identity_is_violated_and_excluded(self):
        store, record = _store_with(submitted=100, matched=100, reused=90, evaluated=8)
        data = record.to_dict()
        self.assertEqual(data["measurement_quality"]["accounting"]["state"], "violated")
        self.assertFalse(data["measurement_quality"]["aggregate_eligible"])
        self.assertEqual(store.summary()["counters"]["prompt_tokens_evaluated"], 0)
        self.assertEqual(store.summary()["counters"]["prompt_tokens_reused"], 0)

    def test_a_missing_native_identity_leaves_the_correlation_unavailable(self):
        store = TelemetryStore()
        record = RequestRecord("r1")
        record.set_prompt_tokens(rendered=100, submitted=100)
        apply_engine(record, {"matched": 90, "reused": 90, "evaluated": 10})
        data = record.seal("completed", 200).to_dict()
        self.assertEqual(data["measurement_quality"]["native_correlation"], "unavailable")
        self.assertFalse(data["measurement_quality"]["aggregate_eligible"])
        store.add(record)
        counters = store.summary()["counters"]
        self.assertEqual(counters["prompt_tokens_reused"], 0)          # the native numbers are not authoritative
        self.assertEqual(counters["prompt_tokens_submitted"], 100)    # the server's own number still counts

    def test_the_reuse_ratio_stays_between_zero_and_one(self):
        store = TelemetryStore()
        for reused in (0, 50, 100):
            record = RequestRecord(f"r{store.seq + 1}")
            record.set_prompt_tokens(rendered=100, submitted=100)
            apply_engine(record, {"rid": record.request_id, "matched": reused, "reused": reused,
                                  "evaluated": 100 - reused})
            store.add(record.seal("completed", 200))
        reuse = store.summary()["cache_reuse"]
        self.assertGreaterEqual(reuse["ratio"], 0.0)
        self.assertLessEqual(reuse["ratio"], 1.0)
        self.assertEqual(reuse["eligible_requests"], 3)

    def test_a_counter_never_falls_because_an_invalid_measurement_was_admitted(self):
        store = TelemetryStore()
        record = RequestRecord("r1")
        record.set_prompt_tokens(rendered=100, submitted=100)
        apply_engine(record, {"rid": "r1", "matched": 100, "reused": 120, "evaluated": 0})
        store.add(record.seal("completed", 200))
        self.assertEqual(store.summary()["counters"]["prompt_tokens_reused"], 0)


class InvocationIdentity(unittest.TestCase):
    """G2/A2: the receipt belongs to the invocation, not to the request."""

    def test_the_matching_invocation_is_applied(self):
        record = RequestRecord("r1")
        invocation = new_invocation_id()
        record.engine_invocation_id = invocation
        verdict = apply_engine(record, {"rid": invocation, "matched": 40, "reused": 40, "evaluated": 60},
                               expected_invocation_id=invocation)
        self.assertEqual(verdict["correlation"], "verified")
        self.assertEqual(record.matched_prefix_tokens, 40)

    def test_a_foreign_invocation_is_rejected_and_its_numbers_are_not_applied(self):
        record = RequestRecord("r1")
        invocation = new_invocation_id()
        record.engine_invocation_id = invocation
        verdict = apply_engine(record, {"rid": "0123456789abcdef", "matched": 40, "reused": 40, "evaluated": 60},
                               expected_invocation_id=invocation)
        self.assertEqual(verdict["correlation"], "rejected")
        self.assertFalse(verdict["admitted"])
        self.assertIsNone(record.matched_prefix_tokens)
        self.assertIsNone(record.reused_prefix_tokens)

    def test_the_recovery_witness(self):
        """A: two invocations B and C; the receipt of B arrives while C runs.  It is rejected."""
        record = RequestRecord("A")
        first, second = new_invocation_id(), new_invocation_id()
        record.engine_invocation_id = second
        verdict = apply_engine(record, {"rid": first, "matched": 10, "reused": 10, "evaluated": 5},
                               expected_invocation_id=second)
        self.assertEqual(verdict["correlation"], "rejected")
        self.assertFalse(verdict["admitted"])

    def test_a_foreign_receipt_does_not_contaminate_the_aggregates(self):
        store = TelemetryStore()
        record = RequestRecord("r1")
        invocation = new_invocation_id()
        record.engine_invocation_id = invocation
        apply_engine(record, {"rid": "fedcba9876543210", "matched": 4000, "reused": 4000, "evaluated": 0},
                    expected_invocation_id=invocation)
        store.add(record.seal("completed", 200))
        counters = store.summary()["counters"]
        self.assertEqual(counters["prompt_tokens_matched"], 0)
        self.assertEqual(counters["prompt_tokens_reused"], 0)

    def test_a_missing_identity_is_unavailable_and_never_an_asserted_join(self):
        record = RequestRecord("r1")
        verdict = apply_engine(record, {"matched": 40}, expected_invocation_id=new_invocation_id())
        self.assertEqual(verdict["correlation"], "unavailable")
        self.assertFalse(verdict["admitted"])

    def test_every_invocation_id_is_its_own(self):
        ids = {new_invocation_id() for _ in range(100)}
        self.assertEqual(len(ids), 100)
        self.assertTrue(all(i and all(c in "0123456789abcdef" for c in i) for i in ids))


class Monotonicity(unittest.TestCase):
    """G5: the engine's own eviction counter is a high-water mark."""

    def test_the_counter_never_falls(self):
        store = TelemetryStore()
        seen = []
        for evictions in (10, 8, 11):
            record = RequestRecord(f"r{store.seq + 1}")
            apply_engine(record, {"rid": record.request_id, "evictions": evictions})
            store.add(record.seal("completed", 200))
            seen.append(store.summary()["counters"]["cache_evictions"])
        self.assertEqual(seen, [10, 10, 11])

    def test_a_new_engine_instance_starts_its_own_mark(self):
        """Each engine instance has its own mark; the total is the sum of the increases (10 + 3 + 2)."""
        store = TelemetryStore()
        for instance, evictions in (("engine-a", 10), ("engine-b", 3), ("engine-a", 12)):
            record = RequestRecord(f"r{store.seq + 1}")
            record.engine_instance_id = instance
            apply_engine(record, {"rid": record.request_id, "evictions": evictions})
            store.add(record.seal("completed", 200))
        self.assertEqual(store.summary()["counters"]["cache_evictions"], 15)


class Cursors(unittest.TestCase):
    """G6: the cursor contract."""

    def test_a_cursor_without_an_owner_is_refused(self):
        with self.assertRaises(ValueError):
            decode_cursor(encode_cursor(1, ""), "server-1")

    def test_a_foreign_cursor_is_refused(self):
        with self.assertRaises(ValueError):
            decode_cursor(encode_cursor(1, "server-1"), "server-2")

    def test_a_negative_or_zero_sequence_is_refused(self):
        for seq in (0, -1):
            with self.assertRaises(ValueError):
                decode_cursor(encode_cursor(seq, "server-1"), "server-1")

    def test_an_expired_cursor_is_refused(self):
        cursor = encode_cursor(1, "server-1")
        with self.assertRaises(ValueError):
            decode_cursor(cursor, "server-1", max_age_s=-1)

    def test_a_cursor_in_the_future_is_refused(self):
        import base64
        raw = "seq:5:server-1:%d" % (int(time.time()) + 3600)
        cursor = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
        with self.assertRaises(ValueError):
            decode_cursor(cursor, "server-1")

    def test_a_cursor_that_names_a_record_never_written_is_refused(self):
        store = TelemetryStore()
        with self.assertRaises(ValueError):
            store.list(cursor=encode_cursor(1000, store.server_instance_id))

    def test_a_cursor_whose_page_was_evicted_is_refused(self):
        store = TelemetryStore(max_records=2)
        for i in range(5):
            record = RequestRecord(f"r{i}")
            store.add(record.seal("completed", 200))
        with self.assertRaises(ValueError):
            store.list(cursor=encode_cursor(1, store.server_instance_id))


class EvidenceWriter(unittest.TestCase):
    """A5: the writer's bounds, its bytes and its flush."""

    def test_the_bytes_are_utf8_bytes_and_not_characters(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "e.jsonl"
            log = EvidenceLog(path, queue_bytes=4096)
            record = {"a": "é" * 3000}                     # 6000 bytes of UTF-8, 3000 characters
            self.assertFalse(log.write(record))            # the BYTE budget refuses it
            counters = log.counters()
            self.assertEqual(counters["dropped_records"], 1)
            self.assertEqual(counters["accepted_records"], 0)
            log.close()

    def test_a_blocked_writer_is_not_flushed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "e.jsonl"
            log = EvidenceLog(path)
            release = threading.Event()
            original = log._handle

            class Blocked:
                def write(self, data):
                    release.wait(5)
                    return original.write(data)

                def flush(self):
                    return original.flush()

                def close(self):
                    return original.close()

            log._handle = Blocked()
            log.write({"a": 1})
            time.sleep(0.1)
            self.assertFalse(log.flush(timeout=0.2))       # the record is still in the writer
            release.set()
            self.assertTrue(log.flush(timeout=5))
            self.assertEqual(log.counters()["written_records"], 1)
            log.close()

    def test_the_outstanding_bound_counts_the_record_being_written(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "e.jsonl"
            log = EvidenceLog(path, queue_size=1)
            release = threading.Event()
            original = log._handle

            class Blocked:
                def write(self, data):
                    release.wait(5)
                    return original.write(data)

                def flush(self):
                    return original.flush()

                def close(self):
                    return original.close()

            log._handle = Blocked()
            self.assertTrue(log.write({"a": 1}))
            time.sleep(0.1)
            self.assertFalse(log.write({"a": 2}))           # the bound counts the record being written
            self.assertEqual(log.counters()["dropped_records"], 1)
            release.set()
            log.flush(timeout=5)
            log.close()

    def test_a_refused_write_is_counted_as_a_failure(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "e.jsonl"
            log = EvidenceLog(path)
            log._handle = None
            self.assertFalse(log.write({"a": 1}))
            self.assertEqual(log.counters()["failed_records"], 1)
            log.close()


class Lifecycle(unittest.TestCase):
    """A4: the lifecycle accounting is independent of the receipt's delivery."""

    def test_the_terminal_outcome_survives_a_seal_that_fails(self):
        tel = ServerTelemetry()
        record = tel.begin()

        def broken(*args, **kwargs):
            raise RuntimeError("the seal failed")

        record.seal = broken
        with self.assertRaises(RuntimeError):
            tel.finish(record, state="completed", http_status=200)
        counters = tel.store.summary()["counters"]
        self.assertEqual(counters["requests_accepted"], 1)
        self.assertEqual(counters["requests_terminal_completed"], 1)
        self.assertEqual(counters["receipt_delivery_failures"], 1)
        self.assertEqual(tel.inflight(), 0)

    def test_the_identity_balances_at_quiescence(self):
        tel = ServerTelemetry()
        for state in ("completed", "cancelled", "failed", "rejected"):
            tel.finish(tel.begin(), state=state, http_status=200)
        counters = tel.store.summary()["counters"]
        self.assertEqual(counters["requests_accepted"],
                         counters["requests_terminal_completed"] + counters["requests_terminal_cancelled"]
                         + counters["requests_terminal_failed"] + counters["requests_terminal_rejected"])
        self.assertEqual(tel.inflight(), 0)


class ModelSwitch(unittest.TestCase):
    """A8: a process-lifetime total is not relabelled when the model changes."""

    def test_the_work_of_the_first_model_is_not_published_under_the_second(self):
        store = TelemetryStore()
        record = RequestRecord("r1")
        record.set_prompt_tokens(rendered=10, submitted=10)
        apply_engine(record, {"rid": "r1", "matched": 1, "reused": 1, "evaluated": 9})
        store.add(record.seal("completed", 200))
        summary = store.summary()
        summary["inflight"] = 0
        summary["enabled"] = True
        metrics = {"engine": {"model": "model-b"}, "live": {}, "totals": {}, "hardware": {}, "requests": [],
                   "telemetry": summary}
        lat = {k: ([0] * len(prometheus.BUCKETS), 0.0, 0) for k in ("ttft", "itl", "e2e")}
        text = prometheus.render(metrics, lat)
        self.assertIn("strata_prompt_tokens_total 10", text)
        self.assertNotIn('strata_prompt_tokens_total{model_name="model-b"}', text)


class FiguresEngine(MockEngine):
    """A mock engine that reports the figures a real engine's DONE line carries, with the request's own id.

    The real engine echoes the invocation's id on its DONE line (include/strata/program/reqtelemetry.hpp); this
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


class HttpWitnesses(unittest.TestCase):
    """A1, A3, A4 and G6 through the PRODUCTION HTTP handlers."""

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
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def get(self, path):
        req = urllib.request.Request(self.base + path)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def chat(self, text="hi", **kw):
        body = {"model": "m", "messages": [{"role": "user", "content": text}]}
        body.update(kw)
        return self.post("/v1/chat/completions", body)

    def records(self):
        _, body = self.get("/v1/telemetry/requests")
        return body["records"]

    def test_the_queue_wait_is_the_wait_and_not_the_whole_request(self):
        """A1: a request that waited for its turn reports the WAIT, not the time it spent running."""
        self.engine.delay = 0.005
        self.engine.script = self.tok.encode("word " * 20, parse_special=True) + [7]
        results = []

        def one():
            results.append(self.chat()[0])

        first = threading.Thread(target=one)
        first.start()
        time.sleep(0.1)                                   # the first request holds the turn
        second = threading.Thread(target=one)
        second.start()
        first.join(timeout=60)
        second.join(timeout=60)
        records = self.records()
        self.assertEqual(len(records), 2)
        queued = [r for r in records if "queue" in r["timing_ms"] and r["timing_ms"]["queue"] > 100]
        self.assertTrue(queued, "the second request really waited for its turn")
        for record in queued:
            # the wait is the wait: the request also spent time running, so the wait is well under its total
            self.assertLess(record["timing_ms"]["queue"] * 1.25, record["timing_ms"]["total"])

    def test_the_first_content_is_timed_at_the_write_boundary(self):
        """A3: the engine's first token and the first byte written are two different measurements."""
        self.chat()
        record = self.records()[0]
        timing = record["timing_ms"]
        authority = record["measurement_quality"]["timing_authority"]
        self.assertIn("http_first_token", timing)
        self.assertIn("engine_first_token", timing)
        self.assertEqual(authority.get("http_first_token"), "http_server_write")
        self.assertEqual(authority.get("engine_first_token"), "http_server_observation")

    def test_the_lifecycle_identity_balances_over_http(self):
        """A4: at quiescence the accepted requests and the terminal outcomes balance."""
        self.chat()
        _, summary = self.get("/v1/telemetry/summary")
        counters = summary["counters"]
        self.assertEqual(counters["requests_accepted"],
                         counters["requests_terminal_completed"] + counters["requests_terminal_cancelled"]
                         + counters["requests_terminal_failed"] + counters["requests_terminal_rejected"])
        self.assertEqual(summary["inflight"], 0)

    def test_a_broken_cursor_is_refused_over_http(self):
        """G6: a cursor that names nothing is an error, not an exhausted collection."""
        status, _ = self.get("/v1/telemetry/requests?cursor=not-a-cursor")
        self.assertEqual(status, 400)
        status, _ = self.get("/v1/telemetry/requests?cursor=" +
                             encode_cursor(99999, self.svc.telemetry_requests.server_instance_id))
        self.assertEqual(status, 400)

    def test_the_emitted_tokens_are_not_the_generated_ones(self):
        """A3: the generation loop's count is not the emitted count."""
        self.chat()
        record = self.records()[0]
        self.assertEqual(record["generation"]["generated_tokens"], 7)
        self.assertIsNone(record["generation"]["emitted_tokens"])

    def test_two_requests_never_share_an_invocation_id(self):
        """A2: the invocation id is new for every dispatch, so two requests can never be confused."""
        self.chat()
        self.chat()
        ids = [r["identity"]["engine_invocation_id"] for r in self.records()]
        self.assertEqual(len(ids), 2)
        self.assertTrue(all(ids))
        self.assertNotEqual(ids[0], ids[1])


if __name__ == "__main__":
    unittest.main()
