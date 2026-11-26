#!/usr/bin/env python3
"""tools/test_telemetry_mutations.py - the non-vacuity witnesses of
ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-01 (G10).

Each witness here reverses ONE correction, in memory only, and shows that the witness that guards it FAILS without
the correction.  Nothing is written to the repository's files: the reversal is a patch of the running process, and
it is undone when the test ends.  No mutation code is left in the production tree.

    python tools/test_telemetry_mutations.py
"""
from __future__ import annotations

import contextlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serve import prometheus  # noqa: E402
from serve.reqtelemetry import RequestRecord, ServerTelemetry, TelemetryStore  # noqa: E402
from serve.reqtelemetry import accounting, correlation, metrics, store  # noqa: E402


@contextlib.contextmanager
def patched(obj, name, replacement):
    """Replace one attribute for the duration of the block, and put it back afterwards."""
    old = getattr(obj, name)
    setattr(obj, name, replacement)
    try:
        yield
    finally:
        setattr(obj, name, old)


def _store_with(*durations_ms):
    """A store with one record per duration (milliseconds)."""
    store = TelemetryStore()
    for i, ms in enumerate(durations_ms):
        record = RequestRecord(f"r{i}")
        record.set_timing("total", ms, "http_server")
        store.add(record.seal("completed", 200))
    return store


def _scrape(store) -> str:
    summary = store.summary()
    summary["inflight"] = 0
    summary["enabled"] = True
    metrics_json = {"engine": {"model": "test"}, "live": {}, "totals": {}, "hardware": {}, "requests": [],
                    "telemetry": summary}
    lat = {"ttft": ([0] * len(prometheus.BUCKETS), 0.0, 0),
           "itl": ([0] * len(prometheus.BUCKETS), 0.0, 0),
           "e2e": ([0] * len(prometheus.BUCKETS), 0.0, 0)}
    return prometheus.render(metrics_json, lat)


def _bucket(text: str, edge: str) -> int:
    """The value of one histogram bucket line of the scrape.

    ACT-...-AMENDMENT-02 (A8): the canonical telemetry metrics are process-scoped: they carry no model_name
    label.  The witness accepts both shapes so it also works against the predecessor's exporter.
    """
    for prefix in (f"strata_request_duration_seconds_bucket{{le=\"{edge}\"}}",
                   f"strata_request_duration_seconds_bucket{{model_name=\"test\",le=\"{edge}\"}}"):
        for line in text.splitlines():
            if line.startswith(prefix + " "):
                return int(line.rsplit(" ", 1)[1])
    raise AssertionError(f"the scrape has no bucket line for {edge}")



def _run_witness(case, name):
    """Run ONE witness of the amendment-02 suite and let its assertion failure through.

    TestCase.run() swallows the failure (it records it), so the witness is called directly: the mutation must
    make it fail, and the failure must reach the caller.
    """
    case.setUp()
    try:
        getattr(case, name)()
    finally:
        case.tearDown()


