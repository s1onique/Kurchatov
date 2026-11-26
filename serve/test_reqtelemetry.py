"""serve/test_reqtelemetry.py - the per-request telemetry (ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01).

The telemetry's contract, its HTTP API, its retention bounds, its privacy and its accounting rules, checked
through the real HTTP surface against the mock engine (no GPU and no model pack).

    python -m unittest serve.test_reqtelemetry -v

What is checked here, and why:

  * the RECORD: its sections, its schema, and the rule that an unavailable measurement is null and never a zero;
  * the ACCOUNTING: the identities that must hold for a complete request, and that a broken one is REPORTED
    rather than repaired;
  * the IDENTITY: two requests with the same client id stay two records, and the server's id is the key;
  * the HTTP API: its routes, its pagination, its filters, its bounds and its errors;
  * the RETENTION: the store evicts, and the process-lifetime counters do not fall when it does;
  * the PRIVACY: no prompt, no answer, no header and no key appears anywhere in the telemetry;
  * the ACCESS CONTROL: the request-level endpoints need the key when the listener is not this PC's own;
  * the ENGINE FIGURES: the record takes the engine's own measurements, and keeps them apart from the server's.
"""
import json
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from serve.frontend import ChatTemplate
from serve.reqtelemetry import (COMPLETE, DISPOSITION_COLD_MISS, DISPOSITION_FULL_HIT, DISPOSITION_PARTIAL_HIT,
                                MAXIMUM_PAGE_SIZE, PARTIAL, RequestRecord, ServerTelemetry, TelemetryStore,
                                apply_engine, new_request_id, validate, valid_client_request_id)
from serve.server import ByteTokenizer, MockEngine, Service, serve

ROOT = Path(__file__).resolve().parents[1]
CTX = 4096


class TelemetryEngine(MockEngine):
    """A mock engine that reports the SAME figures a real engine's DONE line carries, so the server's reader and
    the record's accounting are exercised end to end."""

    def __init__(self, tok, **figs):
        super().__init__(tok, "ok", max_context=CTX)
        self.figs = figs
        self.rids = []
        self.last = {}
        self.cancelling = False

    def generate(self, ids, max_new, sampling, cancel, embeddings=None):
        self.rids.append(getattr(self, "request_id", lambda: None)())
        try:
            for token in super().generate(ids, max_new, sampling, cancel, embeddings):
                if getattr(self, "cancelling", False):
                    cancel.set()               # the client went away: the request ends as a cancellation
                yield token
        finally:
            # the DONE line's figures, as the real engine reports them (the server reads them after the generator
            # is closed, so they must be set even when the consumer stopped early)
            self.last = dict(self.last or {})
            self.last.update(self.figs)


class Http(unittest.TestCase):
    """The telemetry API over HTTP."""

    def setUp(self):
        import threading
        self.samplers_before = sum(1 for t in threading.enumerate() if t.name.endswith("(_loop)"))
        self.tok = ByteTokenizer()
        self.engine = TelemetryEngine(self.tok, prompt_tokens=100, prompt_read=60, reused=40, generated=7,
                                      prompt_ms=12.0, decode_ms=30.0, finish="stop",
                                      telemetry={"matched": 40, "reused": 40, "evaluated": 60, "work": 60,
                                                 "cache_source": "live", "cache_reason": "EXACT_MATCH",
                                                 "restore": "none", "slot": 0})
        self.svc = Service(self.engine, self.tok, ChatTemplate(ROOT / "serve/chat_template.jinja"))
        self.httpd = serve(self.svc, port=0)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        import threading
        import time
        self.httpd.shutdown()
        self.httpd.server_close()
        # The hardware sampler stops a moment after the server does (it finishes its sample first).  Waiting for
        # it here keeps the next test's thread count honest.
        for _ in range(50):
            if sum(1 for t in threading.enumerate() if t.name.endswith("(_loop)")) <= self.samplers_before:
                break
            time.sleep(0.1)

    def get(self, path, headers=None):
        req = urllib.request.Request(self.base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                raw = e.read()
                try:
                    return e.code, json.loads(raw)
                except ValueError:
                    return e.code, {"raw": raw.decode("utf-8", "replace")}

    def post(self, path, body, headers=None):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), headers=h)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read()), dict(r.headers)
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read()), dict(e.headers)

    def chat(self, text="hi", headers=None, **kw):
        body = {"model": "m", "messages": [{"role": "user", "content": text}]}
        body.update(kw)
        return self.post("/v1/chat/completions", body, headers=headers)

    def chat_with(self, client_id, text="hi"):
        return self.post("/v1/chat/completions",
                         {"model": "m", "messages": [{"role": "user", "content": text}]},
                         headers={"X-Request-ID": client_id})


