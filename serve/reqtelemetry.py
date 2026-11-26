"""serve/reqtelemetry.py - the canonical per-request telemetry record (ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01).

One versioned, machine-readable record per physical request attempt.  It is METADATA ONLY: no prompt, no answer,
no reasoning, no token ids, no hash of the prompt.  Two authorities write into it:

  * the NATIVE ENGINE owns the cache state and the model execution: the prompt tokens it was given, the prefix it
    actually reused, the tokens it read, the prefill and decode time, the drafts it offered and accepted, and the
    reason it ended.  Those numbers arrive on the request's own DONE line (serve/server.py: StrataEngine._parse_done),
    which is the request's own channel - not a log that is read afterwards and matched by position.
  * the HTTP SERVER owns the request lifecycle: the queue wait, the template render, the tokenization, the model
    load, the time to the first byte the client sees, the total time, and the HTTP status.

The record keeps the two apart and says which is which.  A number that was not measured is null, never 0: 0 is a
measured zero, and a null says "this was not measured here" (measurement_quality says why).

The store keeps the last N records in memory (bounded by count AND by bytes).  It is not durable and it does not
grow: the process-lifetime counters are separate and never fall when a record is evicted.
"""
from __future__ import annotations

import base64
import json
import threading
import time
import uuid

SCHEMA_VERSION = "strata.request-telemetry/1"

# The measurement quality of a record as a whole, and of a single field.
COMPLETE = "complete"
PARTIAL = "partial"
UNSUPPORTED = "unsupported"
INSTRUMENTATION_ERROR = "instrumentation_error"

# The cache source vocabulary (what the reusable prefix came from).
SOURCE_NONE = "none"
SOURCE_RESIDENT_SLOT = "resident_slot"
SOURCE_CONVERSATION_CACHE = "conversation_cache"
SOURCE_RESTORED_CHECKPOINT = "restored_checkpoint"
SOURCE_MULTIPLE = "multiple"
SOURCE_UNKNOWN = "unknown"
SOURCES = (SOURCE_NONE, SOURCE_RESIDENT_SLOT, SOURCE_CONVERSATION_CACHE, SOURCE_RESTORED_CHECKPOINT,
           SOURCE_MULTIPLE, SOURCE_UNKNOWN)

# The cache disposition vocabulary (what the engine did with it), derived from evidence only - never from a
# duration or a rate.
DISPOSITION_COLD_MISS = "cold_miss"
DISPOSITION_FULL_HIT = "full_hit"
DISPOSITION_PARTIAL_HIT = "partial_hit"
DISPOSITION_MATCH_WITHOUT_STATE = "match_without_usable_state"
DISPOSITION_BYPASSED = "bypassed"
DISPOSITION_INVALIDATED = "invalidated"
DISPOSITION_UNKNOWN = "unknown"
DISPOSITIONS = (DISPOSITION_COLD_MISS, DISPOSITION_FULL_HIT, DISPOSITION_PARTIAL_HIT,
                DISPOSITION_MATCH_WITHOUT_STATE, DISPOSITION_BYPASSED, DISPOSITION_INVALIDATED, DISPOSITION_UNKNOWN)

# The request states a record can end in.
STATES = ("queued", "running", "completed", "cancelled", "failed", "rejected")

# The limits (the defaults; the run config may lower or raise them within the bounds below).
DEFAULT_PAGE_SIZE = 100
MAXIMUM_PAGE_SIZE = 500
DEFAULT_RETENTION_RECORDS = 2048
DEFAULT_RETENTION_BYTES = 16 << 20          # 16 MiB

# The client's own request id: what may be in it.  It is a label for the operator, never a key and never a
# credential: it may not authenticate anything and it is never the internal primary key.
CLIENT_ID_MAX = 128
CLIENT_ID_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")


