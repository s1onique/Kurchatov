#!/usr/bin/env python3
"""tools/test_telemetry_web_inspector.py - the browser's invocation inspector, checked (A6).

ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (A6): the inspector's facts and the coverage
line are PURE functions of serve/web/telemetry_accounting.js, so they can be run here with a REAL record - one the
production path built, with two ASYMMETRICAL invocation receipts - and the page and this test cannot drift apart.

The witness checks:

  1. BOTH invocations appear, with their own identities, their own prompt domains, their own native outcomes and
     their own measurements;
  2. a measurement that was NOT taken is shown as unavailable, never as a zero;
  3. the coverage line names the CORRECTED populations (A1): the dispatched native invocations and the physical
     requests that reached a terminal outcome;
  4. the witness has TEETH: with the inspector's property misspelled, the same check fails.

    python tools/test_telemetry_web_inspector.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# the serving layer lives in terminal/, so `serve.` is a package under terminal/.
sys.path.insert(0, str(ROOT / 'terminal'))

JS = ROOT / "terminal/serve/web/telemetry_accounting.js"

# the character the page shows for a measurement that was not taken (an em dash)
UNAVAILABLE = "—"


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


def _record():
    """A REAL record of the production path, with two asymmetrical invocation receipts."""
    from serve.reqtelemetry import RequestRecord, apply_engine, new_invocation_id
    record = RequestRecord("r1", client_request_id="abc", model_id="m", build_revision="b", api="openai")
    record.set_prompt_tokens(rendered=100, submitted=100)
    first = new_invocation_id()
    record.begin_invocation(first, ordinal=1)
    receipt = record.invocation_for(first)
    receipt.submitted_tokens = 100
    receipt.prompt_domain = "request"
    apply_engine(record, {"rid": first, "matched": 90, "reused": 90, "evaluated": 10, "work": 10,
                          "lookup_ms": 12.0}, expected_invocation_id=first,
                 positional={"prompt_ms": 11.0, "decode_ms": 22.0, "generated": 5, "finish": "stop"},
                 native_state="completed")
    second = new_invocation_id()
    record.begin_invocation(second, ordinal=2)
    receipt = record.invocation_for(second)
    receipt.submitted_tokens = 40
    receipt.prompt_domain = "other"
    # the second invocation measured LESS: the restoration failed and it generated nothing
    apply_engine(record, {"rid": second, "matched": 40, "reused": 0, "evaluated": 40, "work": 40,
                          "restore": "failed", "restore_ms": 3.0}, expected_invocation_id=second,
                 positional={"prompt_ms": 7.0, "finish": "error"}, native_state="failed")
    return record.seal("completed", 200, finish_reason="stop").to_dict()


def main() -> int:
    engine = _engine()
    if engine is None:
        print("NOT_EXECUTED: this host has no JavaScript engine (no node, no osascript)")
        return 0
    failures = []

    def check(ok, what):
        if not ok:
            failures.append(what)

    record = _record()
    # the record the witness shows is a REAL one: it validates against the current contract
    from serve.reqtelemetry import validate
    check(not validate(record), f"the witness record validates: {validate(record)}")
    check(len(record.get("invocations") or []) == 2, "the witness record has two invocation receipts")

    source = JS.read_text()

    def facts_of(js_source):
        out = _run(engine, js_source + "\nvar __record = " + json.dumps(record) + """\n;
        JSON.stringify({facts: invocationFacts(__record)});
        """)
        try:
            return json.loads(out.splitlines()[-1])["facts"]
        except (ValueError, IndexError, KeyError):
            return None

    facts = facts_of(source)
    check(facts is not None, "the inspector's facts function answered")
    if facts is not None:
        labels = {label: value for label, value in facts}
        # 1. BOTH invocations appear, with their own identities and measurements
        check("Invocation 1 id" in labels, "the first invocation appears")
        check("Invocation 2 id" in labels, "the second invocation appears")
        check(labels.get("Invocation 1 id") == record["invocations"][0]["identity"]["engine_invocation_id"],
              "the first invocation keeps its own identity")
        check(labels.get("Invocation 2 id") == record["invocations"][1]["identity"]["engine_invocation_id"],
              "the second invocation keeps its own identity")
        check(labels.get("Invocation 1 state") == "completed", "the first invocation keeps its native outcome")
        check(labels.get("Invocation 2 state") == "failed", "the second invocation keeps its native outcome")
        check(labels.get("Invocation 1 prompt domain") == "request", "the first invocation keeps its prompt domain")
        check(labels.get("Invocation 2 prompt domain") == "other", "the second invocation keeps its prompt domain")
        check(labels.get("Invocation 1 reused") == "90", "the first invocation keeps its own reuse")
        check(labels.get("Invocation 2 reused") == "0", "the second invocation keeps its own reuse")
        check(labels.get("Invocation 2 cache") == record["invocations"][1]["cache"]["disposition"],
              "the second invocation keeps its own disposition")
        # 2. a measurement that was NOT taken is unavailable, never a zero
        check(labels.get("Invocation 2 generated") == UNAVAILABLE,
              f"a measurement that was not taken is unavailable, not a zero: "
              f"{labels.get('Invocation 2 generated')!r}")
        check(labels.get("Invocation 2 decode") == UNAVAILABLE,
              f"a duration that was not measured is unavailable: {labels.get('Invocation 2 decode')!r}")
        check(labels.get("Invocation 1 generated") == "5", "a measured generation count is shown")

    # 3. the coverage line names the corrected populations (A1)
    from serve.reqtelemetry import ServerTelemetry, apply_engine, new_invocation_id
    tel = ServerTelemetry()
    served = tel.begin(api="openai", client_request_id="abc", model_id="m")
    served.set_prompt_tokens(rendered=100, submitted=100)
    invocation = new_invocation_id()
    served.begin_invocation(invocation, ordinal=1)
    served.invocation_for(invocation).submitted_tokens = 100
    served.invocation_for(invocation).prompt_domain = "request"
    apply_engine(served, {"rid": invocation, "matched": 90, "reused": 90, "evaluated": 10, "work": 10},
                 expected_invocation_id=invocation)
    tel.finish(served, state="completed", http_status=200, finish_reason="stop")
    summary = tel.store.summary()
    reuse = summary["cache_reuse"]
    line = _run(engine, source + "\nvar __reuse = " + json.dumps(reuse) + """\n;
    reuseCoverageLine(__reuse);
    """)
    check("native invocations accounted for" in line, "the coverage line names the invocation population")
    check("requests" in line, "the coverage line names the request population")
    check(f"{reuse['eligible_invocations']} of {reuse['invocations']} native invocations accounted for" in line,
          f"the coverage line names the dispatched invocation population: {line!r}")
    check(f"{reuse['requests_with_complete_accounting']} of {reuse['requests']} requests" in line,
          f"the coverage line names the physical request population: {line!r}")

    # 4. the witness has TEETH: with the inspector's property misspelled, the facts are gone
    misspelled = source.replace("record.invocations", "record.invocation_receipts")
    check(misspelled != source, "the mutation of the inspector's property was applied")
    mutated = facts_of(misspelled)
    check(mutated == [], f"a misspelled inspector property shows no invocation at all: {mutated!r}")

    if failures:
        for what in failures:
            print(f"FAIL: {what}")
        return 1
    print(f"test_telemetry_web_inspector: the invocation inspector was checked with {engine[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
