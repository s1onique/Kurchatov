"""serve/reqtelemetry/metrics.py - the duration histograms the Prometheus exporter reads (G1, G9).

ONE authority for the durations: the record keeps its timings in MILLISECONDS (the section is named timing_ms), the
store converts them to SECONDS once - here - and everything downstream of this line is seconds.  The buckets are
cumulative and real: a bucket says how many observations were at or below that edge, never the total count.
"""
from __future__ import annotations

import math

# The duration buckets (SECONDS).  One authority for the edges: the store counts the observations into them and the
# Prometheus exporter prints the same numbers, so a bucket line and the store's own accounting cannot disagree.  They
# reach past a minute because a long-context prefill takes minutes, and a bucket set that ended at 20 s would put
# every long prefill in the same bucket.
DURATION_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0,
                    600.0, 1200.0, 3600.0)

# The durations the record carries, and the histogram each one belongs to.
DURATION_METRICS = (("queue", "queue_duration"),
                    ("cache_lookup", "cache_lookup_duration"),
                    ("cache_restore", "cache_restore_duration"),
                    ("prefill_wall", "prefill_duration"),
                    ("decode_wall", "decode_duration"),
                    ("total", "request_duration"),
                    ("http_first_token", "time_to_first_token"))


def observe_duration(histograms: dict, metric: str, milliseconds) -> bool:
    """Observe ONE duration (milliseconds) in a histogram, in seconds.

    An unavailable duration is NOT observed: it would be a zero, and a zero is a measured zero.  A negative or a
    non-finite measurement is not a duration at all and is not observed either.  True when the observation counted.
    """
    if not isinstance(milliseconds, (int, float)) or isinstance(milliseconds, bool):
        return False
    seconds = float(milliseconds) / 1000.0
    if not math.isfinite(seconds) or seconds < 0:
        return False
    hist = histograms.setdefault(metric, {"sum": 0.0, "n": 0, "buckets": [0] * len(DURATION_BUCKETS)})
    hist["sum"] += seconds
    hist["n"] += 1
    for i, edge in enumerate(DURATION_BUCKETS):
        if seconds <= edge:
            hist["buckets"][i] += 1
    return True