def valid_client_request_id(value) -> bool:
    """True when a client-supplied request id may be kept: printable ASCII, bounded, no whitespace or control
    characters.  Anything else is dropped (the request still runs; it just has no client id)."""
    if not isinstance(value, str) or not value or len(value) > CLIENT_ID_MAX:
        return False
    return all(c in CLIENT_ID_ALLOWED for c in value)


def new_request_id() -> str:
    """The server's own id for one physical request attempt: unique, opaque, and never derived from the client's
    id, so two requests that carry the same client id stay two records."""
    import uuid
    return uuid.uuid4().hex


def encode_cursor(seq: int) -> str:
    """The pagination cursor: the sequence number of the last record of the previous page, encoded.  The number is
    a monotonic counter, so a page stays stable while new records arrive at the head."""
    return base64.urlsafe_b64encode(f"seq:{seq}".encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> int:
    """The sequence number a cursor names.  Raises ValueError for a cursor this server did not write."""
    if not isinstance(cursor, str) or not cursor:
        raise ValueError("the cursor is empty")
    pad = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + pad).decode()
    except (ValueError, UnicodeDecodeError):
        raise ValueError("the cursor is not a cursor this server wrote") from None
    if not raw.startswith("seq:"):
        raise ValueError("the cursor is not a cursor this server wrote")
    try:
        return int(raw[4:])
    except ValueError:
        raise ValueError("the cursor is not a cursor this server wrote") from None


