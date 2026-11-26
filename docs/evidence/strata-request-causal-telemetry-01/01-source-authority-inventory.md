# 01 - The source authority inventory (W0)

What each measurement already had an owner for, at ENTRY_HEAD `5b0e549b762d9eac8b360dc34365e7ba8557efb0`. Every
row names the file, the symbol and the line, so the map can be checked against the source.

The rule the inventory follows: **the native engine owns the cache state and the model execution; the HTTP
server owns the HTTP lifecycle.** Nothing is reconstructed on the wrong side.

## 1. The native request lifecycle

| Measurement | Source | Authority | Unit | Scope | Lifecycle | Availability | Action |
|---|---|---|---|---|---|---|---|
| The prompt tokens admitted | `src/program/generate.cpp:11867`, `const int64_t n = (int64_t) ids.size();` | native engine | tokens | request | parsed with the prompt; final at the DONE line | always | REUSE |
| The reusable prefix (the state really mounted) | `src/program/generate.cpp:12064`, `int64_t resume` | native engine | tokens | request | decided at ~12087-12466, final at ~12571 | always | REUSE |
| The prefix that was matched (the tokens only) | `src/program/generate.cpp:8812`, `CacheDiagCollector::best_lcp` | native engine | tokens | request | collected while the candidates are examined | only with the diagnostics on | EXTEND |
| The first divergent token | `src/program/generate.cpp:8813`, `best_mismatch` | native engine | position | request | with the candidates | only with the diagnostics on | EXTEND |
| Where the prefix came from | `src/program/generate.cpp:12496-12511`, `cdiag.selected` | native engine | word | request | at the decision boundary | only with the diagnostics on | EXTEND |
| Why the engine did that | `src/program/generate.cpp:12518-12525`, `cdiag.reason` | native engine | word | request | at the decision boundary | only with the diagnostics on | EXTEND |
| The state restoration's outcome | `src/program/generate.cpp:12620-12645` (`checkpoint_restore`) and `:12477` (the parked restore) | native engine | - / ms | request | at the restore | always (the restore itself) | EXTEND |
| The prompt tokens read | `src/program/generate.cpp:14895`, `read_n` | native engine | tokens | request | at the DONE line | always | REUSE |
| The prefill and the decode time | `src/program/generate.cpp:14911`, `prompt_ms` / `decode_ms` | native engine | ms | request | at the DONE line | always | REUSE |
| The generated tokens and the drafts | `src/program/generate.cpp:14911`, `produced_n`, `draft_accepted`, `draft_offered` | native engine | tokens | request | at the DONE line | always | REUSE |
| The finish reason | `src/program/generate.cpp:14911`, `finish` | native engine | word | request | at the DONE line | always | REUSE |
| The slot | `src/program/generate.cpp:10876`, `admit_slot` | native engine | number | request | at the admission | with `--batch` | EXTEND |
| The cache's evictions | `src/program/generate.cpp:8875`, `cache.evictions()` | native engine | count | process | with the cache | always | EXTEND |

## 2. The HTTP request lifecycle

| Measurement | Source | Authority | Unit | Scope | Availability | Action |
|---|---|---|---|---|---|---|
| The queue wait | `serve/server.py:4269`, `waiting = time.perf_counter()` and the FIFO acquire | HTTP server | ms | request | always | REUSE |
| The template render and the tokenization | `serve/server.py:4648`, `encode_prompt` -> `render_prompt` | HTTP server | tokens | request | always | REUSE |
| The model load | `serve/server.py:4284`, `ensure_loaded()` | HTTP server | ms | request | when a load happened | REUSE |
| The first token the client saw | `serve/server.py:5225`, `trace["first_token_s"]` and `self.status["first_token"]` | HTTP server | ms | request | always | REUSE |
| The total time | `serve/server.py:5426`, the request's `started` | HTTP server | ms | request | always | REUSE |
| The HTTP status | `serve/server.py:6218`, `_json` | HTTP server | code | request | always | REUSE |

## 3. The engine-to-server protocol

The engine writes lines on stdout; the server reads them in `_pump` (`serve/server.py:1141`).

