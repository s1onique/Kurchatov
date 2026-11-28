# 05 - The cross-surface conservation (W4)

ACT: **ACT-KURCHATOV-UPSTREAM-SYNC-01**, execution segment `QUALIFICATION-HANDOFF`
Candidate revision: `859d62c4a7f6bf3b1942ff1c6e61e4405f91623a`
The Kurchatov entry head (the local side of the merge): `7ad7c531dc8f7d00bd483d9baa1270a58bf2ba06`

W4 asks for two things: the **capability-preservation authority** corrected in a successor evidence
receipt, and the **actual HTTP Prometheus exposition** verified against a populated telemetry store. Both
are recorded here, and the third requirement - **retaining both the upstream compatibility and the
canonical process-scoped metrics** - is verified by the exposition itself.

## 1. The correction of the capability-preservation authority

The merge's own exit report recorded the Prometheus exporter's resolution like this
(`docs/evidence/kurchatov-upstream-sync-01/09-exit-report.md`):

> **the Prometheus exporter** - upstream's version was adopted (it already carried the canonical telemetry
> families), after establishing that equivalence;

and, in the merge commit's message:

> Resolved by adopting upstream's implementation, after establishing the equivalence: the Prometheus
> exporter's canonical telemetry families (upstream already carries them)

**That statement is not accurate, and this section corrects it.** The file that the merge left in the tree
is **not** upstream's file: it is Kurchatov's own exporter, carried over by a **byte-identical rename**.

```text
$ git show 7ad7c531d:serve/prometheus.py | sha256sum
c42684d73d0882e6026d801195a2cb31e0fe56ea643e83de879be186b41a13ee  -
$ git show 74e89653e:terminal/serve/prometheus.py | sha256sum
c42684d73d0882e6026d801195a2cb31e0fe56ea643e83de879be186b41a13ee  -
$ git show 42e489d14:terminal/serve/prometheus.py | sha256sum
e9d58c5af5c97d8841a769bc3f77c4f9ba6a13e0e3ba9b777d389bee3f738b03  -
```

Git itself says the same:

```text
$ git diff 7ad7c531d 74e89653e -- serve/prometheus.py terminal/serve/prometheus.py
diff --git a/serve/prometheus.py b/terminal/serve/prometheus.py
similarity index 100%
rename from serve/prometheus.py
rename to terminal/serve/prometheus.py
```

### 1.1 What is actually true

The **precise** statement is this, and it is the authority this ACT proceeds on:

* upstream's exporter is **160 lines** long; Kurchatov's is **291**;
* the first **160 lines are byte-identical** - upstream's file is a **prefix** of Kurchatov's;
* Kurchatov's **131 extra lines** are the canonical telemetry block, appended **additively**.

So the truth is *not* "upstream's implementation was adopted" and *not* "Kurchatov's exporter won". The
truth is: **upstream's exporter was adopted as the base, and Kurchatov's canonical telemetry families were
appended to it, additively.**

The merge's statement was wrong about the *mechanism* (the file was not replaced by upstream's; it was
carried over and extended), and the merge's own evidence for it - the file's difference against upstream -
was read as a replacement when it was an extension.

### 1.2 The correction's authority, and what it rests on

The corrected authority rests on **three** byte-level facts, each reproducible from the repository alone:

| Fact | How it was established |
| --- | --- |
| the merged file is byte-identical to Kurchatov's pre-merge file | the sha256 comparison above |
| upstream's file is a byte-identical **prefix** of the merged file | `diff` of the two against each other shows no difference in the first 160 lines |
| the difference is **additive** | the 131 added lines only **add** families; they rename, remove and redefine nothing |

The third fact is the one that matters for the capability, and it is checked in section 2.

## 2. The capability that is actually preserved: both surfaces, in one scrape

The merged exporter's own contract says the telemetry families are **additive**
(`terminal/serve/prometheus.py:172`-`:190`):

> They are ADDITIVE: nothing here renames, removes or redefines an existing metric, and the JSON /metrics and
> the llama.cpp-compatible names keep their own meaning.

The verification in section 3 checks that claim against the **actual** exposition.

## 3. The actual HTTP exposition, against a populated telemetry store

The witness is `tools/verify_prometheus_exposition.py`, and its output is
`prometheus-exposition.txt` beside this file. It starts the **real** server (`serve.server.serve`), drives a
**real** request through it, and scrapes the **real** `/metrics` endpoint over HTTP with the Prometheus
`Accept` header. The store's own counters are read back afterwards, so the scrape is taken against a
**populated** store and not against an empty one.

The run:

```text
$ /tmp/stratavenv/bin/python tools/verify_prometheus_exposition.py
metrics_keys=build,conversation_cache,engine,hardware,hardware_static,history,live,requests,requests_kept,telemetry,time,totals
upstream_compatible_families=10 present
canonical_families=13 present
canonical_families_are_process_scoped=true
upstream_families_keep_model_label=86
unmeasured_durations_publish_no_sample=true
exposition_well_formed=true
duration_buckets=19 latency_buckets=22
[strata] done: 21 tokens in 0 s (no speed) (stop, cancel=False)
request_usage={"completion_tokens": 21, "prompt_tokens": 246, ...}
populated_summary={"cache_evictions": 0, ..., "native_invocations": 1, ...}
http_exposition_bytes=18633 content_type=text/plain; version=0.0.4; charset=utf-8
http_upstream_families=20
http_canonical_families=31
PROMETHEUS_EXPOSITION_OK
```

