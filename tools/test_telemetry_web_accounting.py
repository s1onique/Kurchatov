#!/usr/bin/env python3
"""tools/test_telemetry_web_accounting.py - the browser's accounting bar, checked (A7).

The bar's arithmetic lives in ONE pure function (serve/web/telemetry_accounting.js), so the page and this test
cannot drift apart.  The function is run with the JavaScript engine of the host (osascript's JavaScript on macOS,
node elsewhere).  Without one the test says NOT_EXECUTED and does not pretend to have run.

    python tools/test_telemetry_web_accounting.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "terminal/serve/web/telemetry_accounting.js"

# the four cases the amendment names: complete, incomplete, violated and unavailable
CASES = {
    "complete": {
        "prompt": {"submitted_tokens": 100, "reused_prefix_tokens": 40, "evaluated_tokens": 60,
                   "non_prefix_reused_tokens": 0, "replayed_tokens": 5},
        "quality": {"accounting": {"state": "satisfied"}},
        "expect": {"complete": True, "total": 100,
                   "parts": {"reused": 40, "evaluated": 55, "replayed": 5},
                   "notes": 0},
    },
    "incomplete": {
        # the replay was not measured: it is not drawn as a measured zero, and the positions nobody accounted
        # for are shown
        "prompt": {"submitted_tokens": 100, "reused_prefix_tokens": 40, "evaluated_tokens": 50,
                   "non_prefix_reused_tokens": 0, "replayed_tokens": None},
        "quality": {"accounting": {"state": "satisfied"}},
        "expect": {"complete": True, "total": 100,
                   "parts": {"reused": 40, "evaluated": 50, "unaccounted": 10},
                   "notes": 1},
    },
    "violated": {
        "prompt": {"submitted_tokens": 100, "reused_prefix_tokens": 90, "evaluated_tokens": 8,
                   "non_prefix_reused_tokens": 0, "replayed_tokens": 0},
        "quality": {"accounting": {"state": "violated"}},
        "expect": {"complete": False, "total": None, "parts": {}, "notes": 1},
    },
    "unavailable": {
        "prompt": {"submitted_tokens": None, "reused_prefix_tokens": None, "evaluated_tokens": None,
                   "non_prefix_reused_tokens": None, "replayed_tokens": None},
        "quality": {"accounting": {"state": "unevaluated"}},
        "expect": {"complete": False, "total": None, "parts": {}, "notes": 1},
    },
}


def _engine():
    """The JavaScript engine of this host (None: there is none)."""
    if shutil.which("node"):
        return ["node", "-e"]
    if shutil.which("osascript"):
        return ["osascript", "-l", "JavaScript", "-e"]
    return None


def _run(engine, script: str) -> str:
    if engine[0] == "node":
        return subprocess.run(engine + [script], capture_output=True, text=True, timeout=60).stdout.strip()
    # osascript prints the result of the last expression
    return subprocess.run(engine + [script], capture_output=True, text=True, timeout=60).stdout.strip()


def main() -> int:
    engine = _engine()
    if engine is None:
        print("NOT_EXECUTED: this host has no JavaScript engine (no node, no osascript)")
        return 0
    source = JS.read_text()
    failures = []
    for name, case in CASES.items():
        script = source + "\nvar __case = " + json.dumps(case) + """
        ;
        var out = accountingBarParts(__case.prompt, __case.quality);
        JSON.stringify(out);
        """
        out = _run(engine, script)
        try:
            result = json.loads(out.splitlines()[-1])
        except (ValueError, IndexError):
            failures.append(f"{name}: the function did not answer ({out!r})")
            continue
        expect = case["expect"]
        if result["complete"] != expect["complete"]:
            failures.append(f"{name}: complete is {result['complete']}, expected {expect['complete']}")
        if expect["total"] is not None and result.get("total") != expect["total"]:
            failures.append(f"{name}: the total is {result.get('total')}, expected {expect['total']}")
        parts = {p["className"]: p["value"] for p in result["parts"]}
        for class_name, value in expect["parts"].items():
            if parts.get(class_name) != value:
                failures.append(f"{name}: the {class_name} part is {parts.get(class_name)}, expected {value}")
        if expect["parts"] == {} and parts:
            failures.append(f"{name}: no bar was expected, got {parts}")
        if len(result["notes"]) != expect["notes"]:
            failures.append(f"{name}: {len(result['notes'])} notes, expected {expect['notes']}")
    if failures:
        for what in failures:
            print(f"FAIL: {what}")
        return 1
    print(f"test_telemetry_web_accounting: {len(CASES)} cases checked with {engine[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
