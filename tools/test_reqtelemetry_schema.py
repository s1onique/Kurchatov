"""tools/test_reqtelemetry_schema.py - the telemetry record's schema, and the engine's writer against the server's
reader (ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01).

    python tools/test_reqtelemetry_schema.py

Two things are checked:

  1. the JSON Schema in docs/telemetry/ is the schema the code uses: the file on disk and the SCHEMA in
     serve/reqtelemetry.py are the same contract, so they cannot drift apart;
  2. every record the server can produce validates against it, and a record that is NOT valid is rejected.

The engine's writer (include/strata/program/reqtelemetry.hpp) has its own test (src/program/reqtelemetry_test.cpp);
the engine's DONE line is checked against the server's reader by tools/test_reqtelemetry_roundtrip.py when the
engine binary is available.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from serve.reqtelemetry import SCHEMA, RequestRecord, ServerTelemetry, validate  # noqa: E402
from serve.reqtelemetry.schema import SCHEMA_V2, SCHEMA_V3  # noqa: E402


def main() -> int:
    failures = []

    def check(ok, what):
        if not ok:
            failures.append(what)

    # 1. the schema on disk IS the schema in the code
    # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (A5c): BOTH contracts are on disk and both
    # are the ones the code uses: the historical strata.request-telemetry/2 and the current
    # strata.request-telemetry/3.  The historical one was restored: the incompatible corrections belong to the new
    # identity, not to the old one.
    on_disk = json.loads((ROOT / "docs/telemetry/strata-request-telemetry-2.schema.json").read_text())
    check(on_disk == SCHEMA_V2, "the historical v2 schema file and the code's v2 schema are the same contract")
    on_disk_v3 = json.loads((ROOT / "docs/telemetry/strata-request-telemetry-3.schema.json").read_text())
    check(on_disk_v3 == SCHEMA_V3, "the v3 schema file and the code's v3 schema are the same contract")
    check(SCHEMA is SCHEMA_V3, "the default schema is the current (v3) contract")
    check(SCHEMA_V2["properties"]["schema_version"] == {"const": "strata.request-telemetry/2"},
          "the historical contract keeps its own identity")
    check(SCHEMA_V3["properties"]["schema_version"] == {"const": "strata.request-telemetry/3"},
          "the current contract has its own identity")

    # 2. a record the server produces validates
    tel = ServerTelemetry()
    record = tel.begin(api="openai", client_request_id="abc", model_id="m")
    record.set_prompt_tokens(rendered=100, submitted=100)
    record.set_native_cache(matched_prefix=40, reused_prefix=40, evaluated=60, non_prefix_reused=0,
                             evaluation_work=60)
    record.set_generation(requested_max=64, effective_max=64, generated=7, emitted=7)
    record.set_timing("prefill_wall", 41.5, "native_engine")
    data = tel.finish(record, state="completed", http_status=200, finish_reason="stop")
    check(not validate(data), f"a finished record validates: {validate(data)}")

    # 3. a record that is NOT valid is rejected: the check has teeth
    broken = json.loads(json.dumps(data))
    broken["prompt"]["evaluated_tokens"] = "not a number"
    check(validate(broken), "a broken record is rejected")
    broken = json.loads(json.dumps(data))
    del broken["cache"]
    check(validate(broken), "a record without a section is rejected")
    broken = json.loads(json.dumps(data))
    broken["cache"]["disposition"] = "not a disposition"
    check(validate(broken), "a record with an unknown disposition is rejected")
    broken = json.loads(json.dumps(data))
    broken["extra_section"] = {}
    check(validate(broken), "a record with an unknown section is rejected")

    # 4. the HISTORICAL fixture validates against the historical contract (A5c), and NOT against the current one
    fixture = ROOT / "serve/fixtures/telemetry/record-v2.json"
    if fixture.exists():
        historical = json.loads(fixture.read_text())
        check(not validate(historical, SCHEMA_V2),
              f"the historical record validates against the v2 contract: {validate(historical, SCHEMA_V2)}")
        check(validate(historical, SCHEMA_V3),
              "the historical record does NOT validate against the current contract: the versions are separate")
    else:
        check(False, "the historical fixture is missing")

    if failures:
        for what in failures:
            print(f"FAIL: {what}")
        return 1
    print("test_reqtelemetry_schema: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
