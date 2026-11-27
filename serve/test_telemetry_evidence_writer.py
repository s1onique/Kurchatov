#!/usr/bin/env python3
"""serve/test_telemetry_evidence_writer.py - the ACTUAL evidence-writing boundary (ACT-...-AMENDMENT-01, A5a).

The evidence writer is the boundary where a telemetry record becomes a JSONL line on the disk.  A record that
carries a value JSON cannot represent - a NaN, a positive infinity, a negative infinity - must be REFUSED there
and counted in the writer's own serialization-refusal domain.  It must never reach the disk as the bare token
`NaN`, `Infinity` or `-Infinity`: those are not JSON, and no strict reader accepts them.

These witnesses drive the REAL writer (`serve.reqtelemetry.evidence.EvidenceLog.write`), not a stand-in:

    NONFINITE_JSONL_ACCEPTED   a NaN / +Infinity / -Infinity record is refused at the writer;
    STRICT_JSONL               what IS written is valid UTF-8 and strict JSON;
    WRITER_CONSERVATION         the writer's counter domains still balance after a refusal;
    STRICT_JSON_HTTP            the HTTP telemetry boundary serves strict JSON too.

    python -m unittest serve.test_telemetry_evidence_writer -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serve.reqtelemetry.evidence import EvidenceLog  # noqa: E402


def _strict_loads(text: str):
    """Parse JSON the way a STRICT reader does: the non-finite literals are an error, not a value.

    `json.loads` accepts `NaN`, `Infinity` and `-Infinity` by default.  `parse_constant` is the hook that turns
    them into an error, which is what a reader that follows the JSON specification does.
    """
    def refuse(token):
        raise ValueError(f"{token} is not JSON")

    return json.loads(text, parse_constant=refuse)


class StrictJsonBoundary(unittest.TestCase):
    """A5a: the strict JSON boundary at the ACTUAL evidence-writing boundary."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "evidence.jsonl"

    def tearDown(self):
        self.folder.cleanup()

    def _written_lines(self) -> list:
        if not self.path.exists():
            return []
        raw = self.path.read_bytes()
        # the file must be valid UTF-8: a byte sequence that is not UTF-8 is not a JSONL file
        text = raw.decode("utf-8")
        return [line for line in text.splitlines() if line.strip()]

    def test_a_nan_record_is_refused_by_the_writer(self):
        """NONFINITE_JSONL_ACCEPTED: a NaN never reaches the disk."""
        log = EvidenceLog(self.path)
        try:
            accepted = log.write({"schema_version": "strata.request-telemetry/2", "x": float("nan")})
        finally:
            log.close()
        self.assertFalse(accepted, "a record with a NaN was accepted by the writer")
        counters = log.counters()
        self.assertEqual(counters["serialization_refusals"], 1)
        self.assertEqual(counters["refused_records"], 1)
        self.assertEqual(counters["written_records"], 0)
        self.assertEqual(self._written_lines(), [], "the refused record reached the disk")

    def test_a_positive_infinity_record_is_refused_by_the_writer(self):
        """NONFINITE_JSONL_ACCEPTED: +Infinity never reaches the disk."""
        log = EvidenceLog(self.path)
        try:
            accepted = log.write({"x": float("inf")})
        finally:
            log.close()
        self.assertFalse(accepted)
        self.assertEqual(log.counters()["serialization_refusals"], 1)
        self.assertEqual(self._written_lines(), [])

    def test_a_negative_infinity_record_is_refused_by_the_writer(self):
        """NONFINITE_JSONL_ACCEPTED: -Infinity never reaches the disk."""
        log = EvidenceLog(self.path)
        try:
            accepted = log.write({"x": float("-inf")})
        finally:
            log.close()
        self.assertFalse(accepted)
        self.assertEqual(log.counters()["serialization_refusals"], 1)
        self.assertEqual(self._written_lines(), [])

    def test_the_non_finite_record_is_refused_wherever_it_sits(self):
        """The refusal is about the RECORD, not about one field's place in it."""
        log = EvidenceLog(self.path)
        try:
            for record in ({"a": {"b": [1.0, float("nan")]}},
                           {"timing_ms": {"prefill_wall": float("inf")}},
                           {"timing_ms": {"prefill_wall": float("-inf")}}):
                self.assertFalse(log.write(record))
        finally:
            log.close()
        counters = log.counters()
        self.assertEqual(counters["serialization_refusals"], 3)
        self.assertEqual(counters["refused_records"], 3)
        self.assertEqual(self._written_lines(), [])

    def test_a_valid_record_is_strict_json_on_the_disk(self):
        """STRICT_JSONL: what IS written is valid UTF-8 and strict JSON."""
        log = EvidenceLog(self.path)
        try:
            self.assertTrue(log.write({"schema_version": "strata.request-telemetry/2", "name": "café",
                                        "count": 3, "ratio": 0.5, "nothing": None}))
        finally:
            log.close()
        lines = self._written_lines()
        self.assertEqual(len(lines), 1)
        parsed = _strict_loads(lines[0])
        self.assertEqual(parsed["name"], "café")
        self.assertEqual(parsed["count"], 3)
        self.assertIsNone(parsed["nothing"])

    def test_the_written_line_carries_no_non_finite_token(self):
        """STRICT_JSONL: the line itself never contains `NaN`, `Infinity` or `-Infinity`."""
        log = EvidenceLog(self.path)
        try:
            self.assertTrue(log.write({"x": 1.5, "y": None}))
        finally:
            log.close()
        raw = self.path.read_text(encoding="utf-8")
        for token in ("NaN", "Infinity"):
            self.assertNotIn(token, raw)

    def test_the_writer_conserves_its_counter_domains_after_a_refusal(self):
        """WRITER_CONSERVATION: a refusal is counted in its own domain and nothing is lost."""
        log = EvidenceLog(self.path)
        try:
            self.assertTrue(log.write({"x": 1}))
            self.assertFalse(log.write({"x": float("nan")}))
            self.assertTrue(log.write({"x": 2}))
        finally:
            log.close()
        counters = log.counters()
        self.assertEqual(counters["submitted_records"], 3)
        self.assertEqual(counters["pending_records"], 0)
        self.assertEqual(counters["accepted_records"], 2)
        self.assertEqual(counters["refused_records"], 1)
        self.assertEqual(counters["serialization_refusals"], 1)
        self.assertEqual(counters["written_records"], 2)
        self.assertEqual(counters["outstanding_records"], 0)
        # submitted = accepted + refused + pending, and accepted = written + failed + outstanding
        self.assertEqual(counters["submitted_records"],
                         counters["accepted_records"] + counters["refused_records"] + counters["pending_records"])
        self.assertEqual(counters["accepted_records"],
                         counters["written_records"] + counters["failed_records"]
                         + counters["outstanding_records"])
        self.assertEqual(len(self._written_lines()), 2)

    def test_a_refused_record_does_not_disturb_the_records_around_it(self):
        """The refusals are per record: the valid ones around them are still written."""
        log = EvidenceLog(self.path)
        try:
            self.assertTrue(log.write({"x": 1}))
            self.assertFalse(log.write({"x": float("nan")}))
            self.assertTrue(log.write({"x": 2}))
            self.assertFalse(log.write({"x": float("inf")}))
            self.assertTrue(log.write({"x": 3}))
        finally:
            log.close()
        lines = self._written_lines()
        self.assertEqual([_strict_loads(line)["x"] for line in lines], [1, 2, 3])
        self.assertEqual(log.counters()["serialization_refusals"], 2)


