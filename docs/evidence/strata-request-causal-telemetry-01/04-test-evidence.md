# 04 - The test evidence (W7)

Every command below was run on the host described in `00-entry-state.md`. The exit codes are the real ones.

## What was executed

| # | Command | Exit | Result |
|---|---|---|---|
| 1 | `g++ -std=c++20 -Iinclude -o /tmp/rtcache/reqtelemetry_test src/program/reqtelemetry_test.cpp && /tmp/rtcache/reqtelemetry_test` | 0 | `reqtelemetry_test: all checks passed` |
| 2 | `g++ -std=c++20 -Iinclude -o /tmp/rtcache/reqtelemetry_roundtrip src/program/reqtelemetry_roundtrip.cpp` | 0 | the engine's writer builds |
| 3 | `/tmp/stratavenv/bin/python tools/test_reqtelemetry_roundtrip.py -v` | 0 | `Ran 6 tests ... OK` |
| 4 | `/tmp/stratavenv/bin/python tools/test_reqtelemetry_schema.py` | 0 | `test_reqtelemetry_schema: all checks passed` |
| 5 | `/tmp/stratavenv/bin/python -m unittest serve.test_reqtelemetry -v` | 0 | `Ran 49 tests ... OK` |
| 6 | `/tmp/stratavenv/bin/python -m unittest serve.test_prometheus serve.test_reqtelemetry` | 0 | `Ran 55 tests ... OK` |
| 7 | `/tmp/stratavenv/bin/python -m unittest discover -s serve -p 'test_*.py'` | 0 | `Ran 1052 tests in 350.210s ... OK (skipped=23)` |
| 8 | the same at the ENTRY commit, in a temporary worktree (`git worktree add --detach /tmp/baseline 5b0e549b`) | 0 | `Ran 1005 tests in 340.202s ... OK (skipped=23)` |

The 23 skips are the repository's own (the GPU, the network and the platform tests). The suite passed **before**
this ACT's changes too, at the same count of skips.

### A test-isolation note

`serve/test_responses.py`'s `test_server_close_ends_the_sampler` counts the running hardware samplers. A sampler
stops a moment after its server does (it finishes its sample first), so a sampler from an earlier test can die
between that test's two counts and make the count come out one short.

This ACT's test file starts a server per test, so it widened that window. The fix is in the new file: its
tear-down waits for the sampler to be gone, exactly as `test_responses.py` does in its own teardown. The
repository's own test is **not** changed.

With the fix, `serve.test_reqtelemetry` + `serve.test_responses` + `serve.test_parallel` run together: **OK**.

The baseline was checked too, in a temporary worktree at the entry commit (`git worktree add --detach /tmp/baseline
5b0e549b`): **1005 tests, OK (skipped=23)**. So the race was latent before this ACT and this ACT's test file
widened the window; the fix closes it. The temporary worktree was removed afterwards; the repository's own
worktrees and the deployment repository were not touched.

## The qualification matrix

The honest column is the last one. **A native control that was not executed is NOT_EXECUTED, never PASS.**

