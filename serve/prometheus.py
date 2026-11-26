"""GET /metrics in the Prometheus text format, with vLLM's metric names, so the dashboards and alerts written for a
vLLM server read a PolyStrata server unchanged.  Everything comes from the server's own record (Service.metrics(), the
same dict the JSON /metrics returns) plus three latency histograms observed when a request finishes.

What vLLM has no name for is the JSON's own facts under `strata:`, named after the JSON's keys (live.tok_s ->
strata:live_tok_s, totals.decode_ms -> strata:totals_decode_seconds_total, hardware.gpu_util -> strata:gpu_util), so
the two formats say the same thing and a panel can be moved from the Monitor tab to Grafana by its key."""
import threading

# vLLM's buckets for the request latencies (seconds)
BUCKETS = (0.001, 0.005, 0.01, 0.02, 0.04, 0.06, 0.08, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0, 20.0, 40.0,
           80.0, 160.0, 640.0, 2560.0)
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def wants_prometheus(accept: str, query: str) -> bool:
    """Prometheus asks with Accept: text/plain or application/openmetrics-text; a person can add ?format=prometheus.
    Anything else (the Monitor tab, curl without a header) keeps the JSON."""
    return "format=prometheus" in (query or "") or "openmetrics" in (accept or "") or "text/plain" in (accept or "")


class Histogram:
    def __init__(self):
        self.counts = [0] * len(BUCKETS)
        self.sum = 0.0
        self.n = 0

    def observe(self, v: float, times: int = 1):
        if v is None or times <= 0:
            return
        for i, b in enumerate(BUCKETS):
            if v <= b:
                self.counts[i] += times
        self.sum += v * times
        self.n += times


class Latencies:
    """Time to first token, the time between tokens and the whole request, per finished request."""

    def __init__(self):
        self.lock = threading.Lock()
        self.ttft, self.itl, self.e2e = Histogram(), Histogram(), Histogram()

    def observe(self, ttft_s, output_tokens, decode_s, total_s):
        with self.lock:
            self.ttft.observe(ttft_s)
            if output_tokens and output_tokens > 1 and decode_s:
                # the mean gap, once per gap: the engine reports the decode time, not each token's
                self.itl.observe(decode_s / (output_tokens - 1), output_tokens - 1)
            self.e2e.observe(total_s)

    def snapshot(self):
        with self.lock:
            return {k: (list(h.counts), h.sum, h.n) for k, h in
                    (("ttft", self.ttft), ("itl", self.itl), ("e2e", self.e2e))}


def _num(v, default=0):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else default


def render(m: dict, lat: dict) -> str:
    """The text for one scrape.  `m` is Service.metrics(), `lat` Latencies.snapshot()."""
    model = str((m.get("engine") or {}).get("model") or "strata").replace("\\", "\\\\").replace('"', '\\"')
    lab = f'model_name="{model}"'
    live, totals = m.get("live") or {}, m.get("totals") or {}
    out = []

    def metric(name, kind, help_, value):
        out.append(f"# HELP {name} {help_}\n# TYPE {name} {kind}\n{name}{{{lab}}} {value}")

    busy = live.get("state") in ("reading", "generating")
    ctx = _num((m.get("engine") or {}).get("max_context"), 0)
    used = _num(live.get("prompt_tokens")) + _num(live.get("generated")) if busy else 0
    # "parallel": live.running / live.waiting count the requests together (waiting: for a slot or the control lines)
    metric("vllm:num_requests_running", "gauge", "Requests reading their prompt or generating.",
           _num(live.get("running"), int(busy)))
    metric("vllm:num_requests_waiting", "gauge", "Requests waiting for their turn.",
           _num(live.get("queued")) + _num(live.get("waiting")))
    metric("vllm:kv_cache_usage_perc", "gauge", "The running request's share of the context (1 = full).",
           round(min(1.0, used / ctx), 4) if ctx else 0)
    metric("vllm:prompt_tokens_total", "counter", "Prompt tokens of the finished requests.",
           _num(totals.get("prompt_tokens")))
    metric("vllm:generation_tokens_total", "counter", "Generated tokens.", _num(totals.get("output_tokens")))
    metric("vllm:request_success_total", "counter", "Finished requests.", _num(totals.get("requests")))
    metric("vllm:prefix_cache_queries_total", "counter", "Prompt tokens looked up in the prompt cache.",
           _num(totals.get("prompt_tokens")))
    metric("vllm:prefix_cache_hits_total", "counter", "Prompt tokens the prompt cache already held.",
           _num(totals.get("reused")))
    metric("vllm:spec_decode_num_draft_tokens_total", "counter", "MTP draft tokens offered.",
           _num(totals.get("drafts_offered")))
    metric("vllm:spec_decode_num_accepted_tokens_total", "counter", "MTP draft tokens accepted.",
           _num(totals.get("drafts_accepted")))
    metric("vllm:num_preemptions_total", "counter", "Preempted requests (PolyStrata does not preempt).", 0)
    for name, key, help_ in (("vllm:time_to_first_token_seconds", "ttft", "Time to the first token."),
                             ("vllm:inter_token_latency_seconds", "itl", "Time between two tokens."),
                             ("vllm:e2e_request_latency_seconds", "e2e", "A request from start to end.")):
        counts, total, n = lat[key]
        out.append(f"# HELP {name} {help_}\n# TYPE {name} histogram")
        for b, c in zip(BUCKETS, counts):
            out.append(f'{name}_bucket{{{lab},le="{b}"}} {c}')
        out.append(f'{name}_bucket{{{lab},le="+Inf"}} {n}')
        out.append(f"{name}_sum{{{lab}}} {round(total, 6)}\n{name}_count{{{lab}}} {n}")
    strata(m, out, lab)
    return "\n".join(out) + "\n"