def _num(value):
    """A number or None: 0 stays 0 (a measured zero), anything that is not a number becomes null."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


class RequestRecord:
    """One request's telemetry, built up while it runs and sealed when it ends.

    Every setter takes the measurement and the authority that made it.  A measurement that was never made stays
    None, and the record says so in measurement_quality.
    """

    def __init__(self, request_id, client_request_id=None, server_instance_id=None, engine_instance_id=None,
                 model_id=None, build_revision=None, api=None):
        self.request_id = request_id
        self.seq = 0
        self.client_request_id = client_request_id if valid_client_request_id(client_request_id) else None
        self.server_instance_id = server_instance_id
        self.engine_instance_id = engine_instance_id
        self.engine_invocation_id = None
        self.slot_id = None
        self.model_id = model_id
        self.build_revision = build_revision
        self.api = api
        self.state = "queued"
        self.received_at = time.time()
        self.started_at = None
        self.finished_at = None
        self.http_status = None
        self.finish_reason = None
        self.outcome_detail = None
        # the prompt accounting (tokens)
        self.rendered_tokens = None
        self.submitted_tokens = None
        self.matched_prefix_tokens = None
        self.reused_prefix_tokens = None
        self.evaluated_tokens = None
        self.replayed_tokens = None
        self.non_prefix_reused_tokens = None
        self.evaluation_work_tokens = None
        self.first_divergent_token_index = None
        # the cache attribution
        self.cache_source = SOURCE_UNKNOWN
        self.cache_disposition = DISPOSITION_UNKNOWN
        self.cache_reason_code = None
        self.cache_restore_attempted = None
        self.cache_restore_succeeded = None
        self.cache_restore_ms = None
        self.cache_recurrent_state = None
        self.cache_attention_state = None
        self.cache_checkpoint_state = None
        self.cache_invalidations = None
        self.cache_evictions = None
        # the timings (milliseconds)
        self.timing = {}
        self.timing_authority = {}
        # the generation
        self.requested_max_output_tokens = None
        self.effective_max_output_tokens = None
        self.generated_tokens = None
        self.emitted_tokens = None
        self.speculative_draft_tokens = None
        self.speculative_accepted_tokens = None
        self.first_token_includes_reasoning = None
        # why a measurement is missing
        self.unavailable = {}
        self.quality = COMPLETE

    # ------------------------------------------------------------------ the measurements
    def mark_unavailable(self, field, reason, quality=UNSUPPORTED):
        """A measurement this server could not make: the field stays null and the record says why.  This is the
        only way a field becomes null - a number that was measured is never turned into null afterwards."""
        self.unavailable[field] = reason
        if quality == INSTRUMENTATION_ERROR:
            self.quality = INSTRUMENTATION_ERROR
        elif self.quality == COMPLETE:
            self.quality = PARTIAL

    def set_timing(self, name, ms, authority):
        """A duration in milliseconds, from a monotonic clock, with the authority that measured it."""
        value = _num(ms)
        if value is None:
            return
        self.timing[name] = round(float(value), 3)
        self.timing_authority[name] = authority

    def set_prompt_tokens(self, rendered=None, submitted=None, authority="server"):
        """The prompt's token counts.  `rendered` is the count after the template render and the tokenization;
        `submitted` is what the engine was actually given (the two differ when the server truncates)."""
        if rendered is not None:
            self.rendered_tokens = _num(rendered)
        if submitted is not None:
            self.submitted_tokens = _num(submitted)

    def set_native_cache(self, *, matched_prefix=None, reused_prefix=None, evaluated=None, replayed=None,
                         non_prefix_reused=None, evaluation_work=None, first_divergent=None,
                         source=None, disposition=None, reason_code=None, restore_attempted=None,
                         restore_succeeded=None, restore_ms=None, recurrent_state=None, attention_state=None,
                         checkpoint_state=None, invalidations=None, evictions=None):
        """What the NATIVE ENGINE measured about the cache and the prompt.

        `matched_prefix` is the contiguous token-prefix match against the selected candidate, BEFORE the execution
        state is considered.  `reused_prefix` is the contiguous prefix whose usable execution state was actually
        retained or restored - the two are different things and the record keeps them apart.  `evaluated` is the
        distinct prompt positions the engine evaluated; `evaluation_work` is the executed prompt-token evaluations
        (repeated work counts again).
        """
        if matched_prefix is not None:
            self.matched_prefix_tokens = _num(matched_prefix)
        if reused_prefix is not None:
            self.reused_prefix_tokens = _num(reused_prefix)
        if evaluated is not None:
            self.evaluated_tokens = _num(evaluated)
        if replayed is not None:
            self.replayed_tokens = _num(replayed)
        if non_prefix_reused is not None:
            self.non_prefix_reused_tokens = _num(non_prefix_reused)
        if evaluation_work is not None:
            self.evaluation_work_tokens = _num(evaluation_work)
        if first_divergent is not None:
            self.first_divergent_token_index = _num(first_divergent)
        if source is not None:
            self.cache_source = source
        if disposition is not None:
            self.cache_disposition = disposition
        if reason_code is not None:
            self.cache_reason_code = reason_code
        if restore_attempted is not None:
            self.cache_restore_attempted = restore_attempted
        if restore_succeeded is not None:
            self.cache_restore_succeeded = restore_succeeded
        if restore_ms is not None:
            self.cache_restore_ms = _num(restore_ms)
        if recurrent_state is not None:
            self.cache_recurrent_state = recurrent_state
        if attention_state is not None:
            self.cache_attention_state = attention_state
        if checkpoint_state is not None:
            self.cache_checkpoint_state = checkpoint_state
        if invalidations is not None:
            self.cache_invalidations = _num(invalidations)
        if evictions is not None:
            self.cache_evictions = _num(evictions)

    def set_generation(self, *, requested_max=None, effective_max=None, generated=None, emitted=None,
                       draft_tokens=None, accepted_tokens=None, finish_reason=None):
        """What was generated.  `requested_max` is what the client asked for; `effective_max` is what the server
        actually allowed (the context's room, a budget).  They are kept apart on purpose."""
        if requested_max is not None:
            self.requested_max_output_tokens = _num(requested_max)
        if effective_max is not None:
            self.effective_max_output_tokens = _num(effective_max)
        if generated is not None:
            self.generated_tokens = _num(generated)
        if emitted is not None:
            self.emitted_tokens = _num(emitted)
        if draft_tokens is not None:
            self.speculative_draft_tokens = _num(draft_tokens)
        if accepted_tokens is not None:
            self.speculative_accepted_tokens = _num(accepted_tokens)
        if finish_reason is not None:
            self.finish_reason = finish_reason

    # ------------------------------------------------------------------ the accounting rules
    def derive_disposition(self):
        """The cache disposition, from the evidence and nothing else.

        The rules, in order:
          * the engine matched the prompt but had no usable state for it -> match_without_usable_state;
          * nothing was reused at all -> cold_miss;
          * everything was reused -> full_hit;
          * some of it was reused -> partial_hit.
        A duration or a rate never decides this: a fast request with no reuse is still a cold miss.
        """
        if self.cache_disposition != DISPOSITION_UNKNOWN:
            return self.cache_disposition                    # the engine named it (an explicit reason code)
        matched, reused = self.matched_prefix_tokens, self.reused_prefix_tokens
        if matched is None and reused is None:
            return DISPOSITION_UNKNOWN
        if matched is not None and matched > 0 and not reused:
            return DISPOSITION_MATCH_WITHOUT_STATE
        if not reused:
            return DISPOSITION_COLD_MISS
        if self.submitted_tokens is not None and self.submitted_tokens > 0 \
                and reused >= self.submitted_tokens:
            return DISPOSITION_FULL_HIT
        return DISPOSITION_PARTIAL_HIT

    def conservation(self) -> list:
        """The accounting identities that must hold when the domains are equivalent, non-overlapping and complete.

        They are CHECKED, never enforced: a measurement is never adjusted to make the identity come out right.  A
        broken identity is reported so the operator sees that the accounting was incomplete.
        """
        problems = []
        matched, reused = self.matched_prefix_tokens, self.reused_prefix_tokens
        submitted, evaluated = self.submitted_tokens, self.evaluated_tokens
        if reused is not None and matched is not None and reused > matched:
            problems.append("reused_prefix_tokens is greater than matched_prefix_tokens")
        if matched is not None and submitted is not None and matched > submitted:
            problems.append("matched_prefix_tokens is greater than submitted_tokens")
        if reused is not None and submitted is not None and reused > submitted:
            problems.append("reused_prefix_tokens is greater than submitted_tokens")
        if self.replayed_tokens is not None and evaluated is not None and self.replayed_tokens > evaluated:
            problems.append("replayed_tokens is greater than evaluated_tokens")
        if self.evaluation_work_tokens is not None and evaluated is not None \
                and self.evaluation_work_tokens < evaluated:
            problems.append("evaluation_work_tokens is less than evaluated_tokens")
        if None not in (reused, evaluated, submitted) and self.non_prefix_reused_tokens is not None:
            if reused + self.non_prefix_reused_tokens + evaluated != submitted:
                problems.append("submitted_tokens is not reused + non_prefix_reused + evaluated")
        return problems

    def seal(self, state=None, http_status=None, finish_reason=None, detail=None):
        """Close the record: the state it ended in, and the checks that describe how complete it is.

        A record that was cancelled or that failed keeps the measurements it HAS (the work the engine really did) and
        says that the accounting is partial.  Nothing is invented to make it look complete.
        """
        if state is not None:
            self.state = state
        if http_status is not None:
            self.http_status = int(http_status)
        if finish_reason is not None:
            self.finish_reason = finish_reason
        if detail is not None:
            self.outcome_detail = detail
        self.finished_at = time.time()
        self.cache_disposition = self.derive_disposition()
        if self.state in ("cancelled", "failed", "rejected") and self.quality == COMPLETE:
            self.quality = PARTIAL
        if self.conservation():
            self.quality = PARTIAL
            self.unavailable.setdefault("accounting", "the token accounting does not close (see conservation)")
        return self

    # ------------------------------------------------------------------ the record itself
    def to_dict(self) -> dict:
        """The canonical record: the sections, in a fixed order, metadata only."""
        return {
            "schema_version": SCHEMA_VERSION,
            "identity": {
                "request_id": self.request_id,
                "client_request_id": self.client_request_id,
                "engine_instance_id": self.engine_instance_id,
                "server_instance_id": self.server_instance_id,
                "engine_invocation_id": self.engine_invocation_id,
                "slot_id": self.slot_id,
                "model_id": self.model_id,
                "build_revision": self.build_revision,
            },
            "lifecycle": {
                "state": self.state,
                "api": self.api,
                "received_at": self.received_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "http_status": self.http_status,
                "finish_reason": self.finish_reason,
                "detail": self.outcome_detail,
            },
            "prompt": {
                "rendered_tokens": self.rendered_tokens,
                "submitted_tokens": self.submitted_tokens,
                "matched_prefix_tokens": self.matched_prefix_tokens,
                "reused_prefix_tokens": self.reused_prefix_tokens,
                "evaluated_tokens": self.evaluated_tokens,
                "replayed_tokens": self.replayed_tokens,
                "non_prefix_reused_tokens": self.non_prefix_reused_tokens,
                "evaluation_work_tokens": self.evaluation_work_tokens,
                "first_divergent_token_index": self.first_divergent_token_index,
            },
            "cache": {
                "source": self.cache_source,
                "disposition": self.cache_disposition,
                "reason_code": self.cache_reason_code,
                "restore_attempted": self.cache_restore_attempted,
                "restore_succeeded": self.cache_restore_succeeded,
                "restore_ms": self.cache_restore_ms,
                "recurrent_state": self.cache_recurrent_state,
                "attention_state": self.cache_attention_state,
                "checkpoint_state": self.cache_checkpoint_state,
                "invalidations": self.cache_invalidations,
                "evictions": self.cache_evictions,
            },
            "timing_ms": {k: self.timing[k] for k in sorted(self.timing)},
            "generation": {
                "requested_max_output_tokens": self.requested_max_output_tokens,
                "effective_max_output_tokens": self.effective_max_output_tokens,
                "generated_tokens": self.generated_tokens,
                "emitted_tokens": self.emitted_tokens,
                "speculative_draft_tokens": self.speculative_draft_tokens,
                "speculative_accepted_tokens": self.speculative_accepted_tokens,
            },
            "measurement_quality": {
                "state": self.quality,
                "unavailable_fields": dict(sorted(self.unavailable.items())),
                "timing_authority": dict(sorted(self.timing_authority.items())),
                "first_token_includes_reasoning": self.first_token_includes_reasoning,
            },
        }


# ------------------------------------------------------------------------------------------------ the JSON Schema
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
            "required": ["state", "unavailable_fields", "timing_authority", "first_token_includes_reasoning"],
            "additionalProperties": False,
            "properties": {
                "state": {"enum": [COMPLETE, PARTIAL, UNSUPPORTED, INSTRUMENTATION_ERROR]},
                "unavailable_fields": {"type": "object", "additionalProperties": {"type": "string"}},
                "timing_authority": {"type": "object", "additionalProperties": {"type": "string"}},
                "first_token_includes_reasoning": {"type": ["boolean", "null"]},
            },
        },
    },
}


