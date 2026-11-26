"""serve/reqtelemetry/schema.py - the JSON Schema of the record and its checker (G9).

The schema on the wire and the schema in the code are the same contract: docs/telemetry/ holds the file, and
tools/test_reqtelemetry_schema.py checks that the file and this SCHEMA are identical.
"""
from __future__ import annotations

from serve.reqtelemetry.vocabulary import (CLIENT_ID_MAX, COMPLETE, DISPOSITIONS, INSTRUMENTATION_ERROR, PARTIAL,
                                         SCHEMA_VERSION, SOURCES, STATES, UNSUPPORTED)

def _int_or_null():
    return {"type": ["integer", "null"], "minimum": 0}


def _str_or_null(max_length=None):
    node = {"type": ["string", "null"]}
    if max_length:
        node["maxLength"] = max_length
    return node


# The JSON Schema of the record (draft 2020-12).  It is exported as a file (docs/telemetry/) and checked by an
# executable test, so the contract on the wire and the contract in the code cannot drift apart.
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://github.com/s1onique/Kurchatov/schemas/strata-request-telemetry-1.json",
    "title": "Strata per-request telemetry record",
    "type": "object",
    "required": ["schema_version", "identity", "lifecycle", "prompt", "cache", "timing_ms", "generation",
                 "measurement_quality"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "seq": {"type": "integer", "minimum": 1},
        "identity": {
            "type": "object",
            "required": ["request_id", "client_request_id", "engine_instance_id", "server_instance_id",
                         "engine_invocation_id", "slot_id", "model_id", "build_revision"],
            "additionalProperties": False,
            "properties": {
                "request_id": {"type": "string", "minLength": 1},
                "client_request_id": _str_or_null(CLIENT_ID_MAX),
                "engine_instance_id": _str_or_null(),
                "server_instance_id": _str_or_null(),
                "engine_invocation_id": _str_or_null(),
                "slot_id": {"type": ["integer", "null"], "minimum": 0},
                "model_id": _str_or_null(),
                "build_revision": _str_or_null(),
            },
        },
        "lifecycle": {
            "type": "object",
            "required": ["state", "api", "received_at", "started_at", "finished_at", "http_status", "finish_reason",
                         "detail"],
            "additionalProperties": False,
            "properties": {
                "state": {"enum": list(STATES)},
                "api": _str_or_null(),
                "received_at": {"type": ["number", "null"]},
                "started_at": {"type": ["number", "null"]},
                "finished_at": {"type": ["number", "null"]},
                "http_status": {"type": ["integer", "null"], "minimum": 100, "maximum": 599},
                "finish_reason": _str_or_null(),
                "detail": _str_or_null(),
            },
        },
        "prompt": {
            "type": "object",
            "required": ["rendered_tokens", "submitted_tokens", "matched_prefix_tokens", "reused_prefix_tokens",
                         "evaluated_tokens", "replayed_tokens", "non_prefix_reused_tokens",
                         "evaluation_work_tokens", "first_divergent_token_index"],
            "additionalProperties": False,
            "properties": {
                "rendered_tokens": _int_or_null(),
                "submitted_tokens": _int_or_null(),
                "matched_prefix_tokens": _int_or_null(),
                "reused_prefix_tokens": _int_or_null(),
                "evaluated_tokens": _int_or_null(),
                "replayed_tokens": _int_or_null(),
                "non_prefix_reused_tokens": _int_or_null(),
                "evaluation_work_tokens": _int_or_null(),
                "first_divergent_token_index": _int_or_null(),
            },
        },
        "cache": {
            "type": "object",
            "required": ["source", "disposition", "reason_code", "restore_attempted", "restore_succeeded",
                         "restore_ms", "recurrent_state", "attention_state", "checkpoint_state", "invalidations",
                         "evictions"],
            "additionalProperties": False,
            "properties": {
                "source": {"enum": list(SOURCES)},
                "disposition": {"enum": list(DISPOSITIONS)},
                "reason_code": _str_or_null(),
                "restore_attempted": {"type": ["boolean", "null"]},
                "restore_succeeded": {"type": ["boolean", "null"]},
                "restore_ms": {"type": ["number", "null"], "minimum": 0},
                "recurrent_state": _str_or_null(),
                "attention_state": _str_or_null(),
                "checkpoint_state": _str_or_null(),
                "invalidations": _int_or_null(),
                "evictions": _int_or_null(),
            },
        },
        "timing_ms": {"type": "object", "additionalProperties": {"type": ["number", "null"], "minimum": 0}},
        "generation": {
            "type": "object",
            "required": ["requested_max_output_tokens", "effective_max_output_tokens", "generated_tokens",
                         "emitted_tokens", "speculative_draft_tokens", "speculative_accepted_tokens"],
            "additionalProperties": False,
            "properties": {
                "requested_max_output_tokens": _int_or_null(),
                "effective_max_output_tokens": _int_or_null(),
                "generated_tokens": _int_or_null(),
                "emitted_tokens": _int_or_null(),
                "speculative_draft_tokens": _int_or_null(),
                "speculative_accepted_tokens": _int_or_null(),
            },
        },
        "measurement_quality": {
            "type": "object",
            "required": ["state", "unavailable_fields", "timing_authority", "first_token_includes_reasoning",
                         "accounting"],
            "additionalProperties": False,
            "properties": {
                "state": {"enum": [COMPLETE, PARTIAL, UNSUPPORTED, INSTRUMENTATION_ERROR]},
                "unavailable_fields": {"type": "object", "additionalProperties": {"type": "string"}},
                "timing_authority": {"type": "object", "additionalProperties": {"type": "string"}},
                "first_token_includes_reasoning": {"type": ["boolean", "null"]},
                "accounting": {
                    "type": "object",
                    "required": ["state", "valid", "problems"],
                    "additionalProperties": False,
                    "properties": {
                        "state": {"enum": ["satisfied", "violated", "unevaluated"]},
                        "valid": {"type": ["boolean", "null"]},
                        "problems": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    },
}


def validate(record: dict, schema: dict | None = None) -> list:
    """The schema errors of a record (an empty list when it is valid).

    The `jsonschema` package is used when it is installed; without it a small built-in checker covers this schema
    (the sections, the required keys, the enumerations, the types and the null-or-number rule).  The server does
    not need the package: this is a check for the tests and for the operator's own tooling.
    """
    schema = schema or SCHEMA
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return _validate_builtin(record, schema)
    errors = []
    for error in Draft202012Validator(schema).iter_errors(record):
        location = "/".join(str(part) for part in error.absolute_path) or "(root)"
        errors.append(f"{location}: {error.message}")
    return errors


def _validate_builtin(record: dict, schema: dict) -> list:
    """The built-in checker: enough for this schema, so the contract can be checked without the package."""
    errors = []
    if not isinstance(record, dict):
        return ["the record is not an object"]
    for key in schema.get("required", []):
        if key not in record:
            errors.append(f"{key}: the section is missing")
    allowed = set(schema.get("properties", {}))
    for key in record:
        if key not in allowed:
            errors.append(f"{key}: not in the schema")
    for key, node in (schema.get("properties") or {}).items():
        if key not in record:
            continue
        value = record[key]
        types = node.get("type")
        if types:
            types = [types] if isinstance(types, str) else types
            ok = False
            for t in types:
                if t == "object" and isinstance(value, dict):
                    ok = True
                elif t == "array" and isinstance(value, list):
                    ok = True
                elif t == "string" and isinstance(value, str):
                    ok = True
                elif t == "integer" and isinstance(value, int) and not isinstance(value, bool):
                    ok = True
                elif t == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
                    ok = True
                elif t == "boolean" and isinstance(value, bool):
                    ok = True
                elif t == "null" and value is None:
                    ok = True
            if not ok:
                errors.append(f"{key}: {'/'.join(types)} expected")
        if "enum" in node and value not in node["enum"]:
            errors.append(f"{key}: {value!r} is not one of {node['enum']}")
        if "const" in node and value != node["const"]:
            errors.append(f"{key}: {value!r} is not {node['const']!r}")
        if isinstance(value, dict) and node.get("properties"):
            errors.extend(_validate_builtin(value, node))
        if isinstance(value, dict) and node.get("additionalProperties") is False and node.get("properties"):
            for sub in value:
                if sub not in node["properties"]:
                    errors.append(f"{key}/{sub}: not in the schema")
        if "maxLength" in node and isinstance(value, str) and len(value) > node["maxLength"]:
            errors.append(f"{key}: longer than {node['maxLength']}")
        if "minimum" in node and isinstance(value, (int, float)) and not isinstance(value, bool) \
                and value < node["minimum"]:
            errors.append(f"{key}: below {node['minimum']}")
    return errors
