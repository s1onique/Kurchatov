"""serve/reqtelemetry/ - the per-request telemetry, split by responsibility.

ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-01 (G9): the former serve/reqtelemetry.py was one file with
everything in it.  It is now:

    vocabulary   the record's own words: the enumerations, the limits, the schema version
    record       the canonical record and the helpers around it
    accounting   the token accounting rules: the disposition and the conservation identities
    correlation  the native receipt and the request it belongs to
    schema       the JSON Schema of the record and its checker
    store        the bounded store of recent records and the process-lifetime counters
    metrics      the duration histograms the Prometheus exporter reads
    evidence     the optional metadata-only JSONL evidence
    server       the server's side: the store, the evidence log and the lifecycle helpers

The import surface of serve.reqtelemetry is unchanged: it re-exports everything this package offers, so nothing
outside has to change with the split.
"""
from __future__ import annotations

from serve.reqtelemetry import accounting, correlation, evidence, metrics, record, schema, store, vocabulary
from serve.reqtelemetry.correlation import (REASON_CODES, SOURCE_NAMES, apply_engine, native_terminal_state,
                                            new_invocation_id, normalize_terminal_evidence)
from serve.reqtelemetry.evidence import EvidenceLog
from serve.reqtelemetry.metrics import DURATION_BUCKETS
from serve.reqtelemetry.record import (RequestRecord, decode_cursor, encode_cursor, new_request_id,
                                    valid_client_request_id)
from serve.reqtelemetry.schema import SCHEMA, validate
from serve.reqtelemetry.server import ServerTelemetry
from serve.reqtelemetry.store import TelemetryStore
from serve.reqtelemetry.vocabulary import (CLIENT_ID_ALLOWED, CLIENT_ID_MAX, COMPLETE, DEFAULT_PAGE_SIZE,
                                         DEFAULT_RETENTION_BYTES, DEFAULT_RETENTION_RECORDS, DISPOSITIONS,
                                         DISPOSITION_BYPASSED, DISPOSITION_COLD_MISS, DISPOSITION_FULL_HIT,
                                         DISPOSITION_INVALIDATED, DISPOSITION_MATCH_WITHOUT_STATE,
                                         DISPOSITION_PARTIAL_HIT, DISPOSITION_UNKNOWN, INSTRUMENTATION_ERROR,
                                         MAXIMUM_PAGE_SIZE, PARTIAL, SCHEMA_VERSION, SOURCES,
                                         SOURCE_CONVERSATION_CACHE, SOURCE_MULTIPLE, SOURCE_NONE,
                                         SOURCE_RESIDENT_SLOT, SOURCE_RESTORED_CHECKPOINT, SOURCE_UNKNOWN, STATES,
                                         UNSUPPORTED)

__all__ = ["CLIENT_ID_ALLOWED", "CLIENT_ID_MAX", "COMPLETE", "DEFAULT_PAGE_SIZE", "DEFAULT_RETENTION_BYTES",
           "DEFAULT_RETENTION_RECORDS", "DISPOSITIONS", "DISPOSITION_BYPASSED", "DISPOSITION_COLD_MISS",
           "DISPOSITION_FULL_HIT", "DISPOSITION_INVALIDATED", "DISPOSITION_MATCH_WITHOUT_STATE",
           "DISPOSITION_PARTIAL_HIT", "DISPOSITION_UNKNOWN", "DURATION_BUCKETS", "EvidenceLog",
           "INSTRUMENTATION_ERROR", "MAXIMUM_PAGE_SIZE", "PARTIAL", "RequestRecord", "SCHEMA", "SCHEMA_VERSION",
           "SOURCES", "SOURCE_CONVERSATION_CACHE", "SOURCE_MULTIPLE", "SOURCE_NONE", "SOURCE_RESIDENT_SLOT",
           "SOURCE_RESTORED_CHECKPOINT", "SOURCE_UNKNOWN", "STATES", "ServerTelemetry", "TelemetryStore",
           "UNSUPPORTED", "apply_engine", "decode_cursor", "encode_cursor", "native_terminal_state", "new_invocation_id", "new_request_id",
           "normalize_terminal_evidence", "valid_client_request_id", "validate"]