class TelemetryStore:
    """The bounded store of recent request records, and the process-lifetime counters beside it.

    The store is bounded by BOTH a record count and a byte budget: a very long request cannot push the store over
    its memory ceiling.  It is intentionally NOT durable: nothing is written to disk here, and a restart empties it.
    The counters live here and never fall when a record is evicted - they are the process-lifetime totals.
    """

    def __init__(self, max_records=DEFAULT_RETENTION_RECORDS, max_bytes=DEFAULT_RETENTION_BYTES):
        self.max_records = max(1, int(max_records))
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
        }
        self.histograms = {}               # name -> {"sum": .., "n": ..}

    # ------------------------------------------------------------------ writing
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
        measurement is not counted as zero."""
        c = self.counters
        c["requests_total"] += 1
        state = data["lifecycle"]["state"]
        if state == "completed":
            c["requests_completed"] += 1
        elif state == "cancelled":
            c["requests_cancelled"] += 1
        elif state in ("failed", "rejected"):
            c["requests_failed"] += 1
        prompt, gen, cache = data["prompt"], data["generation"], data["cache"]
        for key, counter in (("submitted_tokens", "prompt_tokens_submitted"),
                             ("matched_prefix_tokens", "prompt_tokens_matched"),
                             ("reused_prefix_tokens", "prompt_tokens_reused"),
                             ("evaluated_tokens", "prompt_tokens_evaluated"),
                             ("replayed_tokens", "prompt_tokens_replayed"),
                             ("evaluation_work_tokens", "prompt_evaluation_work_tokens")):
            value = prompt.get(key)
            if isinstance(value, int):
                c[counter] += value
        for key, counter in (("generated_tokens", "generated_tokens"), ("emitted_tokens", "emitted_tokens"),
                             ("speculative_draft_tokens", "speculative_draft_tokens"),
                             ("speculative_accepted_tokens", "speculative_accepted_tokens")):
            value = gen.get(key)
            if isinstance(value, int):
                c[counter] += value
        if cache.get("restore_attempted") is True:
            c["cache_restore_attempts"] += 1
            if cache.get("restore_succeeded") is False:
                c["cache_restore_failures"] += 1
        if isinstance(cache.get("evictions"), int):
            c["cache_evictions"] = max(c["cache_evictions"], cache["evictions"])
        if data["measurement_quality"]["state"] == INSTRUMENTATION_ERROR:
            c["instrumentation_errors"] += 1
        self._observe_locked(data)

    def _observe_locked(self, data):
        """The duration histograms: what the Prometheus exporter reads.  An unavailable duration is NOT observed -
        it would be a zero, and a zero is a measured zero."""
        timing = data["timing_ms"]
        for name, metric in (("queue", "queue_duration"), ("cache_lookup", "cache_lookup_duration"),
                             ("cache_restore", "cache_restore_duration"), ("prefill_wall", "prefill_duration"),
                             ("decode_wall", "decode_duration"), ("total", "request_duration"),
                             ("http_first_token", "time_to_first_token")):
            value = timing.get(name)
            if isinstance(value, (int, float)):
                hist = self.histograms.setdefault(metric, {"sum": 0.0, "n": 0})
                hist["sum"] += float(value)
                hist["n"] += 1

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
            after = decode_cursor(cursor)
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
                "next_cursor": encode_cursor(last) if last is not None and len(out) == limit else None}

    def summary(self) -> dict:
        """The process-lifetime totals and what the store holds.  The totals never fall when a record is evicted."""
        with self.lock:
            return {
                "counters": dict(self.counters),
                "histograms": {k: {"sum": v["sum"], "count": v["n"]} for k, v in self.histograms.items()},
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


# ------------------------------------------------------------------------------------------------ the schema check
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


# ------------------------------------------------------------------------------------------------ the JSONL evidence
class EvidenceLog:
    """The optional terminal-record log: one metadata-only JSON object per accepted request, one per line.

    It is written by a BACKGROUND thread: the token path never touches the disk, and a slow disk cannot slow a
    request down.  The queue is bounded - when it is full the record is DROPPED and counted, never written
    synchronously as a fallback (that would put the disk back on the hot path).
    """

    def __init__(self, path, queue_size=1024):
        self.path = str(path)
        self.queue_size = max(1, int(queue_size))
        self.lock = threading.Lock()
        self.queue = []
        self.written = 0
        self.dropped = 0
        self.errors = 0
        self._stop = threading.Event()
        self._thread = None
        self._handle = None
        self._open()

    def _open(self):
        try:
            self._handle = open(self.path, "a", encoding="utf-8")
        except OSError:
            self._handle = None
            with self.lock:
                self.errors += 1
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="strata-telemetry-evidence")
        self._thread.start()

    def write(self, record: dict) -> bool:
        """Queue a terminal record.  True when it was queued, False when it was dropped."""
        if self._handle is None:
            return False
        try:
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            with self.lock:
                self.errors += 1
            return False
        with self.lock:
            if len(self.queue) >= self.queue_size:
                self.dropped += 1
                return False
            self.queue.append(line)
        return True

    def _loop(self):
        while not self._stop.is_set() or self.queue:
            with self.lock:
                pending, self.queue = self.queue, []
            for line in pending:
                try:
                    self._handle.write(line + "\n")
                    self._handle.flush()
                    with self.lock:
                        self.written += 1
                except OSError:
                    with self.lock:
                        self.errors += 1
            if not pending:
                self._stop.wait(0.2)

    def flush(self, timeout=2.0):
        """Wait for the queue to be written (the shutdown path)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                if not self.queue:
                    return True
            time.sleep(0.02)
        return False

    def close(self):
        """Stop the thread after the queue is written, and close the file."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._handle is not None:
            try:
                self._handle.close()
            except OSError:
                pass
            self._handle = None

    def counters(self) -> dict:
        with self.lock:
            return {"written": self.written, "dropped": self.dropped, "errors": self.errors,
                    "queue_size": self.queue_size, "path": self.path}


# ------------------------------------------------------------------------------------------------ the server's side
# The engine's own measurements arrive as the key=value pairs on the request's own DONE line (see
# include/strata/program/reqtelemetry.hpp for the writer and src/program/reqtelemetry_test.cpp for the format).
# These are the names the server reads.  A field the engine did not send is ABSENT here, and stays null in the
# record: the engine's silence is not a zero.
ENGINE_INT_KEYS = ("matched", "reused", "evaluated", "replayed", "work", "divergent", "slot",
                   "invalidations", "evictions")
ENGINE_TEXT_KEYS = ("cache_source", "cache_reason", "restore", "rid")

# The engine's cache source names (cache_diag::Source) mapped to the canonical vocabulary.
SOURCE_NAMES = {
    "none": SOURCE_NONE,
    "live": SOURCE_RESIDENT_SLOT,
    "active_checkpoint": SOURCE_CONVERSATION_CACHE,
    "parked_live": SOURCE_CONVERSATION_CACHE,
    "parked_checkpoint": SOURCE_RESTORED_CHECKPOINT,
    "slot": SOURCE_RESIDENT_SLOT,
}

# The engine's reason names (cache_diag::Reason) mapped to the canonical reason codes.  They are the engine's own
# words for why it did what it did, kept as they are: an operator who knows the engine's log reads them.
REASON_CODES = {
    "EXACT_MATCH": "exact_match",
    "TOKEN_MISMATCH": "token_mismatch",
    "IMAGE_MISMATCH": "image_mismatch",
    "STEERING_MISMATCH": "steering_mismatch",
    "ABSENT": "absent",
    "INELIGIBLE": "ineligible",
    "EVICTED": "evicted",
    "RETENTION_REMOVED": "retention_removed",
    "CACHE_DISABLED": "cache_disabled",
    "BUDGET_REFUSED": "budget_refused",
    "SUPERSEDED": "superseded",
    "BORROWED": "borrowed",
    "SLOT_SOURCE": "slot_source",
    "UNKNOWN": "unknown",
}


def apply_engine(record: RequestRecord, figures: dict | None):
    """The engine's own measurements for this request, into the record.

    `figures` is the `telemetry` part of the engine's DONE line: what the engine measured about the cache and about
    the work it did.  A field the engine did not send stays null - it is NOT a zero, and it is NOT guessed from the
    server's own timings.
    """
    if not figures:
        record.mark_unavailable("cache", "the engine reported no cache measurements for this request")
        record.mark_unavailable("prompt.matched_prefix_tokens", "the engine reported no cache measurements")
        return record
    record.engine_invocation_id = figures.get("rid") or record.engine_invocation_id

    matched = figures.get("matched")
    reused = figures.get("reused")
    evaluated = figures.get("evaluated")
    # The engine writes the divergent index as: a position (0 or more), -1 for "the sequences agree throughout"
    # and -2 for "not measured".  The record's field is null in both of those cases - there is no mismatch to
    # report - and the reason says which of the two it was.
    divergent = figures.get("divergent")
    if divergent is not None:
        if divergent >= 0:
            record.first_divergent_token_index = int(divergent)
        elif divergent == -1:
            record.mark_unavailable("prompt.first_divergent_token_index",
                                    "the sequences agree throughout: there is no mismatch")
        else:
            record.mark_unavailable("prompt.first_divergent_token_index",
                                    "the engine did not report a divergence index")
    record.set_native_cache(
        matched_prefix=matched, reused_prefix=reused, evaluated=evaluated,
        replayed=figures.get("replayed"), evaluation_work=figures.get("work"),
        source=SOURCE_NAMES.get(figures.get("cache_source", ""), SOURCE_UNKNOWN),
        reason_code=REASON_CODES.get(figures.get("cache_reason", ""), "unknown"),
        restore_attempted=(figures.get("restore") != "none") if "restore" in figures else None,
        restore_succeeded=(figures.get("restore") == "succeeded") if "restore" in figures else None,
        restore_ms=figures.get("restore_ms"),
        invalidations=figures.get("invalidations"), evictions=figures.get("evictions"))
    # the engine's own durations: the lookup and the restoration it measured
    if figures.get("lookup_ms") is not None:
        record.set_timing("cache_lookup", figures["lookup_ms"], "native_engine")
    if figures.get("restore_ms") is not None:
        record.set_timing("cache_restore", figures["restore_ms"], "native_engine")
    if "slot" in figures:
        slot = figures["slot"]
        # the engine writes a slot only when there is one; a stray negative is "no slot", not a slot
        record.slot_id = int(slot) if isinstance(slot, int) and slot >= 0 else None
    if matched is None:
        record.mark_unavailable("prompt.matched_prefix_tokens", "the engine did not report a prefix match")
    if reused is None:
        record.mark_unavailable("prompt.reused_prefix_tokens", "the engine did not report a reused prefix")
    if evaluated is None:
        record.mark_unavailable("prompt.evaluated_tokens", "the engine did not report the tokens it evaluated")
    return record


# ------------------------------------------------------------------------------------------------ the server's wiring
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
        self.store = TelemetryStore(max_records=max_records, max_bytes=max_bytes)
        self.evidence = EvidenceLog(evidence_path) if evidence_path else None
        self.enabled = True
        self._records: dict[str, RequestRecord] = {}     # the requests in flight, by their id
        self.lock = threading.Lock()

    # ------------------------------------------------------------------ the request's life
    def begin(self, api=None, client_request_id=None, model_id=None, build_revision=None) -> RequestRecord:
        """A new request's record.  Its id is the server's own: unique per physical attempt, never derived from
        the client's id, so two requests that carry the same client id stay two records."""
        record = RequestRecord(new_request_id(), client_request_id=client_request_id,
                               server_instance_id=self.server_instance_id, model_id=model_id,
                               build_revision=build_revision, api=api)
        if not self.enabled:
            return record                     # the telemetry is off: the record is made and thrown away
        with self.lock:
            self._records[record.request_id] = record
        return record

    def finish(self, record: RequestRecord, state=None, http_status=None, finish_reason=None, detail=None):
        """Close a request's record, put it in the store and write the evidence line.  At most once: a record that
        was already finished is not finished again."""
        if record is None:
            return None
        if not self.enabled:
            return None                         # the telemetry is off: nothing is kept and nothing is written
        with self.lock:
            if record.request_id not in self._records:
                return None                 # already finished: a terminal receipt is finalized AT MOST ONCE
            del self._records[record.request_id]
        record.seal(state=state, http_status=http_status, finish_reason=finish_reason, detail=detail)
        data = self.store.add(record)
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