class Record(unittest.TestCase):
    """The record itself: its sections, its schema, and null-versus-zero."""

    def test_the_sections_are_there(self):
        r = RequestRecord("abc")
        data = r.to_dict()
        for section in ("schema_version", "identity", "lifecycle", "prompt", "cache", "timing_ms", "generation",
                        "measurement_quality"):
            self.assertIn(section, data)
        self.assertEqual(validate(data), [])

    def test_an_unmeasured_field_is_null_and_never_zero(self):
        r = RequestRecord("abc")
        data = r.to_dict()
        self.assertIsNone(data["prompt"]["evaluated_tokens"])
        self.assertIsNone(data["prompt"]["reused_prefix_tokens"])
        self.assertIsNone(data["cache"]["restore_ms"])
        # a measured zero IS a zero
        r.set_native_cache(matched_prefix=0, reused_prefix=0, evaluated=10)
        data = r.to_dict()
        self.assertEqual(data["prompt"]["matched_prefix_tokens"], 0)
        self.assertEqual(data["prompt"]["reused_prefix_tokens"], 0)

    def test_a_measured_zero_and_an_unavailable_field_are_different(self):
        r = RequestRecord("abc")
        r.set_native_cache(matched_prefix=0, reused_prefix=0, evaluated=5)
        r.mark_unavailable("cache.restore_ms", "the engine did not measure it")
        data = r.to_dict()
        self.assertEqual(data["prompt"]["matched_prefix_tokens"], 0)
        self.assertIsNone(data["cache"]["restore_ms"])
        self.assertIn("cache.restore_ms", data["measurement_quality"]["unavailable_fields"])
        self.assertEqual(data["measurement_quality"]["state"], PARTIAL)

    def test_the_client_id_is_validated(self):
        self.assertTrue(valid_client_request_id("abc-123_x.y"))
        self.assertFalse(valid_client_request_id(""))            # empty
        self.assertFalse(valid_client_request_id("a" * 200))      # too long
        self.assertFalse(valid_client_request_id("has space"))    # a space
        self.assertFalse(valid_client_request_id("has\nnewline"))
        self.assertFalse(valid_client_request_id(None))
        # an invalid client id is dropped, not kept
        r = RequestRecord("abc", client_request_id="has space")
        self.assertIsNone(r.client_request_id)

    def test_the_server_id_is_unique_per_attempt(self):
        ids = {new_request_id() for _ in range(1000)}
        self.assertEqual(len(ids), 1000)