### 3.1 What each check establishes

| Check | What it establishes |
| --- | --- |
| `upstream_compatible_families=10 present` | the upstream-compatible families (`vllm:num_requests_running`, `vllm:prompt_tokens_total`, `vllm:spec_decode_num_draft_tokens_total`, ...) are all there, by name |
| `canonical_families=13 present` | the canonical telemetry families (`strata_requests_total`, `strata_prompt_matched_tokens_total`, `strata_cache_restore_attempts_total`, `strata_telemetry_dropped_records_total`, ...) are all there, by name |
| `canonical_families_are_process_scoped=true` | **no** canonical family carries a `model_name` label: a process-lifetime total does not belong to the model that happens to be selected when the scrape happens (`terminal/serve/prometheus.py:196`-`:199`) |
| `upstream_families_keep_model_label=86` | the upstream-compatible families **keep** theirs: the compatibility surface is unchanged, so a dashboard written for a vLLM server reads this server unchanged |
| `unmeasured_durations_publish_no_sample=true` | a duration the server did **not** measure contributes **no** sample: there is no family of zeros (`terminal/serve/prometheus.py:236`-`:238`, "nothing was measured: no family, not a family of zeros") |
| `exposition_well_formed=true` | every family carries a `# HELP` and a `# TYPE` line |
| `http_exposition_bytes=18633`, `content_type=text/plain; version=0.0.4; charset=utf-8` | the exposition is the real HTTP answer, with the real content type |
| `http_upstream_families=20`, `http_canonical_families=31` | **both** surfaces are in the *same* scrape: the compatibility surface and the canonical surface, side by side |

### 3.2 The store was really populated

The witness asserts it, and the output shows it: `native_invocations: 1` after the request, and
`requests_total` at least 1 (`the store was not populated` is the assertion's own message). The scrape is
therefore taken against a store that holds a record, not against an empty one.

## 4. The selected suites are not the complete upstream qualification

**This section distinguishes the two, because the ACT asks for it.**

| What | Which suite | What it establishes | What it does NOT establish |
| --- | --- | --- | --- |
| the exporter's contract | `tools/verify_prometheus_exposition.py` (this ACT's witness) | the actual HTTP exposition carries both surfaces, that the canonical families are process-scoped, that an unmeasured duration publishes no sample | nothing about the upstream serving layer's other behaviour |
| the exporter's unit contract | `terminal/serve/test_prometheus.py` | the exporter's own rules (the buckets are cumulative, the label escaping, the JSON/Prometheus agreement) | nothing about a live engine |
| the upstream serving layer | upstream's own suite (the merge's baseline: 1 failed, 512 passed, the one failure being upstream's own Windows-only assertion) | the upstream serving layer behaves as it does at the pinned upstream head | nothing about the native engine, and nothing about this ACT's envelope |
| the native engine | the native build and the native ctest targets (section 03 of this evidence) | the engine compiles for the card's architecture and its own native tests pass | nothing about a request served by a real model |
| **the complete upstream qualification** | **not performed** | - | the complete upstream qualification of the merged tree on the target hardware is a **separate** exercise; this ACT claims a **selected** set of suites and says which |

The sentence this ACT makes is therefore: **the selected suites above passed, and they are not the complete
upstream qualification.** The exit report repeats it.

## 5. The cross-surface conservation of the telemetry itself

The conservation is not only of the exporter. Every telemetry module and every cache-diagnostics file is
**byte-identical** to the Kurchatov entry head's version - only the *location* changed (`serve/` ->
`terminal/serve/`, `include/` -> `engine/include/`, `src/` -> `engine/src/`):

```text
IDENTICAL  terminal/serve/reqtelemetry/accounting.py
IDENTICAL  terminal/serve/reqtelemetry/correlation.py
IDENTICAL  terminal/serve/reqtelemetry/store.py
IDENTICAL  terminal/serve/reqtelemetry/record.py
IDENTICAL  terminal/serve/reqtelemetry/evidence.py
IDENTICAL  terminal/serve/reqtelemetry/metrics.py
IDENTICAL  terminal/serve/reqtelemetry/schema.py
IDENTICAL  terminal/serve/reqtelemetry/vocabulary.py
IDENTICAL  terminal/serve/reqtelemetry/invocation.py
IDENTICAL  terminal/serve/reqtelemetry/server.py
IDENTICAL  engine/include/strata/program/reqtelemetry.hpp
IDENTICAL  engine/include/strata/program/cache_diag.hpp
IDENTICAL  engine/src/program/reqtelemetry_test.cpp
IDENTICAL  engine/src/program/reqtelemetry_roundtrip.cpp
IDENTICAL  engine/src/program/cache_diag_test.cpp
IDENTICAL  engine/src/program/cache_diag_engine_test.cpp
IDENTICAL  engine/src/program/cache_diag_regress_test.cpp
IDENTICAL  terminal/serve/web/telemetry.js
IDENTICAL  terminal/serve/web/telemetry_accounting.js
```

The one file that is **not** byte-identical on purpose is `terminal/serve/prometheus.py` - it carries
Kurchatov's canonical telemetry block, and the merge's authority about it was wrong (section 1). The
corrected authority is: **upstream's exporter was adopted as the base, and Kurchatov's canonical families
were appended to it, additively.** The appended block renames, removes and redefines nothing, and the
exposition in section 3 is the proof.