| Line | Meaning | Where it is parsed |
|---|---|---|
| `DONE <generated> <prompt> <prompt_ms> <decode_ms> <finish> <drafts_accepted> <drafts_offered> <reused> <hits> <lookups> <ram> <file> <file_mb> <prompt_read> <offloaded> [key=value ...]` | the request's own figures | `serve/server.py:1283`, `_parse_done` |
| `RESUME <n>` | the reused prefix | `serve/server.py:2204` |
| `PP <read> <total> <ms> [tok/s]` | the prompt progress | `serve/server.py:1468` |
| `BT <slot> <id>` / `BDONE <slot> <produced> <finish> <ms>` | a batch slot's lines | `serve/server.py:1158` (routed to the slot's queue) |
| `ERR <message>` | the engine refused or failed | `serve/server.py:1491` |

**The DONE line already has a `key=value` suffix** (`chunk=`, `experts_streamed=`). That is the extension point
this ACT uses: a new field is an extension of an existing protocol, not a new one, and an older server ignores the
keys it does not know.

## 4. The correlation: what was there and what was missing

**What was there.** The DONE line belongs to the request that read it. The server reads it while it holds that
request's control lines (`self.ctl`), and a batch slot's lines go to that slot's own queue (`_pump`, the
`"BT "`/`"BDONE "` routing). So the *figures* were already per-request by construction.

**What was missing.** There was no **identity** on the wire: nothing said *which* request a line belonged to, so
the record could not name the request it described, and a restart could not be told apart from a continuation.
The `STRATA_CACHE_DIAG` events carried a `request_seq` (a process-local counter) and went to **stderr** as a log
that the server scraped (`ConvCacheLog`): a log-scraping channel, correlated by position.

**What this ACT adds.** The request's own id travels with the request:

```
server -> engine:  GEN <max_new> ... rid=<hex> <ids>
engine -> server:  DONE ... rid=<hex> matched=... reused=... ...
```

The `rid` is the server's id for that physical attempt. It is a label: it is never a key, never a credential,
and the engine only echoes back what it was given (checked to be hex, bounded to 64 characters).

## 5. The existing cache diagnostics (reused, not duplicated)

`include/strata/program/cache_diag.hpp` already computes what the telemetry needs:

| What | Where |
|---|---|
| the ACTUAL common prefix of a candidate with the prompt | `cache_diag::common_prefix` (line 194) |
| why a candidate is not usable | `cache_diag::analyse` (line 245) |
| the source and the reason vocabularies | `cache_diag::Source` (line 62), `cache_diag::Reason` (line 84) |
| the collector that fills them per request | `generate.cpp:8796`, `CacheDiagCollector` |

The collector was gated on `STRATA_CACHE_DIAG=1` and wrote to **stderr**. This ACT turns the **same** collector on
for the telemetry (`generate.cpp:8885` in this ACT: `cdiag.on = cdiag_on || tele_on;`) and carries the result on the DONE
line. There is **no second, parallel account** of the cache decision: one analysis, two destinations.

## 6. The action per measurement

| Action | Measurements |
|---|---|
| **REUSE** | the prompt tokens admitted, the reusable prefix, the prompt tokens read, the prefill and decode time, the generated tokens, the drafts, the finish reason, the queue wait, the render and the tokenization, the model load, the first token, the total time, the HTTP status |
| **EXTEND** | the matched prefix, the first divergent token, the cache source, the cache reason, the restoration's outcome and time, the slot, the cache's evictions, the lookup time, the request's identity on the wire |
| **IMPLEMENT** | the canonical record, the store, the HTTP API, the web view, the Prometheus extension, the structured evidence |
| **UNSUPPORTED** | the recurrent-state and attention-state attribution **separately**: Strata's checkpoints restore the whole session state together (`src/core/conversation_state.cpp:187`, `conversation_checkpoint_restore` copies `ss.gdn_state` and the QSA states in one go), so the record reports ONE restoration, not two. The non-prefix reuse (`non_prefix_reused_tokens`): Strata's cache is a prefix cache, so there are no reused positions outside the contiguous prefix - the field is reported as a measured zero by the server's accounting, not as a number the engine invented. |

## 7. What was deliberately NOT touched

| Not touched | Why |
|---|---|
| the cache selection, the retention, the eviction policy | the telemetry **observes** the decision; it does not make it |
| the checkpoints and the conversation cache | same |
| the sampling, the quantization, the kernels | outside the ACT's scope |
| the `/metrics` JSON shape, the vLLM names, the llama.cpp names | the Prometheus work is **additive** |
| the API monitor (`/api-monitor`) | it captures content; the telemetry is metadata-only and independent of it |