class Accounting(unittest.TestCase):
    """The accounting identities: they are CHECKED, never enforced."""

    def test_a_complete_request_closes(self):
        r = RequestRecord("abc")
        r.set_prompt_tokens(rendered=100, submitted=100)
        r.set_native_cache(matched_prefix=40, reused_prefix=40, evaluated=60, non_prefix_reused=0,
                           evaluation_work=60)
        r.seal("completed", 200)
        self.assertEqual(r.conservation(), [])

    def test_a_broken_identity_is_reported_and_not_repaired(self):
        r = RequestRecord("abc")
        r.set_prompt_tokens(rendered=100, submitted=100)
        # the reused prefix is longer than the submitted prompt: impossible
        r.set_native_cache(matched_prefix=40, reused_prefix=80, evaluated=60, non_prefix_reused=0)
        problems = r.conservation()
        self.assertTrue(problems)
        r.seal("completed", 200)
        # the measurement is NOT adjusted to make it come out right
        self.assertEqual(r.reused_prefix_tokens, 80)
        self.assertEqual(r.quality, PARTIAL)

    def test_matched_may_exceed_reused(self):
        """A candidate whose tokens match but whose state is unusable: the match moves, the reuse does not."""
        r = RequestRecord("abc")
        r.set_prompt_tokens(rendered=100, submitted=100)
        r.set_native_cache(matched_prefix=80, reused_prefix=0, evaluated=100, non_prefix_reused=0,
                           evaluation_work=100)
        self.assertEqual(r.conservation(), [])
        r.seal("completed", 200)
        self.assertEqual(r.cache_disposition, "match_without_usable_state")

    def test_the_disposition_is_derived_from_the_evidence(self):
        r = RequestRecord("abc")
        r.set_prompt_tokens(rendered=100, submitted=100)
        r.set_native_cache(matched_prefix=0, reused_prefix=0, evaluated=100, non_prefix_reused=0)
        r.seal("completed", 200)
        self.assertEqual(r.cache_disposition, DISPOSITION_COLD_MISS)

        r = RequestRecord("abc")
        r.set_prompt_tokens(rendered=100, submitted=100)
        r.set_native_cache(matched_prefix=100, reused_prefix=100, evaluated=0, non_prefix_reused=0)
        r.seal("completed", 200)
        self.assertEqual(r.cache_disposition, DISPOSITION_FULL_HIT)

        r = RequestRecord("abc")
        r.set_prompt_tokens(rendered=100, submitted=100)
        r.set_native_cache(matched_prefix=40, reused_prefix=40, evaluated=60, non_prefix_reused=0)
        r.seal("completed", 200)
        self.assertEqual(r.cache_disposition, DISPOSITION_PARTIAL_HIT)

    def test_a_cancelled_request_is_not_a_successful_one(self):
        r = RequestRecord("abc")
        r.set_prompt_tokens(rendered=100, submitted=100)
        r.set_native_cache(matched_prefix=40, reused_prefix=40, evaluated=20, non_prefix_reused=0)
        r.seal("cancelled", 499, finish_reason="cancel")
        self.assertEqual(r.state, "cancelled")
        self.assertEqual(r.quality, PARTIAL)


class Schema(unittest.TestCase):
    """Every figure the engine can write must produce a record that validates."""

    def test_every_figure_the_engine_can_write_validates(self):
        figures = [
            {}, {"matched": 0}, {"matched": 40, "reused": 40, "evaluated": 60, "work": 60},
            {"divergent": -1}, {"divergent": -2}, {"divergent": 0}, {"divergent": 12},
            {"slot": -1}, {"slot": 0}, {"slot": 3},
            {"restore": "none"}, {"restore": "succeeded"}, {"restore": "failed"},
            {"cache_source": "live"}, {"cache_source": "parked_checkpoint"}, {"cache_source": "nonsense"},
            {"cache_reason": "EXACT_MATCH"}, {"cache_reason": "STEERING_MISMATCH"}, {"cache_reason": "NONSENSE"},
            {"rid": "abc123"}, {"restore_ms": 1.5}, {"lookup_ms": 0.25},
            {"replayed": 10}, {"invalidations": 0}, {"evictions": 3},
        ]
        for fig in figures:
            r = RequestRecord("abc")
            apply_engine(r, fig)
            r.set_prompt_tokens(rendered=100, submitted=100)
            r.set_native_cache(non_prefix_reused=0)
            r.seal("completed", 200)
            errors = validate(r.to_dict())
            self.assertEqual(errors, [], f"the figures {fig} produced an invalid record: {errors}")

    def test_a_negative_divergence_is_never_a_position(self):
        r = RequestRecord("abc")
        apply_engine(r, {"divergent": -1})
        self.assertIsNone(r.first_divergent_token_index)
        self.assertIn("prompt.first_divergent_token_index", r.unavailable)