class Mutations(unittest.TestCase):
    """Every witness fails when its correction is reversed."""

    def test_the_histogram_buckets_are_not_fabricated(self):
        """HISTOGRAM_BUCKET_FABRICATION: every bucket carrying the total count."""

        def fabricated(tel, out, lab):
            """The exporter of the predecessor: every bucket says the total count."""
            histograms = tel.get("histograms") or {}
            name, key = "strata_request_duration_seconds", "request_duration"
            hist = histograms.get(key) or {}
            n = hist.get("count")
            if not isinstance(n, int) or n <= 0:
                return
            label_set = f"{lab}," if lab else ""
            out.append(f"# HELP {name} durations\n# TYPE {name} histogram")
            for b in prometheus.TELEMETRY_BUCKETS:
                out.append(f'{name}_bucket{{{label_set}le="{b}"}} {n}')
            out.append(f'{name}_bucket{{{label_set}le="+Inf"}} {n}')
            if lab:
                out.append(f"{name}_sum{{{lab}}} {round(hist.get('sum') or 0.0, 6)}\n{name}_count{{{lab}}} {n}")
            else:
                out.append(f"{name}_sum {round(hist.get('sum') or 0.0, 6)}\n{name}_count {n}")

        with patched(prometheus, "telemetry", fabricated):
            text = _scrape(_store_with(2000, 20000, 120000))
        # the witness: a 120 s observation is NOT in the 1 s bucket
        self.assertNotEqual(_bucket(text, "1.0"), 0, "the fabricated exporter passes the witness")

    def test_the_histogram_unit_is_converted(self):
        """HISTOGRAM_UNIT_CONVERSION_REMOVED: the milliseconds exported as seconds."""

        def unconverted(histograms, metric, milliseconds):
            if not isinstance(milliseconds, (int, float)) or isinstance(milliseconds, bool):
                return False
            hist = histograms.setdefault(metric, {"sum": 0.0, "n": 0,
                                                  "buckets": [0] * len(metrics.DURATION_BUCKETS)})
            hist["sum"] += float(milliseconds)          # no conversion: the milliseconds are the seconds
            hist["n"] += 1
            for i, edge in enumerate(metrics.DURATION_BUCKETS):
                if float(milliseconds) <= edge:
                    hist["buckets"][i] += 1
            return True

        with patched(store, "observe_duration", unconverted):
            mutated = _store_with(2000, 20000, 120000)
            summary = mutated.summary()
        self.assertNotAlmostEqual(summary["histograms"]["request_duration"]["sum"], 142.0, places=3,
                                   msg="the unconverted exporter passes the witness")


    def test_a_foreign_native_id_is_not_accepted(self):
        """FOREIGN_NATIVE_ID_ACCEPTED: a receipt of another request attached to this one."""
        real = correlation.apply_engine

        def accepting(record, figures):
            record.engine_invocation_id = figures.get("rid") or record.engine_invocation_id
            return real(record, {k: v for k, v in (figures or {}).items() if k != "rid"})

        record = RequestRecord("abc123")
        with patched(correlation, "apply_engine", accepting):
            correlation.apply_engine(record, {"rid": "somebody-else", "matched": 40})
        self.assertEqual(record.matched_prefix_tokens, 40,
                         "the accepting correlation passes the witness")

    def test_a_null_reuse_is_not_a_zero(self):
        """NULL_REUSE_INTERPRETED_AS_ZERO: an unmeasured reuse read as a measured zero."""
        real = accounting.derive_disposition

        def truthy(record):
            matched, reused = record.matched_prefix_tokens, record.reused_prefix_tokens
            if matched is None and reused is None:
                return "unknown"
            if matched is not None and matched > 0 and not reused:   # the bug: None is a zero here
                return "match_without_usable_state"
            return real(record)

        record = RequestRecord("abc")
        record.set_native_cache(matched_prefix=90)
        with patched(accounting, "derive_disposition", truthy):
            disposition = accounting.derive_disposition(record)
        self.assertNotEqual(disposition, "unknown",
                            "the truthy disposition passes the witness")

    def test_the_conservation_identity_is_checked(self):
        """CONSERVATION_CHECK_BYPASSED: the identity never checked, so a broken accounting looks complete."""
        record = RequestRecord("abc")
        record.set_prompt_tokens(rendered=100, submitted=100)
        record.set_native_cache(matched_prefix=90, reused_prefix=90, evaluated=8)
        with patched(accounting, "conservation", lambda record: []):
            record.seal("completed", 200)
        self.assertNotEqual(record.quality, "partial",
                            "the unchecked accounting passes the witness")

    def test_the_output_budget_is_wired(self):
        """OUTPUT_BUDGET_NOT_WIRED: the requested budget never reaches the record."""
        real = RequestRecord.set_generation

        def not_wired(self, *, requested_max=None, effective_max=None, generated=None, emitted=None,
                      draft_tokens=None, accepted_tokens=None, finish_reason=None):
            return real(self, effective_max=effective_max, generated=generated, emitted=emitted,
                        draft_tokens=draft_tokens, accepted_tokens=accepted_tokens, finish_reason=finish_reason)

        record = RequestRecord("abc")
        with patched(RequestRecord, "set_generation", not_wired):
            record.set_generation(requested_max=1000)
        self.assertIsNone(record.requested_max_output_tokens,
                          "the unwired budget passes the witness")

    def test_a_duration_is_not_a_wall_clock_difference(self):
        """WALL_CLOCK_USED_FOR_DURATION: the duration taken from two wall-clock timestamps."""
        import time as _time

        real = ServerTelemetry.finish

        def wall_clock(self, rec, state=None, http_status=None, finish_reason=None, detail=None):
            rec.set_timing("total", (_time.time() - rec.clock) * 1000.0, "http_server")
            return real(self, rec, state=state, http_status=http_status, finish_reason=finish_reason,
                        detail=detail)

        tel = ServerTelemetry()
        rec = tel.begin()
        rec.clock = _time.time() - 3600            # an hour "ago", in wall-clock seconds
        with patched(ServerTelemetry, "finish", wall_clock):
            tel.finish(rec, state="completed", http_status=200)
        data = tel.store.list()["records"][0]
        self.assertGreater(data["timing_ms"]["total"], 3_600_000,
                           "the wall-clock duration passes the witness")

    def test_a_terminal_receipt_is_not_lost(self):
        """TERMINAL_RECEIPT_LOST: the record never reaches the store."""
        real = ServerTelemetry.finish

        def losing(self, record, state=None, http_status=None, finish_reason=None, detail=None):
            with self.lock:
                self._records.pop(record.request_id, None)
            return None

        tel = ServerTelemetry()
        rec = tel.begin()
        with patched(ServerTelemetry, "finish", losing):
            tel.finish(rec, state="completed", http_status=200)
        self.assertEqual(tel.store.list()["records"], [],
                         "the lost receipt passes the witness")

    # ---------------------------------------------------------------- the AMENDMENT-02 witnesses
    def test_the_queue_duration_is_not_overwritten(self):
        """QUEUE_DURATION_OVERWRITTEN: the finalization overwrites the queue wait with the request time.

        The witness is the PRODUCTION path of serve/test_telemetry_amendment02.py: two real HTTP requests, the
        second one waiting for its turn.
        """
        import time as _time

        from serve import server as server_module
        from serve.test_telemetry_amendment02 import HttpWitnesses

        real = server_module.Service._finish_telemetry

        def overwriting(self, tele, last, seen, submitted, generated, finish, started, emitted=None,
                        queue_s=None, first_token_s=None, invocations=1):
            if tele is not None:
                # the defect: the queue wait becomes the time the request spent running
                tele.set_timing("queue", (_time.perf_counter() - tele.clock) * 1000.0, "http_server")
            return real(self, tele, last, seen, submitted, generated, finish, started, emitted=emitted,
                        queue_s=queue_s, first_token_s=first_token_s, invocations=invocations)

        with patched(server_module.Service, "_finish_telemetry", overwriting):
            case = HttpWitnesses("test_the_queue_wait_is_the_wait_and_not_the_whole_request")
            with self.assertRaises(AssertionError):
                _run_witness(case, "test_the_queue_wait_is_the_wait_and_not_the_whole_request")

    def test_the_first_content_is_not_the_generation_observation(self):
        """HTTP_FIRST_TOKEN_MISATTRIBUTED: the first token is the generation loop's, not the first byte written."""
        from serve import server as server_module
        from serve.test_telemetry_amendment02 import HttpWitnesses

        real = server_module.Service._finish_telemetry

        def misattributing(self, tele, last, seen, submitted, generated, finish, started, emitted=None,
                           queue_s=None, first_token_s=None, invocations=1):
            if tele is not None and first_token_s is not None:
                # the defect: the service's observation is published as the HTTP first-content time
                tele.set_timing("http_first_token", float(first_token_s) * 1000.0, "http_server")
            return real(self, tele, last, seen, submitted, generated, finish, started, emitted=emitted,
                        queue_s=queue_s, first_token_s=first_token_s, invocations=invocations)

        with patched(server_module.Service, "_finish_telemetry", misattributing):
            case = HttpWitnesses("test_the_first_content_is_timed_at_the_write_boundary")
            with self.assertRaises(AssertionError):
                _run_witness(case, "test_the_first_content_is_timed_at_the_write_boundary")

    def test_the_invocation_id_is_not_reused(self):
        """INVOCATION_ID_REUSED: every dispatch gets its own invocation id."""
        from serve import reqtelemetry as rt
        from serve.test_telemetry_amendment02 import HttpWitnesses

        def constant():
            return "0123456789abcdef0123456789abcdef"

        with patched(rt, "new_invocation_id", constant):
            case = HttpWitnesses("test_two_requests_never_share_an_invocation_id")
            with self.assertRaises(AssertionError):
                _run_witness(case, "test_two_requests_never_share_an_invocation_id")

    def test_the_flush_does_not_return_while_the_writer_is_busy(self):
        """FLUSH_RETURNS_WHILE_WRITER_BUSY: the flush ignores the record the writer is writing."""
        from serve.reqtelemetry import evidence as evidence_module
        from serve.test_telemetry_amendment02 import EvidenceWriter

        real = evidence_module.EvidenceLog.flush

        def busy_flush(self, timeout=2.0):
            # the defect: only the QUEUE is looked at, the record being written is not
            with self.lock:
                if not self.queue:
                    return True
            return real(self, timeout)

        with patched(evidence_module.EvidenceLog, "flush", busy_flush):
            case = EvidenceWriter("test_a_blocked_writer_is_not_flushed")
            with self.assertRaises(AssertionError):
                _run_witness(case, "test_a_blocked_writer_is_not_flushed")


if __name__ == "__main__":
    unittest.main()
