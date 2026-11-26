"""serve/reqtelemetry/server.py - the server's side of the per-request telemetry (G9).

The HTTP SERVER owns the request lifecycle: the queue wait, the render, the tokenization, the model load, the time
to the first token the client sees, the total time and the HTTP status.  The store, the evidence log and the
counters live beside it; the record itself lives in serve/reqtelemetry/record.py.
"""
from __future__ import annotations

import threading
import uuid

from serve.reqtelemetry.evidence import EvidenceLog
from serve.reqtelemetry.record import RequestRecord, new_request_id, valid_client_request_id
from serve.reqtelemetry.store import TelemetryStore
from serve.reqtelemetry.vocabulary import (DEFAULT_RETENTION_BYTES, DEFAULT_RETENTION_RECORDS, SCHEMA_VERSION,
                                         UNSUPPORTED)

class ServerTelemetry:
    """The server's side of the per-request telemetry: the store, the evidence log and the lifecycle helpers.

    The HTTP SERVER owns the request lifecycle: the queue wait, the render, the tokenization, the model load, the
    time to the first byte the client sees and the total time.  The NATIVE ENGINE owns the cache state and the
    model execution.  This class is where the two meet: it holds each request's record, takes the engine's figures
    when the request ends, and puts the finished record into the store and (optionally) the evidence log.

    It is INDEPENDENT of the content-capturing API monitor: nothing here keeps a prompt, an answer or a header.
    """

    def __init__(self, server_instance_id=None, max_records=DEFAULT_RETENTION_RECORDS,
                 max_bytes=DEFAULT_RETENTION_BYTES, evidence_path=None):
        self.server_instance_id = server_instance_id or uuid.uuid4().hex
        # the store belongs to THIS server: the cursors it writes name it, so a cursor of another server (or of
        # a previous run) is refused instead of quietly pointing somewhere else (G7)
        self.store = TelemetryStore(max_records=max_records, max_bytes=max_bytes,
                                    server_instance_id=self.server_instance_id)
        self.evidence = EvidenceLog(evidence_path) if evidence_path else None
        self.enabled = True
        self._records: dict[str, RequestRecord] = {}     # the requests in flight, by their id
        self.lock = threading.Lock()

    # ------------------------------------------------------------------ the request's life
    def begin(self, api=None, client_request_id=None, model_id=None, build_revision=None) -> RequestRecord:
        """A new request's record.  Its id is the server's own: unique per physical attempt, never derived from
        the client's id, so two requests that carry the same client id stay two records.

        AMENDMENT-02 (A4): the request is counted as ACCEPTED here, at the admission boundary, and this count does
        not depend on the record: a request whose record can never be sealed is still an accepted request.
        """
        if not self.enabled:
            # the telemetry is off: NOTHING is allocated, nothing is kept, nothing is written (G6)
            return None
        record = RequestRecord(new_request_id(), client_request_id=client_request_id,
                               server_instance_id=self.server_instance_id, model_id=model_id,
                               build_revision=build_revision, api=api)
        with self.lock:
            self._records[record.request_id] = record
        self.store.begin_request()
        return record

    def finish(self, record: RequestRecord, state=None, http_status=None, finish_reason=None, detail=None):
        """Close a request's record, put it in the store and write the evidence line.  At most once: a record that
        was already finished is not finished again.

        AMENDMENT-02 (A4): the TERMINAL OUTCOME is counted before the record is sealed, so a request whose record
        cannot be sealed or stored still has exactly one terminal outcome and the lifecycle identity still balances.
        The receipt's own delivery is counted beside it: the two identities are separate on purpose.
        """
        if record is None:
            return None
        if not self.enabled:
            return None                         # the telemetry is off: nothing is kept and nothing is written
        with self.lock:
            if record.request_id not in self._records:
                return None                 # already finished: a terminal receipt is finalized AT MOST ONCE
            del self._records[record.request_id]
        # the terminal outcome first: it does not depend on the receipt
        self.store.end_request(state)
        try:
            record.seal(state=state, http_status=http_status, finish_reason=finish_reason, detail=detail)
            data = self.store.add(record)
        except Exception:                   # noqa: BLE001 - a receipt that cannot be sealed is a lost receipt, not a
            self.store.receipt_failed()      # lost request: the terminal outcome above still stands
            raise
        if self.evidence is not None:
            self.evidence.write(data)
        return data

    def inflight(self) -> int:
        """The requests that are running now (the gauge /metrics shows)."""
        with self.lock:
            return len(self._records)

    def status(self) -> dict:
        """What the telemetry can do, who it is and how much it keeps."""
        summary = self.store.summary()
        return {
            "schema_version": SCHEMA_VERSION,
            "enabled": self.enabled,
            "server_instance_id": self.server_instance_id,
            "engine_instance_id": None,       # the engine's own identity is set per request
            "build_revision": None,
            "capabilities": {
                "prompt_accounting": True,
                "cache_attribution": True,
                "per_request_timings": True,
                "generation_counters": True,
                "structured_evidence": self.evidence is not None,
            },
            "retention": summary["retention"],
            "quality": "complete" if self.enabled else "unsupported",
            "counters": summary["counters"],
        }

    def close(self):
        """The shutdown path: the evidence log's queue is written out and its file closed."""
        if self.evidence is not None:
            self.evidence.flush()
            self.evidence.close()