class StrictJsonHttp(unittest.TestCase):
    """A5a: the HTTP telemetry boundary serves strict JSON as well."""

    def test_the_telemetry_payload_is_strict_json_by_construction(self):
        """STRICT_JSON_HTTP: the body the HTTP telemetry endpoints serve is strict JSON.

        The endpoints serve the store's own records and summary.  A strict reader must accept every one of
        them, so the payload is serialized with `allow_nan=False` here: a value that a strict reader would
        reject is a defect of the payload, and this witness finds it.
        """
        from serve.reqtelemetry import RequestRecord, ServerTelemetry, TelemetryStore, apply_engine, new_invocation_id

        tel = ServerTelemetry()
        record = tel.begin(model_id="m")
        record.set_prompt_tokens(rendered=100, submitted=100)
        invocation = new_invocation_id()
        record.begin_invocation(invocation, ordinal=1)
        record.invocation_for(invocation).submitted_tokens = 100
        apply_engine(record, {"rid": invocation, "matched": 90, "reused": 90, "evaluated": 10,
                              "work": 10, "lookup_ms": 5.0}, expected_invocation_id=invocation)
        data = tel.finish(record, state="completed", http_status=200)
        # the record as the HTTP endpoint serves it
        json.dumps(data, allow_nan=False)
        for line in json.dumps(data, allow_nan=False).splitlines():
            if line.strip():
                _strict_loads(line)
        # the summary as the HTTP endpoint serves it
        summary = tel.store.summary()
        json.dumps(summary, allow_nan=False)
        for line in json.dumps(summary, allow_nan=False).splitlines():
            if line.strip():
                _strict_loads(line)
        # a record that was never measured keeps its fields null - and a null is strict JSON
        empty = RequestRecord("r2")
        empty.seal("completed", 200)
        json.dumps(empty.to_dict(), allow_nan=False)

    def test_the_http_telemetry_body_is_strict_json(self):
        """STRICT_JSON_HTTP: the served telemetry body parses with a strict reader."""
        import urllib.request
        try:
            from serve.server import ByteTokenizer, MockEngine, Service, serve
        except ImportError as e:                    # the server's own dependency (jinja2) is not installed here
            raise unittest.SkipTest(f"the server's dependencies are not installed: {e}")

        class Engine(MockEngine):
            def __init__(self, tok):
                super().__init__(tok, "ok", max_context=4096)
                self.last = {}

        tok = ByteTokenizer()
        # no chat template: the telemetry endpoints do not need one, and the test must not depend on jinja2
        service = Service(Engine(tok), tok, None)
        httpd = serve(service, port=0)
        try:
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            body = urllib.request.urlopen(base + "/v1/telemetry/summary", timeout=30).read().decode("utf-8")
            self.assertIn("counters", _strict_loads(body))
            body = urllib.request.urlopen(base + "/v1/telemetry/requests", timeout=30).read().decode("utf-8")
            self.assertIn("records", _strict_loads(body))
        finally:
            httpd.shutdown()
            httpd.server_close()


