# The corrections of ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01

## A5a - the actual strict JSON boundary (the only gate this run closed)

**The defect.** `serve/reqtelemetry/evidence.py` serialized the record with the default `json.dumps`.  The
default accepts `NaN`, `Infinity` and `-Infinity` and writes them into the JSONL line as the bare tokens
`NaN`, `Infinity` and `-Infinity`.  Those are not JSON: RFC 8259 has no literal for them, and a strict reader
(`json.loads` with `parse_constant`, `jq`, `JSON.parse`) rejects the line.  The evidence file was therefore not
guaranteed to be readable JSON, even though every other boundary of the telemetry was strict.

**The correction.** The evidence-writing boundary now serializes with `allow_nan=False`:

```python
line = (json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
```

A record that carries a value JSON cannot represent now FAILS the serialization, and the failure lands in the
writer's existing serialization-refusal domain: `serialization_refusals`, `refused_records`, `dropped_records`
and `errors` each grow by one, `pending` falls back, and the record never reaches the disk.  No new refusal
domain, no new counter, no new framework: the refusal the writer already had for an unserializable record now
also covers a non-finite one.

**What this leaves alone.** The record's own typed admission is unchanged: a NaN duration is still refused at
`record.set_timing` and stays null.  The writer's boundary is the LAST line of defence, and it is now strict.
The store's own byte accounting, the Prometheus exporter, the HTTP handlers and the schema are untouched.

## The witnesses (serve/test_telemetry_evidence_writer.py)

They drive the REAL writer (`EvidenceLog.write`), not a stand-in:

| witness | what it shows |
|---|---|
| `test_a_nan_record_is_refused_by_the_writer` | a NaN record is refused, counted as a serialization refusal, and never written |
| `test_a_positive_infinity_record_is_refused_by_the_writer` | the same for `+Infinity` |
| `test_a_negative_infinity_record_is_refused_by_the_writer` | the same for `-Infinity` |
| `test_the_non_finite_record_is_refused_wherever_it_sits` | the refusal is about the record, not about one field's place in it |
| `test_a_valid_record_is_strict_json_on_the_disk` | what IS written is valid UTF-8 and parses with a strict reader |
| `test_the_written_line_carries_no_non_finite_token` | the line never contains `NaN` or `Infinity` |
| `test_the_writer_conserves_its_counter_domains_after_a_refusal` | `submitted = accepted + refused + pending` and `accepted = written + failed + outstanding` still hold |
| `test_a_refused_record_does_not_disturb_the_records_around_it` | a refusal is per record: the valid ones around it are still written |
| `test_a_record_with_a_non_finite_value_never_reaches_the_disk` | the whole path, through the real `ServerTelemetry` |
| `test_the_telemetry_payload_is_strict_json_by_construction` | the payload the HTTP telemetry endpoints serve is strict JSON |
| `test_the_http_telemetry_body_is_strict_json` | the served HTTP body parses with a strict reader (needs the server's own dependencies) |
| `test_the_witnesses_fail_when_the_strict_boundary_is_reversed` | NON-VACUITY: with the correction reversed in memory, the writer accepts the record again |

## What was NOT closed in this run

The amendment names seven gates (A1-A7).  This run closed **A5a only**, because the runtime authority scoped
the mutation to "the production telemetry evidence JSONL writer module and its directly associated writer test
file".  A1, A2, A3, A4, A5b, A5c, A6 and A7 are untouched and remain open.

The environment blocks part of the verification: `jinja2` is not installed in this container, so every test
module that imports `serve.server` (including `serve/test_reqtelemetry.py`,
`serve/test_telemetry_closure01.py`, `serve/test_telemetry_amendment02.py`, `serve/test_telemetry_amendment03.py`,
`serve/test_telemetry_integrity.py`, `serve/test_request_accounting.py` and the three mutation suites) fails at
import.  That failure is PRE-EXISTING: with the change stashed, `python -m unittest discover -s serve` reports
the same 61 import errors.  With the change applied it reports the same 61, and 12 more tests run (the new
writer suite).  `tools/test_reqtelemetry_schema.py` passes, and `tools/test_telemetry_web_accounting.py` checks
its four cases with the host's JavaScript engine.
