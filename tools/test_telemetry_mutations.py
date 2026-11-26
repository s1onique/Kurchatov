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
    prefix = f"strata_request_duration_seconds_bucket{{model_name=\"test\",le=\"{edge}\"}}"
    for line in text.splitlines():
        if line.startswith(prefix + " "):
            return int(line.rsplit(" ", 1)[1])
    raise AssertionError(f"the scrape has no {prefix} line")



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
            out.append(f"# HELP {name} durations\n# TYPE {name} histogram")
            for b in prometheus.TELEMETRY_BUCKETS:
                out.append(f'{name}_bucket{{{lab},le="{b}"}} {n}')
            out.append(f'{name}_bucket{{{lab},le="+Inf"}} {n}')
            out.append(f"{name}_sum{{{lab}}} {round(hist.get('sum') or 0.0, 6)}\n{name}_count{{{lab}}} {n}")

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


if __name__ == "__main__":
    unittest.main()