def strata(m: dict, out: list, lab: str):
    """The JSON's facts vLLM has no name for, under `strata:` and the JSON's key."""
    live, totals = m.get("live") or {}, m.get("totals") or {}
    hw, eng = m.get("hardware") or {}, m.get("engine") or {}
    reqs = m.get("requests") or []

    typed = set()

    def metric(name, kind, help_, value, labels=""):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return                                       # unknown here (no GPU telemetry, an older engine): no sample
        if name not in typed:                            # one HELP / TYPE per family, before its first sample
            typed.add(name)
            out.append(f"# HELP strata:{name} {help_}\n# TYPE strata:{name} {kind}")
        out.append(f"strata:{name}{{{lab}{labels}}} {value}")

    for state in ("unloaded", "idle", "reading", "generating"):
        metric("live_state", "gauge", "1 for what the engine is doing (live.state).", int(live.get("state") == state),
               f',state="{state}"')
    metric("live_tok_s", "gauge", "Decode rate over the last seconds (live.tok_s).", live.get("tok_s") or 0)
    metric("live_prefill_tok_s_mean", "gauge", "Prompt reading rate of the running request (live.prefill_tok_s_mean).",
           live.get("prefill_tok_s_mean") or 0)
    metric("live_prompt_read", "gauge", "Prompt tokens read so far by the running request (live.prompt_read).",
           live.get("prompt_read") or 0)
    for state in ("idle", "reading", "generating"):
        slots = live.get("slots")
        if isinstance(slots, list) and slots:
            metric("live_slots", "gauge", "The batch slots in each state (live.slots).",
                   sum(1 for x in slots if isinstance(x, dict) and x.get("state") == state), f',state="{state}"')
    metric("engine_max_context", "gauge", "The engine's context (engine.max_context).", eng.get("max_context"))
    metric("totals_prompt_seconds_total", "counter", "Time spent reading prompts (totals.prompt_ms).",
           round((totals.get("prompt_ms") or 0) / 1000, 3))
    metric("totals_decode_seconds_total", "counter", "Time spent generating (totals.decode_ms).",
           round((totals.get("decode_ms") or 0) / 1000, 3))
    last = reqs[0] if reqs else {}
    metric("last_hit_rate", "gauge", "The last request's expert cache hit rate (requests[0].hit_rate).",
           last.get("hit_rate"))
    metric("last_decode_tok_s", "gauge", "The last request's decode rate (requests[0].decode_tok_s).",
           last.get("decode_tok_s"))
    gpus = hw.get("gpus") or ([{"index": 0, "util": hw.get("gpu_util"), "mem_used": hw.get("gpu_mem_used"),
                                "mem_total": hw.get("gpu_mem_total"), "temp": hw.get("gpu_temp"),
                                "power": hw.get("gpu_power")}] if hw.get("gpu_util") is not None else [])
    for name, key, help_ in (("gpu_util", "util", "GPU busy, percent (hardware.gpu_util)."),
                             ("gpu_mem_used_bytes", "mem_used", "GPU memory in use (hardware.gpu_mem_used)."),
                             ("gpu_mem_total_bytes", "mem_total", "GPU memory (hardware.gpu_mem_total)."),
                             ("gpu_temp_celsius", "temp", "GPU temperature (hardware.gpu_temp)."),
                             ("gpu_power_watts", "power", "GPU power draw (hardware.gpu_power).")):
        for g in gpus:                                   # a family's samples together, one per card
            metric(name, "gauge", help_, g.get(key), f',gpu="{g.get("index")}"')
    metric("cpu", "gauge", "CPU busy, percent (hardware.cpu).", hw.get("cpu"))
    metric("ram_used_bytes", "gauge", "RAM in use (hardware.ram_used).", hw.get("ram_used"))
    metric("ram_total_bytes", "gauge", "RAM (hardware.ram_total).", hw.get("ram_total"))
    telemetry(m.get("telemetry") or {}, out, "")


