"""serve/reqtelemetry/store.py - the bounded store of recent records and the process-lifetime counters (G9).

The store is bounded by BOTH a record count and a byte budget: a very long request cannot push the store over its
memory ceiling.  It is intentionally NOT durable: nothing is written to disk here, and a restart empties it.  The
counters live here and never fall when a record is evicted - they are the process-lifetime totals.
"""
from __future__ import annotations

import json
import threading
import uuid

from serve.reqtelemetry import accounting as ACCOUNTING
from serve.reqtelemetry.metrics import DURATION_BUCKETS, DURATION_METRICS, observe_duration
from serve.reqtelemetry.record import decode_cursor, encode_cursor
from serve.reqtelemetry.vocabulary import (CURSOR_TTL_S, DEFAULT_PAGE_SIZE, DEFAULT_RETENTION_BYTES,
                                         DEFAULT_RETENTION_RECORDS, INSTRUMENTATION_ERROR, MAXIMUM_PAGE_SIZE,
                                         MAX_ENGINE_INSTANCES)

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
            # AMENDMENT-03 (G5): the loss of the EVIDENCE delivery is its own domain: the receipt may be in the
            # store while the evidence line never reached the disk.  The two are not the same failure.
            "evidence_delivery_failures": 0,
            "records_aggregate_eligible": 0, "records_aggregate_excluded": 0,
            # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-03 (G2c): the COVERAGE of the accounting, with
            # the eligible population and the missing population beside it.  The population is the native
            # INVOCATION: a receipt that never arrived is in the missing population, so a lost receipt lowers the
            # coverage instead of silently improving it.
            "native_invocations": 0, "native_invocations_accounted": 0, "native_invocations_missing": 0,
            # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (C2): the receipts that did not fit the bounds.
            # They are missing EVIDENCE: the invocation happened, its receipt did not survive.
            "native_invocations_dropped": 0,
            "requests_with_complete_accounting": 0,
            # the positions of the invocations whose prompt domain is NOT the request's own prompt domain (a
            # recovery dispatch that sent another prompt): they are work, never the request's prompt coverage
            "native_positions_matched_total": 0, "native_positions_reused_total": 0,
            "native_positions_evaluated_total": 0,
            # the evictions of an engine whose identity is unknown: they cannot be attributed to a domain
            "cache_evictions_unattributed": 0,
            # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (C5a): the observations that were REFUSED from
            # the authoritative total because their engine's retired reading was gone - the attribution was
            # unavailable, and the work was not counted twice.
            "cache_evictions_attribution_unavailable": 0,
        }
        # the engine's own eviction counter, per engine instance: it restarts with the engine, and a counter that
        # falls would be a counter that lies (G6)
        self._evictions_by_engine = {}
        # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (C5a): the RETIRED engines' last readings.  They are
        # kept (bounded) so that a DELAYED observation of a retired engine is compared with its own last reading
        # instead of being counted again from zero.  The engines whose reading is gone are remembered as
        # unattributable, so their later observations are refused rather than counted twice.
        self._retired_evictions = {}
        self._unattributable_engines = set()
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

    def end_request(self, state, record=None):
        """Count ONE terminal outcome for an accepted request (AMENDMENT-02, A4).

        ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (C2): the terminal outcome is counted BEFORE the
        receipt is sealed and stored, so a request whose terminal receipt is lost still counts in the physical
        request's own population.  The record is marked, so the outcome is counted exactly ONCE (the store's own
        `add` does not count it a second time).
        """
        key = {"completed": "requests_terminal_completed", "cancelled": "requests_terminal_cancelled",
               "failed": "requests_terminal_failed", "rejected": "requests_terminal_rejected"}.get(state)
        if key is None:
            return
        with self.lock:
            self.counters[key] += 1
        if record is not None:
            record._terminal_counted = True

    def receipt_failed(self):
        """A terminal receipt that could not be delivered (sealing, storing or writing it failed)."""
        with self.lock:
            self.counters["receipt_delivery_failures"] += 1

    def evidence_failed(self):
        """The evidence line of a receipt was REFUSED by the writer: the receipt is in the store, the evidence
        line never reached the disk.  It is its own domain (G5)."""
        with self.lock:
            self.counters["evidence_delivery_failures"] += 1

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
            # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (C2): the physical request's own population is the
            # requests that reached a terminal outcome.  A record that arrives WITHOUT its terminal outcome having
            # been counted (a caller that stores the receipt itself) counts it here - exactly once.
            if not getattr(record, "_terminal_counted", False):
                key = {"completed": "requests_terminal_completed", "cancelled": "requests_terminal_cancelled",
                       "failed": "requests_terminal_failed", "rejected": "requests_terminal_rejected"}.get(
                           data["lifecycle"]["state"])
                if key is not None:
                    self.counters[key] += 1
                    record._terminal_counted = True
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

        ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-03 (G1, G2): the counters are fed by the record's own
        HTTP-owned measurements and by the PER-INVOCATION receipts - never by a summary of several invocations.
        A native measurement is counted only when ITS OWN metric class admits it (serve/reqtelemetry/accounting.py):
        the prompt positions need a correlated receipt and an accounting that is not violated, the work counters
        keep their own authority, the durations need a correlated WHOLE invocation, and the complete cache-reuse
        ratio needs an accounting that SATISFIED.  The same native work is never counted twice: a measurement that
        the parent mirrors from its single receipt is counted from the receipt, not from the parent.
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
        prompt, gen = data["prompt"], data["generation"]
        # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (D3): the HTTP-owned measurements are admitted on
        # THEIR OWN terms.  The server measured them itself; the native token accounting says nothing about them,
        # so a broken NATIVE accounting never suppresses the HTTP counter (and the record's own admission
        # decision - METRIC_HTTP is always admitted - agrees with what the store does).
        submitted = prompt.get("submitted_tokens")
        if isinstance(submitted, int) and not isinstance(submitted, bool) and submitted >= 0:
            c["prompt_tokens_submitted"] += submitted
        emitted = gen.get("emitted_tokens")
        if isinstance(emitted, int) and not isinstance(emitted, bool) and emitted >= 0:
            c["emitted_tokens"] += emitted
        # the native measurements: every invocation's own receipt decides for itself
        request_submitted = prompt.get("submitted_tokens")
        accounted_request = False
        for invocation in data.get("invocations") or []:
            if self._count_invocation_locked(c, invocation, request_submitted):
                accounted_request = True
        # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (C2): the invocation denominator is the DISPATCHED
        # population, not the retained one.  A receipt that was dropped is a MISSING invocation: the coverage falls,
        # it never improves.  The dispatched count comes from the record's own dispatch accounting, so it is
        # independent of the receipts that survived.
        dispatched = int(quality.get("invocations_dispatched") or 0)
        retained = len(data.get("invocations") or [])
        dropped = max(0, dispatched - retained)
        if dropped:
            # the receipts that did not fit: they are in the missing population, never in the accounted one
            c["native_invocations_missing"] += dropped
            c["native_invocations_dropped"] += dropped
        # the invocation population: every native invocation this request performed, whether its receipt survived
        # or not.  It is counted from the DISPATCH accounting, never from the retained receipts alone.
        c["native_invocations"] += retained + dropped
        if accounted_request:
            c["requests_with_complete_accounting"] += 1
        if quality.get("state") == INSTRUMENTATION_ERROR:
            c["instrumentation_errors"] += 1
        if quality.get("aggregate_eligible"):
            c["records_aggregate_eligible"] += 1
        else:
            c["records_aggregate_excluded"] += 1
        self._observe_locked(data)

    def _count_invocation_locked(self, c, invocation, request_submitted) -> bool:
        """One native invocation's receipt, counted under its OWN metric classes (G1, G2).

        True when this invocation's accounting SATISFIED - that is, when it belongs to the eligible population of
        the complete cache-reuse ratio.
        """
        iq = invocation.get("measurement_quality") or {}
        admission = iq.get("admission") or {}
        iprompt = invocation.get("prompt") or {}
        icache = invocation.get("cache") or {}
        igen = invocation.get("generation") or {}
        # the eligible and the missing populations of the accounting coverage (G2c).  The POPULATION itself is
        # counted by the caller, from the dispatch accounting (C2): a dropped receipt is missing evidence, not a
        # smaller population.
        eligible = bool(admission.get(ACCOUNTING.METRIC_COMPLETE_CACHE_RATIO))
        if eligible:
            c["native_invocations_accounted"] += 1
        else:
            c["native_invocations_missing"] += 1
        # the prompt positions: the REQUEST's own prompt domain only.  An invocation that worked on another
        # prompt (a recovery dispatch) is work, never this prompt's coverage.
        #
        # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (C4): the domain is the NAME the dispatch boundary
        # gave it, NOT the prompt's length.  Two different prompts of the same length are two domains, and two
        # invocations of the SAME prompt are one domain.  An invocation whose domain was not named (an older
        # caller) falls back to the length comparison.
        domain = iprompt.get("domain")
        if domain is None:
            same_domain = (request_submitted is None or iprompt.get("submitted_tokens") is None
                           or iprompt.get("submitted_tokens") == request_submitted)
        else:
            same_domain = domain == "request"
        if admission.get(ACCOUNTING.METRIC_NATIVE_PROMPT_POSITION):
            for key, counter, total in (("matched_prefix_tokens", "prompt_tokens_matched",
                                         "native_positions_matched_total"),
                                        ("reused_prefix_tokens", "prompt_tokens_reused",
                                         "native_positions_reused_total"),
                                        ("evaluated_tokens", "prompt_tokens_evaluated",
                                         "native_positions_evaluated_total")):
                value = iprompt.get(key)
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    continue
                c[total] += value
                if same_domain:
                    c[counter] += value
        # the work counters: they keep their own authority - an UNEVALUATED accounting does not exclude them
        if admission.get(ACCOUNTING.METRIC_NATIVE_EXECUTION_WORK):
            for key, counter in (("replayed_tokens", "prompt_tokens_replayed"),
                                 ("evaluation_work_tokens", "prompt_evaluation_work_tokens")):
                value = iprompt.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    c[counter] += value
        # the engine's own generation counters
        if admission.get(ACCOUNTING.METRIC_NATIVE_GENERATION):
            for key, counter in (("generated_tokens", "generated_tokens"),
                                 ("speculative_draft_tokens", "speculative_draft_tokens"),
                                 ("speculative_accepted_tokens", "speculative_accepted_tokens")):
                value = igen.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    c[counter] += value
        # the restoration's outcome
        if admission.get(ACCOUNTING.METRIC_CACHE_RESTORE) and icache.get("restore_attempted") is True:
            c["cache_restore_attempts"] += 1
            if icache.get("restore_succeeded") is False:
                c["cache_restore_failures"] += 1
        # the engine's own eviction counter: a HIGH-WATER MARK per engine instance (G5)
        evictions = icache.get("evictions")
        if isinstance(evictions, int) and not isinstance(evictions, bool) and evictions >= 0 \
                and admission.get(ACCOUNTING.METRIC_NATIVE_PROMPT_POSITION):
            self._count_evictions_locked(c, (invocation.get("identity") or {}).get("engine_instance_id"), evictions)
        # the complete cache-reuse ratio: the numerator and the denominator come from THIS invocation, so the
        # ratio stays in [0, 1] and the population is the invocations whose accounting closed
        if eligible:
            submitted = iprompt.get("submitted_tokens")
            reused = iprompt.get("reused_prefix_tokens")
            if isinstance(submitted, int) and not isinstance(submitted, bool) and submitted >= 0 \
                    and isinstance(reused, int) and not isinstance(reused, bool) and 0 <= reused <= submitted:
                c["requests_reuse_accounted"] += 1
                c["prompt_tokens_reused_eligible"] += reused
                c["prompt_tokens_submitted_eligible"] += submitted
        return eligible

    def _count_evictions_locked(self, c, instance, evictions):
        """The engine's eviction counter, per engine instance (G5).

        AMENDMENT-03 (G5): an engine whose identity is UNKNOWN is not merged into a domain: its counter cannot be
        attributed to an engine process, so it is published as unattributed instead of pretending that two
        different engines are one.  The retired instances' state is BOUNDED: the oldest mark goes when the bound
        is reached, so a long run does not grow the state without limit.

        ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (C5a): retiring an engine's mark must not FORGET its
        counter domain.  The predecessor deleted the mark when the bound was reached, so a LATE observation of
        that engine looked like a first observation and its whole cumulative counter was counted again - the same
        work was counted twice.  Now a retired engine's last reading is kept in a SEPARATE, equally bounded map
        of RETIRED domains: a late observation of a retired engine is compared against that reading and only its
        DELTA is counted.  The retired map is bounded too, and when a retired reading is dropped from it the
        domain is remembered as UNATTRIBUTABLE: a later observation of that engine is then refused from the
        authoritative total and counted as an unavailable attribution - never counted again as if it were new.
        """
        if not instance:
            c["cache_evictions_unattributed"] += evictions
            return
        if instance in self._evictions_by_engine:
            previous = self._evictions_by_engine[instance]
            if evictions >= previous:
                c["cache_evictions"] += evictions - previous
                self._evictions_by_engine[instance] = evictions
        elif instance in self._retired_evictions:
            # a DELAYED observation of a retired engine: only the increase since its last reading is new work
            previous = self._retired_evictions[instance]
            if evictions >= previous:
                c["cache_evictions"] += evictions - previous
                self._retired_evictions[instance] = evictions
        elif instance in self._unattributable_engines:
            # the retired reading of this engine is gone: its exact delta cannot be recovered, so the
            # observation is REFUSED from the authoritative total and the attribution is counted as unavailable
            c["cache_evictions_unattributed"] += evictions
            c["cache_evictions_attribution_unavailable"] += 1
            return
        else:
            # a first observation of this engine: its whole counter is new work
            c["cache_evictions"] += evictions
            self._evictions_by_engine[instance] = evictions
        while len(self._evictions_by_engine) > MAX_ENGINE_INSTANCES:
            oldest = next(iter(self._evictions_by_engine))
            self._retired_evictions[oldest] = self._evictions_by_engine.pop(oldest)
            while len(self._retired_evictions) > MAX_ENGINE_INSTANCES:
                # the retired reading goes: the engine's counter domain is no longer recoverable, so it is
                # remembered as unattributable (a BOUNDED set, not unbounded tombstone storage)
                gone = next(iter(self._retired_evictions))
                del self._retired_evictions[gone]
                self._unattributable_engines.add(gone)
                while len(self._unattributable_engines) > MAX_ENGINE_INSTANCES:
                    self._unattributable_engines.pop()


    def _observe_locked(self, data):
        """The duration histograms: what the Prometheus exporter reads.

        An unavailable duration is NOT observed - it would be a zero, and a zero is a measured zero.  The record's
        timings are milliseconds; the conversion to seconds happens ONCE, in serve/reqtelemetry/metrics.py, and the
        histogram keeps the real cumulative bucket counts (a bucket says how many observations were at or below it -
        not the total count).

        ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-03 (G2b): the durations are admitted by their OWN class.
        The HTTP-owned durations (the queue wait, the total, the time to the first byte) are the server's own
        measurements and are always observed.  A NATIVE duration is observed only from the invocation receipt that
        measured it, and only when that receipt is CORRELATED to its invocation and covers the WHOLE invocation:
        an uncorrelated duration is somebody else's measurement, and a batch slot's admission segment is not the
        whole invocation.  The parent's copy of a native duration is not observed again - it is the receipt's
        measurement, and it is observed once, there.
        """
        timing = data["timing_ms"]
        authority = (data["measurement_quality"] or {}).get("timing_authority") or {}
        for name, metric in DURATION_METRICS:
            if authority.get(name) == "native_engine":
                continue                        # the receipt's own duration: it is observed there, once
            observe_duration(self.histograms, metric, timing.get(name))
        for invocation in data.get("invocations") or []:
            iq = invocation.get("measurement_quality") or {}
            admission = iq.get("admission") or {}
            if not admission.get(ACCOUNTING.METRIC_NATIVE_DURATION):
                continue                        # not correlated, or only a segment of the invocation
            itiming = invocation.get("timing_ms") or {}
            for name, metric in DURATION_METRICS:
                observe_duration(self.histograms, metric, itiming.get(name))

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
        # AMENDMENT-03 (G5): the cursor's validation and the page come from ONE snapshot of the store.  The
        # validation used to read the retention bounds, release the lock and only then read the rows: a record
        # evicted in between made the validation and the page disagree about the same collection.
        after = decode_cursor(cursor, self.server_instance_id, CURSOR_TTL_S) if cursor else None
        with self.lock:
            newest = self.seq
            oldest = self.records[0][0] if self.records else None
            # AMENDMENT-02 (G6): a cursor that names a record this store never wrote, or one whose page was already
            # evicted, is REFUSED.  It is never treated as an exhausted collection: the operator sees an error.
            if after is not None:
                if after > newest:
                    raise ValueError("the cursor names a record this server never wrote")
                if oldest is not None and after < oldest - 1:
                    raise ValueError("the records of this page are no longer retained")
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
            # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (C2): the requests that reached a TERMINAL
            # OUTCOME.  This is the physical request's own denominator: it is independent of the receipts that were
            # stored, so a lost terminal receipt lowers the coverage instead of shrinking the population.
            terminal = (self.counters["requests_terminal_completed"]
                        + self.counters["requests_terminal_cancelled"]
                        + self.counters["requests_terminal_failed"]
                        + self.counters["requests_terminal_rejected"])
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
                # the cache-reuse ratio, with BOTH of its numbers and the coverage of the population it covers.
                # AMENDMENT-03 (G2c): the population is the native INVOCATION whose accounting closed; the
                # missing population is published beside it, so a lost receipt lowers the coverage instead of
                # silently improving it.  The physical HTTP request's own coverage is published separately.
                "cache_reuse": {"ratio": round(reused / submitted, 6) if submitted else None,
                                "reused_tokens": reused, "submitted_tokens": submitted,
                                "eligible_requests": eligible, "requests": total,
                                "eligible_invocations": self.counters["native_invocations_accounted"],
                                "missing_invocations": self.counters["native_invocations_missing"],
                                "invocations": self.counters["native_invocations"],
                                "dropped_invocations": self.counters["native_invocations_dropped"],
                                "requests_with_complete_accounting":
                                    self.counters["requests_with_complete_accounting"],
                                "coverage": round(self.counters["native_invocations_accounted"]
                                                  / self.counters["native_invocations"], 6)
                                if self.counters["native_invocations"] else None,
                                # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01 (C2): the physical request's own
                                # coverage is measured against the requests that REACHED A TERMINAL OUTCOME, not
                                # against the receipts that were stored: a request whose terminal receipt was lost
                                # lowers the coverage instead of disappearing from the denominator.  A request that
                                # is still running is not in the population - its outcome is not known yet.
                                "request_coverage": round(self.counters["requests_with_complete_accounting"]
                                                          / terminal, 6) if terminal else None},
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
