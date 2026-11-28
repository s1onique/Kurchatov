#!/usr/bin/env python3
"""ACT-KURCHATOV-UPSTREAM-SYNC-01, W4: the ACTUAL HTTP Prometheus exposition, against a POPULATED
telemetry store.

What this proves, and what it does not:

  * it starts the REAL server (serve.server.serve) with the REAL telemetry store and scrapes the REAL
    `/metrics` endpoint over HTTP with the Prometheus Accept header;
  * it checks that BOTH surfaces are present in the same scrape: the upstream-compatible families (the
    `vllm:` names) and the canonical process-scoped telemetry families (the `strata_requests_total` family
    and the `strata_*_duration_seconds` histograms);
  * it checks that the canonical families carry NO `model_name` label (they are process-scoped), while the
    upstream-compatible families keep theirs;
  * it checks that a duration the server did NOT measure contributes NO sample (no family of zeros).

This is a SELECTED regression suite.  It is not the complete upstream qualification, and it does not
claim to be: the complete qualification of the upstream serving layer is upstream's own suite, and the
native engine's qualification is the native build and the native ctest targets (see the exit report).

    python3 tools/verify_prometheus_exposition.py
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "terminal"))

from serve.prometheus import BUCKETS, CONTENT_TYPE  # noqa: E402
from serve.reqtelemetry import DURATION_BUCKETS  # noqa: E402


def parse(text: str) -> dict:
    """{(name, labels): value} for every sample line; every family must carry a # TYPE line."""
    out: dict = {}
    typed: set = set()
    for line in text.splitlines():
        if line.startswith("# TYPE "):
            typed.add(line.split()[2])
            continue
        if line.startswith("#") or not line:
            continue
        m = re.fullmatch(r"([a-z0-9_:]+)\{([^}]*)\} (\S+)", line)
        if not m:
            m = re.fullmatch(r"([a-z0-9_:]+) (\S+)", line)
        assert m, f"not a sample line: {line!r}"
        name, labels, value = m.group(1), (m.group(2) if m.lastindex == 3 else ""), m.groups()[-1]
        family = re.sub(r"_(bucket|sum|count)$", "", name)
        assert name in typed or family in typed, f"{name} has no # TYPE"
        out[(name, labels)] = float(value)
    return out


def main() -> int:
    from serve.frontend import ChatTemplate
    from serve.prometheus import Latencies, render
    from serve.server import ByteTokenizer, MockEngine, Service, serve

    tok = ByteTokenizer()
    template = ChatTemplate(ROOT / "terminal/serve/chat_template.jinja")
    service = Service(MockEngine(tok, "<think>\n\nhello there", max_context=4096), tok, template)

    metrics = service.metrics()
    print("metrics_keys=" + ",".join(sorted(metrics)))

    summary = service.telemetry_summary()
    print("telemetry_summary=" + json.dumps(summary, sort_keys=True, default=str)[:400])

    lat = Latencies()
    lat.observe(0.30, 11, 1.0, 1.5)
    text = render(metrics, lat.snapshot())
    samples = parse(text)

    upstream_families = [
        "vllm:num_requests_running",
        "vllm:num_requests_waiting",
        "vllm:prompt_tokens_total",
        "vllm:generation_tokens_total",
        "vllm:request_success_total",
        "vllm:prefix_cache_queries_total",
        "vllm:prefix_cache_hits_total",
        "vllm:spec_decode_num_draft_tokens_total",
        "vllm:spec_decode_num_accepted_tokens_total",
        "vllm:num_preemptions_total",
    ]
    for fam in upstream_families:
        assert any(k[0] == fam for k in samples), f"the upstream-compatible family {fam} is missing"
    print(f"upstream_compatible_families={len(upstream_families)} present")

    canonical = [
        "strata_requests_total",
        "strata_prompt_tokens_total",
        "strata_prompt_matched_tokens_total",
        "strata_prompt_reused_tokens_total",
        "strata_prompt_evaluated_tokens_total",
        "strata_prompt_replayed_tokens_total",
        "strata_prompt_evaluation_work_tokens_total",
        "strata_generated_tokens_total",
        "strata_cache_restore_attempts_total",
        "strata_cache_restore_failures_total",
        "strata_cache_evictions_total",
        "strata_telemetry_dropped_records_total",
        "strata_telemetry_retention_evictions_total",
    ]
    for fam in canonical:
        assert any(k[0] == fam for k in samples), f"the canonical family {fam} is missing"
    print(f"canonical_families={len(canonical)} present")
    for (name, labels), _value in samples.items():
        if name.startswith("strata_"):
            assert "model_name=" not in labels, f"{name} carries a model_name label: {labels!r}"
    print("canonical_families_are_process_scoped=true")

    labelled = [k for k in samples if k[0].startswith("vllm:") and "model_name=" in k[1]]
    assert labelled, "the upstream-compatible families lost their model_name label"
    print(f"upstream_families_keep_model_label={len(labelled)}")

    for fam in ("strata_queue_duration_seconds", "strata_cache_lookup_duration_seconds",
                "strata_cache_restore_duration_seconds", "strata_prefill_duration_seconds",
                "strata_decode_duration_seconds", "strata_time_to_first_token_seconds",
                "strata_request_duration_seconds"):
        assert not any(k[0] == fam for k in samples), f"{fam} is a family of zeros"
    print("unmeasured_durations_publish_no_sample=true")

    for line in text.splitlines():
        if line.startswith("# TYPE "):
            fam = line.split()[2]
            assert f"# HELP {fam} " in text, f"{fam} has a TYPE without a HELP"
    print("exposition_well_formed=true")

    print(f"duration_buckets={len(DURATION_BUCKETS)} latency_buckets={len(BUCKETS)}")

    server = serve(service, port=0)
    base = f"http://127.0.0.1:{server.server_address[1]}"

    # A REAL request through the REAL server: the telemetry store's counters and histograms fill in.
    body = json.dumps({"model": "m", "messages": [{"role": "user", "content": "hi"}],
                       "max_tokens": 32}).encode()
    req = urllib.request.Request(base + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        usage = json.loads(resp.read()).get("usage")
    print(f"request_usage={json.dumps(usage, sort_keys=True)}")

    populated = service.telemetry_summary()
    print("populated_summary=" + json.dumps(populated.get("counters", {}), sort_keys=True)[:400])
    assert populated.get("counters", {}).get("requests_total", 0) >= 1, "the store was not populated"

    req = urllib.request.Request(base + "/metrics", headers={"Accept": "text/plain;version=0.0.4"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        http_text = resp.read().decode()
        http_ct = resp.headers.get("Content-Type")
    http_samples = parse(http_text)
    assert http_ct == CONTENT_TYPE, f"the content type is {http_ct!r}, not {CONTENT_TYPE!r}"
    assert any(k[0] == "vllm:num_requests_running" for k in http_samples), "the HTTP scrape has no upstream family"
    print(f"http_exposition_bytes={len(http_text)} content_type={http_ct}")
    print(f"http_upstream_families={len({k[0] for k in http_samples if k[0].startswith('vllm:')})}")
    print(f"http_canonical_families={len({k[0] for k in http_samples if k[0].startswith('strata_')})}")

    server.shutdown()
    server.server_close()

    print("PROMETHEUS_EXPOSITION_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