class NonFiniteRecord(unittest.TestCase):
    """A5a: the whole path - a record that carries a non-finite value is refused by the writer."""

    def test_a_record_with_a_non_finite_value_never_reaches_the_disk(self):
        """NONFINITE_JSONL_ACCEPTED: the real record path, end to end."""
        from serve.reqtelemetry import ServerTelemetry

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "evidence.jsonl"
            tel = ServerTelemetry(evidence_path=path)
            record = tel.begin()
            # the typed admission refuses the NaN at the record's own boundary, so the field stays null
            record.set_timing("prefill_wall", float("nan"), "native_engine")
            self.assertIsNone(record.timing.get("prefill_wall"))
            tel.finish(record, state="completed", http_status=200)
            tel.close()
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("NaN", raw)
            for line in raw.splitlines():
                if line.strip():
                    _strict_loads(line)         # the line is strict JSON


class NonVacuity(unittest.TestCase):
    """A7: the witnesses have teeth - they FAIL when the correction is reversed.

    The reversal is done IN MEMORY ONLY: the writer's serializer is replaced by one that accepts the
    non-finite literals again.  Nothing is written to the repository's files and the replacement is undone
    when the test ends.
    """

    def test_the_witnesses_fail_when_the_strict_boundary_is_reversed(self):
        """NONFINITE_JSONL_ACCEPTED: without `allow_nan=False` the writer accepts the record again."""
        import types
        from serve.reqtelemetry import evidence as evidence_module

        real_dumps = json.dumps

        class _LenientJSON(types.ModuleType):
            """A stand-in for the json module whose `dumps` ignores `allow_nan`."""

            def dumps(self, obj, **kwargs):
                kwargs.pop("allow_nan", None)
                return real_dumps(obj, **kwargs)

            def __getattr__(self, name):
                return getattr(json, name)

        original = evidence_module.json
        evidence_module.json = _LenientJSON("json")
        try:
            log = EvidenceLog(self.path())
            try:
                accepted = log.write({"x": float("nan")})
            finally:
                log.close()
            # the reversed writer ACCEPTS the record - so the witness above would fail
            self.assertTrue(accepted, "the reversed writer did not accept the record: the witness is vacuous")
        finally:
            evidence_module.json = original

    def path(self):
        return Path(self.folder.name) / "evidence.jsonl"

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.folder.cleanup()


if __name__ == "__main__":
    unittest.main()
