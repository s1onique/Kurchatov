# 04a - The 21 conflict regions in `terminal/serve/server.py`

The serving layer is the one file where the two sides both changed the same code. The
regions are listed in the order they appear in the file. "ours" is upstream's side of
the 3-way apply, "theirs" is the Kurchatov side.

| # | What upstream changed | What the local changed | Resolution | Preserved behavior | Verification |
|---|---|---|---|---|---|
| 1 | nothing (the `engines` section header) | the telemetry key tables (`REQTELEMETRY_INT_KEYS`, `..._FLOAT_KEYS`, `..._TEXT_KEYS`) and `parse_error_figures()` | the local's block kept | the server reads the engine's `DONE`/`ERR` telemetry keys; the failed request's partial evidence is correlated to it | `test_telemetry_amendment03.py` |
| 2 | the cache log's `CLEARED`, `SKIP` and `REASONS` regexes (the refused-park reasons) | the `DIAG` regex and the reader's `READ_MAX`/`DIAG_KEEP` bounds, plus the docstring's sentences | **both**: the local's sentences inside the docstring, upstream's regexes, then the local's `DIAG` regex and bounds | the cache diagnostics' events are read; the refused parks are counted by reason | `tools/test_cache_diag_log.py` (9 passed) |
| 3 | the `self.state` dict gained the refused-park counters | the reader's own state (`diag`, `diag_counts`, `diag_lost`, `diag_truncated`, `diag_bytes_lost`) | upstream's dict line, then the local's state lines | the reader's own counters survive; the refused-park counters are upstream's | `tools/test_cache_diag_log.py` |
| 4 | the `SKIP` handling (`self._refused(...)`) | the passed-over diagnostic events counted as lost | both | a refused park is counted by reason; a passed-over window is counted as lost | `tools/test_cache_diag_log.py` |
| 5 | nothing | the 46-line block (the telemetry's own machinery: the store, the seal, the `_finish_telemetry`) | the local's block kept | the whole telemetry machinery | `test_reqtelemetry.py` (52 passed) |
| 6 | `StrataEngine.sampling_keys(sampling, *, hy4=False)` (the hy4-aware sampler) | `request_key`, `set_request_id`, `request_id`, `error_figures` (the invocation identity) | **both**: upstream's `sampling_keys` **restored** (it had been dropped), then the local's four methods. The local's duplicate `sampling_keys` was dropped. | upstream's hy4-aware sampling keys; the local's per-thread request id | the upstream `SilentEngine`/`LostStep` tests (18 passed) |
| 7 | the `BDONE` handling (the admission token's clock, `read=`, `drafts=`) | the `native_segment_only` marker (a slot's leg is not the whole invocation) | **merged into one body**: upstream's arithmetic **and** the local's marker | a slot's segment is not published as the request's; the admission's clock is not double-counted | `test_telemetry_amendment02.py` |
| 8 | the hold/lp key block | the `request_key` call | upstream's block kept, the local's call appended | upstream's hold and logprob handling | the upstream suite (512 passed) |
| 9 | the hy4-aware key expression | the `request_key` call | merged into one expression: upstream's `hy4` form **plus** `self.request_key(self.request_id())` | the invocation id travels with the request | the upstream suite |
| 10 | `_raise_if_fatal_gpu()` and `_swallow_trailing_done()` (the fatal-GPU handling) | the `ERR` line's telemetry capture (`local.error_figures = parse_error_figures(line)`) | **both** | a fatal GPU error is still an engine death; the failed request's partial evidence is still correlated | `test_telemetry_amendment03.py` |
| 11 | `arena_env(quiet_crash_env(...))` and the `elif` chain for the GPU selection | `env["STRATA_TELEMETRY"] = ...` | upstream's env line, then the local's `STRATA_TELEMETRY` switch, then upstream's `elif` chain (the context after the region) | the engine is asked for its telemetry; the GPU selection is upstream's | `test_telemetry_amendment03.py` |
| 12 | `ContextOverflow` (the typed refusal) and the "max_tokens shortened" notice | the effective budget measurement (`tele.set_generation(effective_max=max_new)`) | **both**: upstream's refusal, then the local's measurement | a request over the context is refused with upstream's typed error; the record still carries the effective budget | the upstream suite |
| 13 | `timed_out = False` | `segment_invocations = []` (the invocation id each segment belongs to) | **both** | the timeout flag; the per-segment invocation ids | `test_telemetry_amendment03.py` |
| 14 | `first_engine_token_s` | `first_token_s` and `dispatch_ordinal` | **both** | upstream's terminal-row bookkeeping; the local's client-visible first-token time and the dispatch ordinal | `test_telemetry_amendment03.py` |
| 15 | the queue wait's deadline logic (`QueueCancelled`, `QueueWaitExpired`) | the local's `break`-based wait, the queue-wait measurement and the "cancelled while queued" outcome | upstream's deadline logic, wrapped so the local's queue-wait measurement and the cancelled outcome still ride on it | a request that gives its place up while queued still gets exactly one receipt | `test_telemetry_amendment02.py::HttpWitnesses::test_a_queued_request_that_the_client_abandons_still_gets_one_receipt` |
| 16 | the hold-aware `pass_sampling` and the `gen = ...` call | the invocation identity block (`new_invocation_id`, `begin_invocation`, the prompt domain, `set_request_id`) and the local's own `gen = ...` call | upstream's `pass_sampling` **and** the local's identity block; the local's duplicate `gen` call dropped (upstream's already makes it, with `pass_sampling`) | the hold budget is honoured; every dispatch owns its own measurements | `test_telemetry_amendment03.py` |
| 17 | the `first_engine_token_s` bookkeeping in the terminal rows | `first_token_s` | **both** | upstream's row bookkeeping; the local's first-token time | `test_telemetry_amendment03.py` |
| 18 | `seen = 0 if admission_rejected else ...` | the local's `seen` and the `_finish_telemetry` call | upstream's `seen` line, then the local's `_finish_telemetry` call (the local's duplicate `seen` dropped) | an admission-rejected request counts no prompt tokens; the record is still finished | `test_telemetry_amendment03.py` |
| 19 | nothing | the 119-line telemetry HTTP surface (`/v1/telemetry/*`, the fail-closed rule, the evidence writer's routes) | the local's block kept | the whole telemetry API | `test_reqtelemetry.py` (52 passed) |
| 20 | `_authorized_telemetry()` (the telemetry key) | `_telemetry_allowed()` (the fail-closed rule) | **both**: two methods | both the telemetry key and the fail-closed rule apply | `test_reqtelemetry.py::Access` (3 passed) |
| 21 | `svc.server_ip = machine_ip()` | `svc.bind_host = host` | **both**: two assignments | the About page's IP; the fail-closed rule's knowledge of the listener | `test_reqtelemetry.py::Access` |

## The three fixes that the upstream suite forced after the merge

The merge resolved every conflict, but the upstream suite then found **four** real
integration defects. They were fixed (see `07-integration-verification.md`):

1. the merged `server.py` re-defined `request_timings`, `request_stats`, `carry_leg` and
   `add_carry`, shadowing upstream's newer versions in `server_parts/core.py`;
2. upstream's `StrataEngine.sampling_keys` had been dropped by region 6;
3. upstream's `StrataEngine._raise_if_fatal_gpu` had been dropped by region 6;
4. the `@staticmethod` decorator on the local's `request_key` had been dropped.

Each was found by the upstream suite, not by inspection, and each is recorded in the
evidence with the test that found it.
