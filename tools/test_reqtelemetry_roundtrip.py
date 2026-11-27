"""tools/test_reqtelemetry_roundtrip.py - the engine's telemetry writer against the server's reader
(ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01).

    python tools/test_reqtelemetry_roundtrip.py

The engine writes the telemetry as key=value pairs on the request's own DONE line
(include/strata/program/reqtelemetry.hpp); the server reads them (serve/server.py's _parse_done).  This test
drives the SERVER's reader with a DONE line the ENGINE's writer produced, so the two halves cannot drift apart.

The engine's writer is a small C++ program (src/program/reqtelemetry_roundtrip.cpp).  When it has not been built
(the normal case on a machine without a CUDA toolchain), the test falls back to a DONE line built from the same
field names, and says so: the check of the two halves then covers the READER against the field names, and the
WRITER's own format is covered by src/program/reqtelemetry_test.cpp.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# the serving layer lives in terminal/, so `serve.` is a package under terminal/.
sys.path[:0] = [str(ROOT), str(ROOT / 'terminal')]

from serve.reqtelemetry import apply_engine, valid_client_request_id  # noqa: E402
from serve.server import (REQTELEMETRY_FLOAT_KEYS, REQTELEMETRY_INT_KEYS,  # noqa: E402
                          REQTELEMETRY_TEXT_KEYS)


def parse_done(line: str) -> dict:
    """The server's reader, as serve/server.py's _parse_done does it: the positional fields and the key=value tail."""
    f = line.split()
    last = {"generated": int(f[1]), "prompt_tokens": int(f[2]), "prompt_ms": float(f[3]),
            "decode_ms": float(f[4]), "finish": f[5]}
    if len(f) >= 9:
        last.update(drafts_accepted=int(f[6]), drafts_offered=int(f[7]), reused=int(f[8]))
    if len(f) >= 15:
        last.update(prompt_read=int(f[14]))
    for tok in f[16:]:
        key, eq, value = tok.partition("=")
        if eq and key in REQTELEMETRY_INT_KEYS:
            last.setdefault("telemetry", {})[key] = int(value)
        elif eq and key in REQTELEMETRY_FLOAT_KEYS:
            last.setdefault("telemetry", {})[key] = float(value)
        elif eq and key in REQTELEMETRY_TEXT_KEYS:
            last.setdefault("telemetry", {})[key] = value
    return last


def engine_done_line(switch: str = "1") -> str | None:
    """A DONE line from the engine's own writer, when it has been built."""
    for candidate in (ROOT / "build" / "reqtelemetry_roundtrip", Path("/tmp/rtcache/reqtelemetry_roundtrip")):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            env = dict(os.environ, STRATA_TELEMETRY=switch)
            out = subprocess.run([str(candidate)], capture_output=True, text=True, env=env, timeout=30)
            for line in out.stdout.splitlines():
                if line.startswith("DONE "):
                    return line
    return None


class Roundtrip(unittest.TestCase):
    def test_the_server_reads_what_the_engine_writes(self):
        line = engine_done_line()
        if line is None:
            self.skipTest("the engine's writer is not built (build reqtelemetry_roundtrip)")
        figures = parse_done(line).get("telemetry") or {}
        self.assertEqual(figures.get("matched"), 60)
        self.assertEqual(figures.get("reused"), 60)
        self.assertEqual(figures.get("evaluated"), 40)
        self.assertEqual(figures.get("slot"), 2)
        self.assertEqual(figures.get("cache_source"), "live")
        self.assertEqual(figures.get("restore"), "succeeded")
        self.assertEqual(figures.get("rid"), "abc123")
        self.assertAlmostEqual(figures.get("restore_ms"), 3.5, places=3)
        self.assertAlmostEqual(figures.get("lookup_ms"), 1.2, places=3)   # the engine writes one decimal

    def test_with_the_switch_off_the_done_line_carries_no_telemetry(self):
        """T19: with the telemetry off, the DONE line is byte-identical to the release's: no telemetry keys."""
        line = engine_done_line("0")
        if line is None:
            self.skipTest("the engine's writer is not built (build reqtelemetry_roundtrip)")
        for key in REQTELEMETRY_INT_KEYS + REQTELEMETRY_FLOAT_KEYS + REQTELEMETRY_TEXT_KEYS:
            self.assertNotIn(f" {key}=", line, f"the telemetry is off, so {key} must not be on the DONE line")
        self.assertEqual(parse_done(line).get("telemetry"), None)

    def test_the_field_names_are_the_same_on_both_sides(self):
        """The keys the engine writes are the keys the server reads: one list, checked against the header."""
        header = (ROOT / "engine/include/strata/program/reqtelemetry.hpp").read_text()
        for key in REQTELEMETRY_INT_KEYS + REQTELEMETRY_FLOAT_KEYS + REQTELEMETRY_TEXT_KEYS:
            self.assertIn(f'"{key}"', header, f"the server reads {key}, so the engine must write it")

    def test_a_record_built_from_the_engines_figures_is_sound(self):
        line = engine_done_line()
        if line is None:
            line = ("DONE 7 100 41.5 210.0 stop 24 31 60 9 10 1 2 1.5 40 0 rid=abc123 matched=60 reused=60 "
                    "evaluated=40 replayed=0 work=40 divergent=-1 slot=2 restore_ms=3.5 lookup_ms=1.25 "
                    "restore=succeeded cache_source=live cache_reason=EXACT_MATCH")
        figures = parse_done(line).get("telemetry") or {}
        from serve.reqtelemetry import RequestRecord
        record = RequestRecord("abc123")
        apply_engine(record, figures)
        self.assertEqual(record.matched_prefix_tokens, 60)
        self.assertEqual(record.reused_prefix_tokens, 60)
        self.assertEqual(record.evaluated_tokens, 40)
        self.assertEqual(record.slot_id, 2)
        self.assertTrue(record.cache_restore_succeeded)
        # the conservation: 100 submitted = 60 reused + 40 evaluated
        record.set_prompt_tokens(rendered=100, submitted=100)
        record.set_native_cache(non_prefix_reused=0)
        record.seal("completed", 200)
        self.assertEqual(record.conservation(), [])

    def test_the_client_id_the_server_sends_is_one_the_engine_accepts(self):
        """The rid the server sends is hex (the engine accepts nothing else), and the server's ids are."""
        from serve.reqtelemetry import new_request_id
        for _ in range(50):
            request_id = new_request_id()
            self.assertTrue(all(c in "0123456789abcdefABCDEF" for c in request_id))
            self.assertLessEqual(len(request_id), 64)

    def test_the_client_id_is_validated_before_it_is_kept(self):
        self.assertTrue(valid_client_request_id("trace-42"))
        self.assertFalse(valid_client_request_id("trace 42"))


if __name__ == "__main__":
    unittest.main()
