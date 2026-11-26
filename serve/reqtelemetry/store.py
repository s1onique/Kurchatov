"""serve/reqtelemetry/store.py - the bounded store of recent records and the process-lifetime counters (G9).

The store is bounded by BOTH a record count and a byte budget: a very long request cannot push the store over its
memory ceiling.  It is intentionally NOT durable: nothing is written to disk here, and a restart empties it.  The
counters live here and never fall when a record is evicted - they are the process-lifetime totals.
"""
from __future__ import annotations

import json
import threading
import uuid

from serve.reqtelemetry.metrics import DURATION_BUCKETS, DURATION_METRICS, observe_duration
from serve.reqtelemetry.record import decode_cursor, encode_cursor
from serve.reqtelemetry.vocabulary import (CURSOR_TTL_S, DEFAULT_PAGE_SIZE, DEFAULT_RETENTION_BYTES,
                                         DEFAULT_RETENTION_RECORDS, INSTRUMENTATION_ERROR, MAXIMUM_PAGE_SIZE)

class TelemetryStore:
    """The bounded store of recent request records, and the process-lifetime counters beside it.

    The store is bounded by BOTH a record count and a byte budget: a very long request cannot push the store over
    its memory ceiling.  It is intentionally NOT durable: nothing is written to disk here, and a restart empties it.
    The counters live here and never fall when a record is evicted - they are the process-lifetime totals.
    """

    def __init__(self, max_records=DEFAULT_RETENTION_RECORDS, max_bytes=DEFAULT_RETENTION_BYTES,
                 server_instance_id=None):
        self.max_records = max(1, int(max_records))
        # the server this store belongs to: a cursor names it, so a cursor of another server is refused (G7)
        self.server_instance_id = server_instance_id or uuid.uuid4().hex
        self.max_bytes = max(4096, int(max_bytes))
        self.lock = threading.Lock()
        self.records = []                  # oldest first
        self.bytes = 0
        self.seq = 0
        self.counters = {
            "requests_total": 0, "requests_completed": 0, "requests_cancelled": 0, "requests_failed": 0,
            "prompt_tokens_submitted": 0, "prompt_tokens_matched": 0, "prompt_tokens_reused": 0,
            "prompt_tokens_evaluated": 0, "prompt_tokens_replayed": 0, "prompt_evaluation_work_tokens": 0,
            "generated_tokens": 0, "emitted_tokens": 0, "speculative_draft_tokens": 0,
            "speculative_accepted_tokens": 0, "cache_restore_attempts": 0, "cache_restore_failures": 0,
            "cache_evictions": 0, "retention_evictions": 0, "dropped_records": 0, "instrumentation_errors": 0,
            # the ELIGIBLE population of the cache-reuse ratio: the requests that have BOTH a submitted prompt and a
            # measured reuse.  The numerator and the denominator come from this population only, so the ratio is
            # not distorted by the requests whose accounting is incomplete (G6).
            "requests_reuse_accounted": 0, "prompt_tokens_reused_eligible": 0,
            "prompt_tokens_submitted_eligible": 0,
            # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-02 (A4): the LIFECYCLE accounting is independent of
            # the record's own insertion: a request is counted as accepted when it is admitted, and it gets exactly
            # one terminal outcome - whether or not its telemetry record could be sealed, stored or written.  The
            # receipt counters beside them say how many records were actually delivered.
            "requests_accepted": 0, "requests_terminal_completed": 0, "requests_terminal_cancelled": 0,
            "requests_terminal_failed": 0, "requests_terminal_rejected": 0,
            "receipts_created": 0, "receipt_delivery_failures": 0,
            "records_aggregate_eligible": 0, "records_aggregate_excluded": 0,
        }
        # the engine's own eviction counter, per engine instance: it restarts with the engine, and a counter that
        # falls would be a counter that lies (G6)
        self._evictions_by_engine = {}
        # The duration histograms, in SECONDS: name -> {"sum": seconds, "n": count, "buckets": [cumulative counts]}.
        # The record keeps its timings in milliseconds (the record's own unit is named in the section), and the store
        # converts them ONCE, here, when it observes them.  Everything downstream of this line is seconds.
        self.histograms = {}

    # ------------------------------------------------------------------ writing
    def begin_request(self):
        """Count an ACCEPTED request, at the admission boundary (AMENDMENT-02, A4).

        This counter does not depend on the telemetry record: a request whose record can never be sealed is still an
        accepted request, and the terminal accounting must balance against it.
        """
        with self.lock:
            self.counters["requests_accepted"] += 1

    def end_request(self, state):
        """Count ONE terminal outcome for an accepted request (AMENDMENT-02, A4)."""
        key = {"completed": "requests_terminal_completed", "cancelled": "requests_terminal_cancelled",
               "failed": "requests_terminal_failed", "rejected": "requests_terminal_rejected"}.get(state)
        if key is None:
            return
        with self.lock:
            self.counters[key] += 1

    def receipt_failed(self):
        """A terminal receipt that could not be delivered (sealing, storing or writing it failed)."""
        with self.lock:
            self.counters["receipt_delivery_failures"] += 1

    def add(self, record: RequestRecord) -> dict:
        """Seal the record, keep it, and count it.  Returns the record's dict (what the API hands out)."""
        with self.lock:
            self.seq += 1
            record.seq = self.seq
            data = record.to_dict()
            data["seq"] = self.seq
            size = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            self.records.append((self.seq, data, size))
            self.bytes += size
            self._evict_locked()
            self.counters["receipts_created"] += 1
            self._count_locked(data)
        return data

    def _evict_locked(self):
        """The old records go first, until the store is inside both ceilings."""
        while self.records and (len(self.records) > self.max_records or self.bytes > self.max_bytes):
            _, _, size = self.records.pop(0)
            self.bytes -= size
            self.counters["retention_evictions"] += 1

    def _count_locked(self, data):
        """The process-lifetime counters.  A counter only moves when a measurement exists: an unavailable
        measurement is not counted as zero.

        ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-02 (G1): a measurement enters an authoritative aggregate
        only when it is VALID, its ACCOUNTING is not violated and - for the engine's own numbers - its RECEIPT is
        correlated to this request.  A record that fails any of these stays in the store as a diagnostic receipt and
        contributes NOTHING to the totals: an invalid or unattributed measurement never distorts them, and a counter
        never falls because one was admitted.
        """
        c = self.counters
        c["requests_total"] += 1
        state = data["lifecycle"]["state"]
        if state == "completed":
            c["requests_completed"] += 1
        elif state == "cancelled":
            c["requests_cancelled"] += 1
        elif state in ("failed", "rejected"):
            c["requests_failed"] += 1
        quality = data["measurement_quality"]
        # the three decisions, kept apart (AMENDMENT-02, G1): the numbers are valid, the accounting holds, and the
        # engine's receipt is correlated to this request.
        valid = bool(quality.get("measurement_valid"))
        accounting_ok = (quality.get("accounting") or {}).get("state") != "violated"
        correlated = quality.get("native_correlation") == "verified" and not quality.get("native_partial")
        eligible = bool(quality.get("aggregate_eligible"))
        prompt, gen, cache = data["prompt"], data["generation"], data["cache"]
        # the tokens the SERVER measured (the submitted prompt) and the tokens the ENGINE measured (the match, the
        # reuse, the evaluation): the engine's numbers need a correlated receipt, the server's do not.
        for key, counter, native in (("submitted_tokens", "prompt_tokens_submitted", False),
                                     ("matched_prefix_tokens", "prompt_tokens_matched", True),
                                     ("reused_prefix_tokens", "prompt_tokens_reused", True),
                                     ("evaluated_tokens", "prompt_tokens_evaluated", True),
                                     ("replayed_tokens", "prompt_tokens_replayed", True),
                                     ("evaluation_work_tokens", "prompt_evaluation_work_tokens", True)):
            value = prompt.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                continue                            # not a measurement: it is not counted
            if native:
                if not (valid and accounting_ok and correlated):
                    continue                        # unattributed or invalid: not an authoritative number
            elif not (valid and accounting_ok):
                continue                            # the server's own number is valid, or it is not counted
            c[counter] += value
        for key, counter in (("generated_tokens", "generated_tokens"), ("emitted_tokens", "emitted_tokens"),
                             ("speculative_draft_tokens", "speculative_draft_tokens"),
                             ("speculative_accepted_tokens", "speculative_accepted_tokens")):
            value = gen.get(key)
            # the engine's own generation counters need a correlated receipt too
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                continue
            if key in ("generated_tokens", "speculative_draft_tokens", "speculative_accepted_tokens") \
                    and not (valid and accounting_ok and correlated):
                continue
            if key == "emitted_tokens" and not (valid and accounting_ok):
                continue
            c[counter] += value
        if cache.get("restore_attempted") is True and valid and accounting_ok and correlated:
            c["cache_restore_attempts"] += 1
            if cache.get("restore_succeeded") is False:
                c["cache_restore_failures"] += 1
        evictions = cache.get("evictions")
        if isinstance(evictions, int) and not isinstance(evictions, bool) and valid and accounting_ok and correlated:
            instance = data["identity"].get("engine_instance_id") or "unknown"
            previous = self._evictions_by_engine.get(instance, 0)
            # AMENDMENT-02 (G5): the engine's own counter is a HIGH-WATER MARK per engine instance: it only goes
            # up inside one instance, and a smaller reading (a counter that fell, or a receipt that arrived out of
            # order) never lowers the mark and never lowers the total.
            if evictions >= previous:
                c["cache_evictions"] += evictions - previous
                self._evictions_by_engine[instance] = evictions
        submitted = prompt.get("submitted_tokens")
        reused = prompt.get("reused_prefix_tokens")
        # the ELIGIBLE population of the cache-reuse ratio: the requests whose reuse accounting is complete AND
        # correlated.  Its numerator and denominator come from this population only, so the ratio stays in [0, 1].
        if (isinstance(submitted, int) and not isinstance(submitted, bool) and submitted >= 0
                and isinstance(reused, int) and not isinstance(reused, bool) and 0 <= reused <= submitted
                and valid and accounting_ok and correlated):
            c["requests_reuse_accounted"] += 1
            c["prompt_tokens_reused_eligible"] += reused
            c["prompt_tokens_submitted_eligible"] += submitted
        if data["measurement_quality"]["state"] == INSTRUMENTATION_ERROR:
            c["instrumentation_errors"] += 1
        if eligible:
            c["records_aggregate_eligible"] += 1
        else:
            c["records_aggregate_excluded"] += 1
        self._observe_locked(data)

    def _observe_locked(self, data):
        """The duration histograms: what the Prometheus exporter reads.

        An unavailable duration is NOT observed - it would be a zero, and a zero is a measured zero.  The record's
        timings are milliseconds; the conversion to seconds happens ONCE, in serve/reqtelemetry/metrics.py, and the
        histogram keeps the real cumulative bucket counts (a bucket says how many observations were at or below it -
        not the total count).
        """
        timing = data["timing_ms"]
        for name, metric in DURATION_METRICS:
            observe_duration(self.histograms, metric, timing.get(name))

    # ------------------------------------------------------------------ reading
    def get(self, request_id):
        """One record by its server id, or None."""
        with self.lock:
            for _, data, _ in self.records:
                if data["identity"]["request_id"] == request_id:
                    return data
        return None

    def list(self, limit=DEFAULT_PAGE_SIZE, cursor=None, client_request_id=None, state=None, disposition=None):
        """A page of records, newest first.

        The page is stable while new records arrive: the cursor names the sequence number of the last record of the
        previous page, and only records OLDER than it are returned.  A record that is evicted between two pages
        simply is not in the next page - the cursor never skips back to a newer record.
        """
        limit = max(1, min(int(limit), MAXIMUM_PAGE_SIZE))
        after = None
        if cursor:
            after = decode_cursor(cursor, self.server_instance_id, CURSOR_TTL_S)
            with self.lock:
                newest = self.seq
                oldest = self.records[0][0] if self.records else None
            # AMENDMENT-02 (G6): a cursor that names a record this store never wrote, or one whose page was already
            # evicted, is REFUSED.  It is never treated as an exhausted collection: the operator sees an error.
            if after > newest:
                raise ValueError("the cursor names a record this server never wrote")
            if oldest is not None and after < oldest - 1:
                raise ValueError("the records of this page are no longer retained")
        with self.lock:
            rows = [data for _, data, _ in self.records]
        rows.reverse()                                   # newest first
        out, last = [], None
        for data in rows:
            seq = data.get("seq")
            if after is not None and seq is not None and seq >= after:
                continue
            identity = data["identity"]
            if client_request_id and identity.get("client_request_id") != client_request_id:
                continue
            if state and data["lifecycle"].get("state") != state:
                continue
            if disposition and data["cache"].get("disposition") != disposition:
                continue
            out.append(data)
            last = seq
            if len(out) >= limit:
                break
        return {"records": out,
                "next_cursor": (encode_cursor(last, self.server_instance_id)
                                if last is not None and len(out) == limit else None)}

    def summary(self) -> dict:
        """The process-lifetime totals and what the store holds.  The totals never fall when a record is evicted."""
        with self.lock:
            eligible = self.counters["requests_reuse_accounted"]
            submitted = self.counters["prompt_tokens_submitted_eligible"]
            reused = self.counters["prompt_tokens_reused_eligible"]
            total = self.counters["requests_total"]
            return {
                "counters": dict(self.counters),
                # AMENDMENT-02 (A4): the lifecycle accounting, independent of the records' own insertion.  At
                # quiescence: accepted = completed + cancelled + failed + rejected.
                "lifecycle": {
                    "accepted": self.counters["requests_accepted"],
                    "completed": self.counters["requests_terminal_completed"],
                    "cancelled": self.counters["requests_terminal_cancelled"],
                    "failed": self.counters["requests_terminal_failed"],
                    "rejected": self.counters["requests_terminal_rejected"],
                    "receipts_created": self.counters["receipts_created"],
                    "receipt_delivery_failures": self.counters["receipt_delivery_failures"],
                },
                # the cache-reuse ratio, with BOTH of its numbers and the coverage of the population it covers
                "cache_reuse": {"ratio": round(reused / submitted, 6) if submitted else None,
                                "reused_tokens": reused, "submitted_tokens": submitted,
                                "eligible_requests": eligible, "requests": total,
                                "coverage": round(eligible / total, 6) if total else None},
                "histograms": {k: {"sum": v["sum"], "count": v["n"],
                                   "buckets": {str(edge): v["buckets"][i]
                                               for i, edge in enumerate(DURATION_BUCKETS)}}
                               for k, v in self.histograms.items()},
                "retention": {
                    "records": len(self.records),
                    "max_records": self.max_records,
                    "bytes": self.bytes,
                    "max_bytes": self.max_bytes,
                    "evictions": self.counters["retention_evictions"],
                    "dropped_records": self.counters["dropped_records"],
                    "durable": False,
                },
            }