class Store(unittest.TestCase):
    """The store: its bounds, its pagination and its counters."""

    def test_the_counters_do_not_fall_when_a_record_is_evicted(self):
        store = TelemetryStore(max_records=5, max_bytes=1 << 20)
        for i in range(20):
            r = RequestRecord(f"r{i}")
            # AMENDMENT-02 (G1): the engine's figures arrive through the PRODUCTION path (apply_engine), so the
            # measurements are correlated to the request and enter the authoritative totals.
            apply_engine(r, {"rid": r.request_id, "matched": 1, "reused": 1, "evaluated": 1})
            r.seal("completed", 200)
            store.add(r)
        summary = store.summary()
        self.assertEqual(summary["counters"]["requests_total"], 20)
        self.assertLessEqual(summary["retention"]["records"], 5)
        self.assertGreater(summary["retention"]["evictions"], 0)
        self.assertEqual(summary["counters"]["prompt_tokens_evaluated"], 20)

    def test_the_byte_ceiling_is_enforced(self):
        store = TelemetryStore(max_records=1000, max_bytes=8192)
        for i in range(200):
            r = RequestRecord(f"r{i}")
            r.set_native_cache(matched_prefix=1, reused_prefix=1, evaluated=1, non_prefix_reused=0)
            r.seal("completed", 200)
            store.add(r)
        self.assertLessEqual(store.summary()["retention"]["bytes"], 8192)

    def test_the_pagination_is_stable_under_new_records(self):
        store = TelemetryStore(max_records=100)
        for i in range(10):
            r = RequestRecord(f"r{i}")
            r.seal("completed", 200)
            store.add(r)
        first = store.list(limit=4)
        self.assertEqual(len(first["records"]), 4)
        # new records arrive while the caller is reading the pages
        for i in range(10, 20):
            r = RequestRecord(f"r{i}")
            r.seal("completed", 200)
            store.add(r)
        second = store.list(limit=4, cursor=first["next_cursor"])
        self.assertEqual(len(second["records"]), 4)
        seen = {d["identity"]["request_id"] for d in first["records"]} | \
               {d["identity"]["request_id"] for d in second["records"]}
        self.assertEqual(len(seen), 8)          # no record appears twice and none is skipped

    def test_a_bad_cursor_is_refused(self):
        store = TelemetryStore()
        with self.assertRaises(ValueError):
            store.list(cursor="not-a-cursor")

    def test_the_page_size_is_capped(self):
        store = TelemetryStore()
        for i in range(600):
            r = RequestRecord(f"r{i}")
            r.seal("completed", 200)
            store.add(r)
        page = store.list(limit=10_000)
        self.assertLessEqual(len(page["records"]), MAXIMUM_PAGE_SIZE)

    def test_a_record_is_finished_at_most_once(self):
        tel = ServerTelemetry()
        r = tel.begin()
        tel.finish(r, state="completed", http_status=200)
        self.assertIsNone(tel.finish(r, state="completed", http_status=200))
        self.assertEqual(tel.store.summary()["counters"]["requests_total"], 1)


class EngineFigures(unittest.TestCase):
    """The engine's own measurements, as they arrive on its DONE line."""

    def test_the_figures_are_taken_as_they_are(self):
        r = RequestRecord("abc")
        apply_engine(r, {"matched": 40, "reused": 40, "evaluated": 60, "work": 60, "replayed": 0,
                         "cache_source": "live", "cache_reason": "EXACT_MATCH", "restore": "none", "slot": 2})
        self.assertEqual(r.matched_prefix_tokens, 40)
        self.assertEqual(r.reused_prefix_tokens, 40)
        self.assertEqual(r.evaluated_tokens, 60)
        self.assertEqual(r.slot_id, 2)
        self.assertEqual(r.cache_source, "resident_slot")

    def test_a_missing_figure_stays_null(self):
        r = RequestRecord("abc")
        apply_engine(r, {"matched": 40})
        self.assertEqual(r.matched_prefix_tokens, 40)
        self.assertIsNone(r.evaluated_tokens)
        self.assertIn("prompt.evaluated_tokens", r.unavailable)
        # the MATCHED field too: an engine that did not report it says nothing, not zero
        r = RequestRecord("abc")
        apply_engine(r, {"evaluated": 60})
        self.assertIsNone(r.matched_prefix_tokens)
        self.assertNotEqual(r.matched_prefix_tokens, 0)
        self.assertIn("prompt.matched_prefix_tokens", r.unavailable)

    def test_no_figures_at_all_is_an_explicit_state(self):
        r = RequestRecord("abc")
        apply_engine(r, {})
        self.assertIsNone(r.matched_prefix_tokens)
        self.assertNotEqual(r.quality, COMPLETE)

    def test_a_failed_restore_is_not_a_successful_reuse(self):
        r = RequestRecord("abc")
        apply_engine(r, {"matched": 100, "reused": 0, "evaluated": 100, "restore": "failed"})
        self.assertFalse(r.cache_restore_succeeded)
        self.assertTrue(r.cache_restore_attempted)
        r.seal("completed", 200)
        self.assertEqual(r.cache_disposition, "match_without_usable_state")

    def test_a_successful_restore_is_reported_as_one(self):
        r = RequestRecord("abc")
        apply_engine(r, {"matched": 100, "reused": 100, "evaluated": 0, "restore": "succeeded"})
        self.assertTrue(r.cache_restore_succeeded)