| ID | Control | What proves it | Status |
|---|---|---|---|
| T01 | Cold cache | the witness in `05-cache-accounting-witnesses.json` ("cold cache"): `matched=0`, `reused=0`, `evaluated=100`, disposition `cold_miss`; the record's own rules | **PASS** (the record's rules and the witness) / **NOT_EXECUTED** (the native engine) |
| T02 | Identical prompt | the witness "identical prompt": `matched=99`, `reused=99`, `evaluated=1` - the final token is evaluated again | **PASS** (the rules) / **NOT_EXECUTED** (the engine) |
| T03 | Appended suffix | the witness "appended suffix": `matched=80`, `reused=80`, `evaluated=20` | **PASS** (the rules) / **NOT_EXECUTED** (the engine) |
| T04 | Changed suffix | the witness "changed suffix": `matched=80`, `reused=0`, `evaluated=100` | **PASS** (the rules) / **NOT_EXECUTED** (the engine) |
| T05 | Changed early prefix | the same rule, with a smaller `matched` | **PASS** (the rules) / **NOT_EXECUTED** (the engine) |
| T06 | State unavailable despite a token match | the witness "state unavailable despite a token match": `matched=90`, `reused=0` → disposition `match_without_usable_state`. **The native condition needs the real engine** (a candidate whose tokens match but whose steering mode differs) | **PASS** (the rules) / **NOT_EXECUTED** (the native condition) |
| T07 | Checkpoint restoration | the witness "a failed restoration" (`restore=failed` → never a successful reuse) and "a re-read state (replay)" (`replayed=100`) | **PASS** (the rules) / **NOT_EXECUTED** (the native restore) |
| T08 | Cancellation while queued | `serve/test_reqtelemetry.py`'s `test_a_cancelled_request_is_not_a_successful_one`: the state is `cancelled` and the quality is `partial` | **PASS** (the server's lifecycle) |
| T09 | Cancellation during prefill | the same rule: the partial accounting keeps the work that was done | **PASS** (the rules) / **NOT_EXECUTED** (the native cancel) |
| T10 | Cancellation during decode | the same rule | **PASS** (the rules) / **NOT_EXECUTED** (the native cancel) |
| T11 | Output exhaustion | the record keeps the requested and the effective budgets apart (`generation.requested_max_output_tokens` and `generation.effective_max_output_tokens`) | **PASS** (the contract) / **NOT_EXECUTED** (the native finish reason) |
| T12 | Duplicate client request ids | `test_two_requests_with_the_same_client_id_are_two_records`: two records, two distinct server ids | **PASS** |
| T13 | Concurrent requests | the id is a **thread-local on the engine** (`_req_local`), so parallel batch slots each carry their own; the store's key is the server's id | **PASS** (the design and the store's thread safety) / **NOT_EXECUTED** (with real parallel slots) |
| T14 | Engine restart / failure | the engine's instance id is `pid` + generation, so it changes on a restart; a request whose engine died keeps what it has and says `failed` | **PASS** (the design) / **NOT_EXECUTED** (a real engine death) |
| T15 | Bounded retention | `test_the_counters_do_not_fall_when_a_record_is_evicted`, `test_the_byte_ceiling_is_enforced`, `test_the_page_size_is_capped`, `test_the_pagination_is_stable_under_new_records` | **PASS** |
| T16 | Prometheus scraping | `06-http-contract-evidence.json`: the exposition is valid, the existing families are there, the telemetry's families are there | **PASS** |
| T17 | Authentication | `test_a_shared_listener_without_a_key_refuses_the_request_metadata` (403), `test_a_shared_listener_with_a_key_needs_it` (401 then 200), `test_the_loopback_listener_keeps_the_server_own_trust` (200) | **PASS** |
| T18 | Privacy | `test_the_evidence_carries_no_content` (the record's keys are exactly the schema's), `test_the_telemetry_carries_no_content_at_all`, and the check in `06-http-contract-evidence.json` | **PASS** |
| T19 | Telemetry disabled | `STRATA_TELEMETRY=0` turns the whole thing off. The engine's own writer program gates its DONE line the way the engine does, and `tools/test_reqtelemetry_roundtrip.py`'s `test_with_the_switch_off_the_done_line_carries_no_telemetry` drives it: no telemetry key is on the line and the server's reader finds no telemetry. The server's side is checked too (`Disabled`: nothing is kept, the status says so). | **PASS** (the switch, against the engine's own writer) / **NOT_EXECUTED** (a real engine's DONE line) |
| T20 | Streaming parity | the streaming path is unchanged: the telemetry only reads the DONE line and writes a record; the response body is untouched | **PASS** (the existing streaming tests pass) |
| T21 | Missing native telemetry | `test_a_missing_figure_stays_null`, `test_no_figures_at_all_is_an_explicit_state`: the fields are null and the quality says why | **PASS** |
| T22 | UI contract | the page (`serve/web/telemetry.html`, `serve/web/telemetry.js`) shows the units, the filters and the inspector; the record's fields are the ones it renders | **PASS** (the page and the record agree; the page is NOT rendered in a browser here) |
| T23 | Concurrent scraping | the API reads the store under its lock and never touches the engine; the page's refresh is bounded and never overlaps | **PASS** (the design) / **NOT_EXECUTED** (with a real engine under load) |

## The non-vacuity witnesses

Each of these is a check that **fails** when the defect it guards against is present. They are in
`serve/test_reqtelemetry.py` and `src/program/reqtelemetry_test.cpp`.

| The regression | The witness that fails without it |
|---|---|
| the matched prefix substituted for the actual reuse | `test_a_broken_identity_is_reported_and_not_repaired` (a reused prefix longer than the matched one is reported, not fixed) and `test_matched_may_exceed_reused` (the match may exceed the reuse; the two are not the same number) |
| the request identity dropped at the native boundary | `tools/test_reqtelemetry_roundtrip.py`'s `test_the_field_names_are_the_same_on_both_sides` (the server reads `rid`, so the engine must write it) and `test_the_client_id_the_server_sends_is_one_the_engine_accepts` |
| a restore failure reported as a successful reuse | `test_a_failed_restore_is_not_a_successful_reuse` (the disposition is `match_without_usable_state` and `restore_succeeded` is false) |
| an unavailable measurement turned into a zero | `test_an_unmeasured_field_is_null_and_never_zero` and `test_a_measured_zero_and_an_unavailable_field_are_different` |
| a cancellation finalized as a successful completion | `test_a_cancelled_request_is_not_a_successful_one` (the state is `cancelled`, the quality is `partial`) |
| duplicate physical attempts collapsed into one record | `test_two_requests_with_the_same_client_id_are_two_records` and `test_a_record_is_finished_at_most_once` |

**The mutations were not left in the code.** The witnesses are permanent checks on the real behaviour; no
temporary reversal was committed.

## What was NOT executed, and why

| Not executed | Why | What would execute it |
|---|---|---|
| the native cache controls (T01-T07, T13, T14, T19's byte-identical line) | no CUDA toolkit and no GPU on this host | a Linux/CUDA machine with the engine built (see `10-build-matrix.md`) |
| the performance parity (W8) | no GPU here | the same, with the two arms measured |
| the Pascal (SM61) and Blackwell (SM120) builds | no CUDA toolkit here | the same |
| the browser rendering of the telemetry page | no browser here | a manual look, or a headless browser |
