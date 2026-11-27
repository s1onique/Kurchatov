#!/usr/bin/env python3
"""tools/test_telemetry_web_status.py - the dashboard's cache-reuse card, checked (F4).

ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (F4): the RESUME-01 patch dropped the assignment to
the `reuse-ratio` element, so the card showed its default text.  The card's value is drawn again here, and the
element is looked up the way the page looks elements up: `$` is getElementById, so the id is "reuse-detail" and
NOT "#reuse-detail".

The witness exercises the ACTUAL renderStatus of serve/web/telemetry.js - not only the pure formatting helper -
with a stub DOM, and it checks the three cases the amendment names:

    measured_ratio:    ratio 0.9  -> "90.0%"
    measured_zero:     ratio 0    -> "0.0%"   (a measured zero is a zero, not a dash)
    unavailable_ratio: ratio null -> "-"      (and the COVERAGE POPULATIONS stay visible)

    python tools/test_telemetry_web_status.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ACCOUNTING = ROOT / "terminal/serve/web/telemetry_accounting.js"
PAGE = ROOT / "terminal/serve/web/telemetry.js"

UNAVAILABLE = "—"

CASES = {
    "measured_ratio": {
        "summary": {"cache_reuse": {"ratio": 0.9, "reused_tokens": 90, "submitted_tokens": 100,
                                    "eligible_invocations": 2, "invocations": 2, "requests": 1,
                                    "requests_with_complete_accounting": 1, "coverage": 1.0}},
        "expect": {"displayed_percentage": "90.0%", "invocations": 2, "eligible_invocations": 2,
                   "coverage_populations_visible": True},
    },
    "measured_zero": {
        "summary": {"cache_reuse": {"ratio": 0, "reused_tokens": 0, "submitted_tokens": 100,
                                    "eligible_invocations": 2, "invocations": 2, "requests": 1,
                                    "requests_with_complete_accounting": 1, "coverage": 1.0}},
        "expect": {"displayed_percentage": "0.0%", "invocations": 2, "eligible_invocations": 2,
                   "coverage_populations_visible": True},
    },
    "unavailable_ratio": {
        "summary": {"cache_reuse": {"ratio": None, "reused_tokens": 0, "submitted_tokens": 0,
                                    "eligible_invocations": 0, "invocations": 2, "requests": 1,
                                    "requests_with_complete_accounting": 0, "coverage": None}},
        "expect": {"displayed_percentage": UNAVAILABLE, "invocations": 2, "eligible_invocations": 0,
                   "coverage_populations_visible": True},
    },
}

# The stub DOM: the page's own code runs against it, and the assignments it makes are read back.
HARNESS = """
var __els = {};
var __document = {
  documentElement: {dataset: {}},
  getElementById: function (id) {
    if (!__els[id]) __els[id] = {textContent: "", value: "2", hidden: false, dataset: {}};
    return __els[id];
  },
  addEventListener: function () {},
  createElement: function () { return {append: function () {}, replaceChildren: function () {},
                                       setAttribute: function () {}}; },
};
var __sessionStorage = {getItem: function () { return null; }, setItem: function () {}};
var __localStorage = {getItem: function () { return null; }, setItem: function () {}};
var __fetch = function () { return new Promise(function () {}); };
var __URLSearchParams = function () { this.set = function () {}; this.toString = function () { return ""; }; };
var __render = new Function("document", "sessionStorage", "localStorage", "fetch", "setInterval",
                            "clearInterval", "URLSearchParams", __SOURCE__)(
  __document, __sessionStorage, __localStorage, __fetch, function () { return 0; }, function () {},
  __URLSearchParams);
__render({model: "m", engine_instance_id: "e", enabled: true, quality: "complete"}, __SUMMARY__);
JSON.stringify({ratio: (__els["reuse-ratio"] || {textContent: ""}).textContent,
                detail: (__els["reuse-detail"] || {textContent: ""}).textContent});
"""


def _engine():
    """The JavaScript engine of this host (None: there is none)."""
    if shutil.which("node"):
        return ["node", "-e"]
    if shutil.which("osascript"):
        return ["osascript", "-l", "JavaScript", "-e"]
    return None


def _run(engine, script: str) -> str:
    result = subprocess.run(engine + [script], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _rendered(engine, source, summary):
    """The ACTUAL renderStatus of the page, run against the stub DOM: what it wrote is read back."""
    script = ("var __SOURCE__ = " + json.dumps(source) + ";\nvar __SUMMARY__ = " + json.dumps(summary) + ";\n"
              + HARNESS)
    out = _run(engine, script)
    try:
        return json.loads(out.splitlines()[-1])
    except (ValueError, IndexError):
        return None


def main() -> int:
    engine = _engine()
    if engine is None:
        print("NOT_EXECUTED: this host has no JavaScript engine (no node, no osascript)")
        return 0
    failures = []

    def check(ok, what):
        if not ok:
            failures.append(what)

    source = ACCOUNTING.read_text() + "\n" + PAGE.read_text() + "\n; return renderStatus;"
    for name, case in CASES.items():
        rendered = _rendered(engine, source, case["summary"])
        check(rendered is not None, f"{name}: renderStatus did not answer")
        if rendered is None:
            continue
        expect = case["expect"]
        check(rendered.get("ratio") == expect["displayed_percentage"],
              f"{name}: the card shows {rendered.get('ratio')!r}, expected {expect['displayed_percentage']!r}")
        detail = rendered.get("detail") or ""
        if expect["coverage_populations_visible"]:
            check(f"{expect['eligible_invocations']} of {expect['invocations']} native invocations accounted for"
                  in detail, f"{name}: the coverage populations are not visible: {detail!r}")
            check("requests" in detail, f"{name}: the request population is not visible: {detail!r}")

    # the witness has TEETH: with the card's own assignment removed, the card shows nothing
    mutated = source.replace('$("reuse-ratio").textContent = reuseRatioText(reuse);', "")
    check(mutated != source, "the mutation of the card's assignment was applied")
    rendered = _rendered(engine, mutated, CASES["measured_ratio"]["summary"])
    check(rendered is not None and rendered.get("ratio") != "90.0%",
          "a card without its own assignment still shows the ratio")

    if failures:
        for what in failures:
            print(f"FAIL: {what}")
        return 1
    print(f"test_telemetry_web_status: {len(CASES)} cases checked with {engine[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