class Evidence(unittest.TestCase):
    """The structured evidence: one metadata-only line per request, written by a background thread."""

    def test_the_evidence_is_one_line_per_request(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "evidence.jsonl"
            tel = ServerTelemetry(evidence_path=path)
            for i in range(3):
                r = tel.begin()
                r.set_native_cache(matched_prefix=1, reused_prefix=1, evaluated=1, non_prefix_reused=0)
                tel.finish(r, state="completed", http_status=200)
            tel.close()
            lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            self.assertEqual(len(lines), 3)
            for line in lines:
                self.assertEqual(validate(line), [])

    def test_the_evidence_carries_no_content(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "evidence.jsonl"
            tel = ServerTelemetry(evidence_path=path)
            r = tel.begin(client_request_id="abc")
            r.set_native_cache(matched_prefix=1, reused_prefix=1, evaluated=1, non_prefix_reused=0)
            tel.finish(r, state="completed", http_status=200)
            tel.close()
            raw = path.read_text()
            # the record has a "prompt" SECTION (the token counts); what must not be there is any CONTENT
            for forbidden in ("Authorization", "api_key", "Bearer", "reasoning_content", "tool_arguments",
                              "tool_calls", "content\":", "messages"):
                self.assertNotIn(forbidden, raw)
            # the record has no key that could hold a prompt or an answer
            record = json.loads(raw.splitlines()[0])
            # no key may hold the request's or the answer's CONTENT: the allowed names are the ones the schema
            # declares, and every value in the record is a count, a position, an id or a fixed word.
            allowed = {"rendered_tokens", "submitted_tokens", "matched_prefix_tokens", "reused_prefix_tokens",
                       "evaluated_tokens", "replayed_tokens", "non_prefix_reused_tokens", "evaluation_work_tokens",
                       "first_divergent_token_index", "source", "disposition", "reason_code", "restore_attempted",
                       "restore_succeeded", "restore_ms", "recurrent_state", "attention_state", "checkpoint_state",
                       "invalidations", "evictions", "request_id", "client_request_id", "engine_instance_id",
                       "server_instance_id", "engine_invocation_id", "engine_invocation_ordinal", "slot_id",
                       "model_id", "build_revision",
                       "state", "api", "received_at", "started_at", "finished_at", "http_status", "finish_reason",
                       "detail", "requested_max_output_tokens", "effective_max_output_tokens", "generated_tokens",
                       "emitted_tokens", "speculative_draft_tokens", "speculative_accepted_tokens",
                       "unavailable_fields", "timing_authority", "first_token_includes_reasoning",
                       "native_correlation", "native_partial", "measurement_valid", "aggregate_eligible",
                       "accounting", "schema_version", "seq"}
            for section in record.values():
                if isinstance(section, dict):
                    for key in section:
                        self.assertIn(key, allowed)

    def test_the_queue_is_bounded_and_drops_are_counted(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "evidence.jsonl"
            log = __import__("serve.reqtelemetry", fromlist=["EvidenceLog"]).EvidenceLog(path, queue_size=2)
            written = sum(log.write({"a": i}) for i in range(10))
            log.close()
            self.assertLessEqual(written, 3)            # the queue is bounded
            self.assertGreaterEqual(log.counters()["dropped"], 7)


class Cancelled(Http):
    """A request that was cut short: the record must say so, not report a success."""

    def test_a_cancelled_request_is_not_a_completed_one(self):
        self.engine.cancelling = True
        self.chat()
        _, body = self.get("/v1/telemetry/requests")
        self.assertEqual(len(body["records"]), 1)
        record = body["records"][0]
        self.assertNotEqual(record["lifecycle"]["state"], "completed")
        self.assertEqual(record["lifecycle"]["state"], "cancelled")
        self.assertNotEqual(record["measurement_quality"]["state"], "complete")


class Disabled(unittest.TestCase):
    """T19: with the telemetry off, the existing behaviour is preserved and nothing is kept."""

    def test_nothing_is_kept_when_the_telemetry_is_off(self):
        tel = ServerTelemetry()
        tel.enabled = False
        record = tel.begin()
        tel.finish(record, state="completed", http_status=200)
        self.assertEqual(tel.store.list()["records"], [])
        self.assertEqual(tel.store.summary()["counters"]["requests_total"], 0)

    def test_the_status_says_so(self):
        tel = ServerTelemetry()
        tel.enabled = False
        status = tel.status()
        self.assertFalse(status["enabled"])
        self.assertEqual(status["quality"], "unsupported")


class Identity(unittest.TestCase):
    """The identity on the wire: the server's id reaches the engine, and the engine's id comes back."""

    def test_the_request_key_carries_the_id_to_the_engine(self):
        from serve.server import StrataEngine
        self.assertEqual(StrataEngine.request_key("abc123"), " rid=abc123")
        self.assertEqual(StrataEngine.request_key(None), "")
        self.assertEqual(StrataEngine.request_key(""), "")

    def test_a_non_hex_id_is_not_sent(self):
        from serve.server import StrataEngine
        # the engine accepts hex only, so nothing else goes into the engine's output
        self.assertEqual(StrataEngine.request_key("not hex!"), "")
        self.assertEqual(StrataEngine.request_key("a" * 65), "")

    def test_the_engine_echoes_the_id_back_into_the_record(self):
        from serve.reqtelemetry import RequestRecord, apply_engine
        record = RequestRecord("the-server-id")
        apply_engine(record, {"rid": "the-server-id", "matched": 10})
        self.assertEqual(record.engine_invocation_id, "the-server-id")

    def test_two_attempts_with_one_client_id_are_two_stored_records(self):
        store = TelemetryStore()
        for i in range(2):
            r = RequestRecord(f"server-id-{i}", client_request_id="same")
            r.seal("completed", 200)
            store.add(r)
        self.assertEqual(len(store.list()["records"]), 2)


class Api(Http):
    """The telemetry API over HTTP."""

    def test_the_status_and_the_summary(self):
        code, body = self.get("/v1/telemetry/status")
        self.assertEqual(code, 200)
        self.assertIn("capabilities", body)
        self.assertIn("retention", body)
        code, body = self.get("/v1/telemetry/summary")
        self.assertEqual(code, 200)
        self.assertIn("counters", body)

    def test_a_request_appears_in_the_collection(self):
        self.chat()
        code, body = self.get("/v1/telemetry/requests")
        self.assertEqual(code, 200)
        self.assertEqual(len(body["records"]), 1)
        record = body["records"][0]
        self.assertEqual(validate(record), [])
        self.assertEqual(record["identity"]["request_id"], self.svc.telemetry_requests.store.records[0][1]["identity"]["request_id"])

    def test_the_engine_figures_reach_the_record(self):
        self.chat()
        _, body = self.get("/v1/telemetry/requests")
        record = body["records"][0]
        self.assertEqual(record["prompt"]["matched_prefix_tokens"], 40)
        self.assertEqual(record["prompt"]["reused_prefix_tokens"], 40)
        self.assertEqual(record["prompt"]["evaluated_tokens"], 60)

    def test_one_request_by_its_id(self):
        self.chat()
        _, body = self.get("/v1/telemetry/requests")
        request_id = body["records"][0]["identity"]["request_id"]
        code, one = self.get(f"/v1/telemetry/requests/{request_id}")
        self.assertEqual(code, 200)
        self.assertEqual(one["identity"]["request_id"], request_id)

    def test_an_unknown_request_id_is_a_404(self):
        code, body = self.get("/v1/telemetry/requests/deadbeef")
        self.assertEqual(code, 404)
        self.assertIn("error", body)

    def test_the_page_size_is_capped(self):
        code, body = self.get("/v1/telemetry/requests?limit=100000")
        self.assertEqual(code, 400)
        code, body = self.get("/v1/telemetry/requests?limit=0")
        self.assertEqual(code, 400)

    def test_a_bad_cursor_is_a_400(self):
        code, body = self.get("/v1/telemetry/requests?cursor=nonsense")
        self.assertEqual(code, 400)

    def test_the_filters_work(self):
        self.chat(text="one")
        self.chat(text="two")
        _, body = self.get("/v1/telemetry/requests?cache_disposition=partial_hit")
        self.assertTrue(all(d["cache"]["disposition"] == "partial_hit" for d in body["records"]))
        _, body = self.get("/v1/telemetry/requests?request_status=completed")
        self.assertTrue(all(d["lifecycle"]["state"] == "completed" for d in body["records"]))
        _, body = self.get("/v1/telemetry/requests?request_status=cancelled")
        self.assertEqual(body["records"], [])

    def test_the_client_id_finds_the_requests(self):
        self.chat_with("client-abc")
        _, body = self.get("/v1/telemetry/requests?client_request_id=client-abc")
        self.assertEqual(len(body["records"]), 1)
        self.assertEqual(body["records"][0]["identity"]["client_request_id"], "client-abc")

    def test_two_requests_with_the_same_client_id_are_two_records(self):
        self.chat_with("same")
        self.chat_with("same")
        _, body = self.get("/v1/telemetry/requests?client_request_id=same")
        self.assertEqual(len(body["records"]), 2)
        ids = {d["identity"]["request_id"] for d in body["records"]}
        self.assertEqual(len(ids), 2)

    def test_the_request_id_is_echoed(self):
        code, body, headers = self.chat()
        self.assertEqual(code, 200)
        self.assertIn("X-Strata-Request-ID", headers)
        _, listed = self.get("/v1/telemetry/requests")
        self.assertEqual(listed["records"][0]["identity"]["request_id"], headers["X-Strata-Request-ID"])

    def test_the_response_never_carries_the_prompt_or_the_answer(self):
        self.chat(text="a-very-secret-prompt")
        _, body = self.get("/v1/telemetry/requests")
        raw = json.dumps(body)
        self.assertNotIn("a-very-secret-prompt", raw)

    def test_the_telemetry_carries_no_content_at_all(self):
        self.chat(text="another-secret")
        _, body = self.get("/v1/telemetry/requests")
        record = body["records"][0]
        raw = json.dumps(record)
        for forbidden in ("another-secret", "Authorization", "api_key", "Bearer"):
            self.assertNotIn(forbidden, raw)


class Access(unittest.TestCase):
    """The access control: the request-level endpoints fail closed when there is no key on a shared listener."""

    def setUp(self):
        import threading
        self.samplers_before = sum(1 for t in threading.enumerate() if t.name.endswith("(_loop)"))
        self.httpd = None
        self.tok = ByteTokenizer()
        self.svc = Service(MockEngine(self.tok, "ok", max_context=CTX), self.tok,
                           ChatTemplate(ROOT / "serve/chat_template.jinja"))

    def tearDown(self):
        import threading
        import time
        if getattr(self, "httpd", None) is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            for _ in range(50):
                if sum(1 for t in threading.enumerate() if t.name.endswith("(_loop)")) <= getattr(
                        self, "samplers_before", 0):
                    break
                time.sleep(0.1)

    def test_a_shared_listener_without_a_key_refuses_the_request_metadata(self):
        self.svc.api_key = ""
        self.httpd = serve(self.svc, host="0.0.0.0", port=0)
        base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        try:
            with urllib.request.urlopen(base + "/v1/telemetry/requests", timeout=30) as r:
                self.fail(f"the telemetry answered without a key: {r.status}")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 403)

    def test_a_shared_listener_with_a_key_needs_it(self):
        self.svc.api_key = "secret"
        self.httpd = serve(self.svc, host="0.0.0.0", port=0)
        base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        try:
            with urllib.request.urlopen(base + "/v1/telemetry/requests", timeout=30) as r:
                self.fail(f"the telemetry answered without the key: {r.status}")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 401)
        req = urllib.request.Request(base + "/v1/telemetry/requests", headers={"Authorization": "Bearer secret"})
        with urllib.request.urlopen(req, timeout=30) as r:
            self.assertEqual(r.status, 200)

    def test_the_loopback_listener_keeps_the_server_own_trust(self):
        self.svc.api_key = ""
        self.httpd = serve(self.svc, port=0)
        base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        with urllib.request.urlopen(base + "/v1/telemetry/requests", timeout=30) as r:
            self.assertEqual(r.status, 200)


if __name__ == "__main__":
    unittest.main()
