"""serve/reqtelemetry/vocabulary.py - the record's own words (ACT-...-AMENDMENT-01, G9).

The enumerations and the limits of the telemetry contract, in one place: the schema, the record, the store and the
exporter all speak these words, so they cannot drift apart.
"""
from __future__ import annotations

# ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-03 (G1): the record contract changed INCOMPATIBLY - the
# per-invocation receipts are a new section and the parent's native scalars are null when the request dispatched
# more than one native invocation - so the contract is versioned up.
SCHEMA_VERSION = "strata.request-telemetry/2"

# ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-03 (G1): the bounds of the per-invocation history.  They are
# a COUNT and a BYTE budget, and a receipt that does not fit is counted as a loss - never dropped silently.
MAX_INVOCATION_RECORDS = 8
MAX_INVOCATION_BYTES = 32 << 10            # 32 KiB of receipts per request

# ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-03 (G5): how many engine instances' eviction high-water
# marks the store keeps.  The retired instances' state is bounded: a long run does not grow it without limit.
MAX_ENGINE_INSTANCES = 64

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

# The duration buckets (SECONDS).  One authority for the edges: the store counts into them and the Prometheus
# exporter prints the same numbers, so a bucket line and the store's own accounting cannot disagree.  They reach
# past a minute because a long-context prefill takes minutes, and a bucket set that ended at 20 s would put every
# long prefill in the same bucket.
DURATION_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0,
                    600.0, 1200.0, 3600.0)

# The client's own request id: what may be in it.  It is a label for the operator, never a key and never a
# credential: it may not authenticate anything and it is never the internal primary key.
CLIENT_ID_MAX = 128
CLIENT_ID_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")

# How long a pagination cursor stays usable.  A cursor names a position in ONE server's store; after this long it
# is refused instead of silently pretending that the collection is exhausted (G7).
CURSOR_TTL_S = 3600.0