# The buckets for the telemetry's durations (seconds).  ONE authority for the edges: the store counts the
# observations into them (serve/reqtelemetry.py) and this exporter prints the same edges, so a bucket line and the
# store's own accounting cannot drift apart.  They are the request-latency buckets extended for the long-context
# prefill: a prefill of a long prompt takes minutes, and a bucket set that ends at 20 s would put every long
# prefill in the same bucket and hide the difference between a 30 s and a 300 s prefill.
from serve.reqtelemetry import DURATION_BUCKETS as TELEMETRY_BUCKETS


def telemetry(tel: dict, out: list, lab: str):
    """ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01: the canonical telemetry metrics.

    They are ADDITIVE: nothing here renames, removes or redefines an existing metric, and the JSON /metrics and the
    llama.cpp-compatible names keep their own meaning.  These are the engine-authoritative request accounting:

      * the token counters count what the ENGINE measured (the tokens it reused, the tokens it evaluated, the
        evaluation work).  A request whose accounting was incomplete (a cancel) contributes what it really did;
      * an unavailable measurement is NOT observed as a zero: a duration the server did not measure contributes no
        sample at all, so a histogram's count says how many observations there really were;
      * the labels are bounded enumerations (an outcome, a cache disposition, a source, a reason code).  There is
        no request id, no session, no engine instance, no prompt, no user and no model identity in a label.
    """
    counters = tel.get("counters") or {}
    histograms = tel.get("histograms") or {}
    retention = tel.get("retention") or {}
    typed = set()

    def metric(name, kind, help_, value, labels=""):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return                                       # not measured here: no sample (never a zero)
        if name not in typed:
            typed.add(name)
            out.append(f"# HELP {name} {help_}\n# TYPE {name} {kind}")
        # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-02 (A8): the canonical telemetry metrics are
        # PROCESS-SCOPED: they carry no model_name label.  A process-lifetime total does not belong to the model
        # that happens to be selected when the scrape happens - otherwise the work of the model that ran before a
        # switch is published under the new model's name.
        label_set = f"{lab}{labels}"
        out.append(f"{name}{{{label_set}}} {value}" if label_set else f"{name} {value}")

    def counter(name, help_, key):
        metric(name, "counter", help_, counters.get(key))

    counter("strata_requests_total", "Requests the telemetry recorded (all outcomes).", "requests_total")
    counter("strata_prompt_tokens_total", "Prompt tokens submitted to the engine.", "prompt_tokens_submitted")
    counter("strata_prompt_matched_tokens_total", "Prompt tokens that matched a cached sequence's prefix.",
            "prompt_tokens_matched")
    counter("strata_prompt_reused_tokens_total", "Prompt tokens whose execution state was really reused.",
            "prompt_tokens_reused")
    counter("strata_prompt_evaluated_tokens_total", "Prompt positions the engine evaluated.", "prompt_tokens_evaluated")
    counter("strata_prompt_replayed_tokens_total", "Evaluated positions that were previously processed material.",
            "prompt_tokens_replayed")
    counter("strata_prompt_evaluation_work_tokens_total", "Prompt-token evaluations executed (repeats count again).",
            "prompt_evaluation_work_tokens")
    counter("strata_generated_tokens_total", "Tokens the engine generated.", "generated_tokens")
    counter("strata_cache_restore_attempts_total", "State restorations the engine tried.", "cache_restore_attempts")
    counter("strata_cache_restore_failures_total", "State restorations that failed.", "cache_restore_failures")
    counter("strata_cache_evictions_total", "Conversation cache evictions the engine saw.", "cache_evictions")
    counter("strata_telemetry_dropped_records_total", "Telemetry records the store could not keep.",
            "dropped_records")
    counter("strata_telemetry_retention_evictions_total", "Records evicted because the store was full.",
            "retention_evictions")

    for name, key, help_ in (("strata_queue_duration_seconds", "queue_duration",
                              "How long a request waited for its turn."),
                             ("strata_cache_lookup_duration_seconds", "cache_lookup_duration",
                              "How long the engine looked for a reusable state."),
                             ("strata_cache_restore_duration_seconds", "cache_restore_duration",
                              "How long the engine restored a state."),
                             ("strata_prefill_duration_seconds", "prefill_duration",
                              "How long the engine read the prompt."),
                             ("strata_decode_duration_seconds", "decode_duration", "How long the engine decoded."),
                             ("strata_time_to_first_token_seconds", "time_to_first_token",
                              "How long from the request's start to the first token the client saw."),
                             ("strata_request_duration_seconds", "request_duration", "How long the request took.")):
        hist = histograms.get(key) or {}
        n = hist.get("count")
        if not isinstance(n, int) or n <= 0:
            continue                                       # nothing was measured: no family, not a family of zeros
        total = hist.get("sum") or 0.0
        out.append(f"# HELP {name} {help_}\n# TYPE {name} histogram")
        # The buckets are CUMULATIVE and REAL: the store counted every observation into the edges it is at or below
        # (serve/reqtelemetry.py, in seconds - the one place the milliseconds are converted).  A bucket says how many
        # observations were at or below that edge, never the total count: an observation of 2 s is not in the 30 s
        # bucket's place, and the sum is the seconds the observations really took.
        buckets = hist.get("buckets") or {}
        label_set = f"{lab}," if lab else ""
        for b in TELEMETRY_BUCKETS:
            count = buckets.get(str(b))
            if not isinstance(count, int):
                count = 0
            out.append(f'{name}_bucket{{{label_set}le="{b}"}} {count}')
        out.append(f'{name}_bucket{{{label_set}le="+Inf"}} {n}')
        if lab:
            out.append(f"{name}_sum{{{lab}}} {round(total, 6)}\n{name}_count{{{lab}}} {n}")
        else:
            out.append(f"{name}_sum {round(total, 6)}\n{name}_count {n}")

    metric("strata_requests_in_flight", "gauge", "Requests the telemetry has open.", tel.get("inflight"))
    metric("strata_requests_queued", "gauge", "Requests waiting for the engine.", tel.get("queued"))
    metric("strata_telemetry_retained_records", "gauge", "Records the store keeps.", retention.get("records"))
    metric("strata_telemetry_retained_bytes", "gauge", "Bytes the store's records take.", retention.get("bytes"))
    metric("strata_telemetry_available", "gauge", "1 when the telemetry is on.", 1 if tel.get("enabled") else 0)
    # ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-01 (G6): the cache-reuse ratio is published with the
    # population it covers: the numerator and the denominator come from the SAME eligible requests (the ones whose
    # reuse accounting is complete), and the coverage says how much of the traffic that population is.
    reuse = tel.get("cache_reuse") or {}
    metric("strata_cache_reuse_ratio", "gauge",
           "Reused prompt tokens over submitted prompt tokens, over the requests whose accounting is complete.",
           reuse.get("ratio"))
    metric("strata_telemetry_accounting_coverage", "gauge",
           "The share of the requests whose cache-reuse accounting is complete.", reuse.get("coverage"))
    evidence = tel.get("evidence") or {}
    metric("strata_telemetry_evidence_dropped_total", "counter",
           "Terminal records the evidence writer could not queue.", evidence.get("dropped"))
    metric("strata_telemetry_evidence_failures_total", "counter",
           "Terminal records the evidence writer could not write.", evidence.get("errors"))

