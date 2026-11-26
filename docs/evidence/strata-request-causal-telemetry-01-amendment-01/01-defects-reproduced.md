# 01 - The defects, reproduced against ENTRY_HEAD

Every defect of the amendment was reproduced against `c45ec82846b2671673ff712009c8a85e1f034e2e` before it was
corrected. The reproductions are executable: they are the witnesses of `serve/test_telemetry_integrity.py` and
`tools/test_telemetry_mutations.py` run against the entry commit (a separate worktree of it, `/tmp/kurchatov-base`).

| ID | The defect | How it showed itself at ENTRY_HEAD |
|---|---|---|
| G1a | every histogram bucket carried the total observation count | the exporter wrote `n` into every `le=` line: a 120 s observation also appeared in the 1 s bucket |
| G1b | the milliseconds were exported as seconds | the store summed the milliseconds and the exporter printed the number as seconds: 2 000 ms was published as 2 000 s |
| G2 | the `rid` was sent to the engine but the returned value was never checked | `apply_engine` took the `rid` for the invocation id and applied the figures whatever they were: a receipt of another request was attached to this one, and its numbers reached the aggregates |
| G3a | a `null` reuse was read as a zero | `derive_disposition` used truthiness: `matched=90, reused=null` gave `match_without_usable_state` |
| G3b | a broken conservation identity and an unevaluated one looked the same | there was no third state: a cancelled request's accounting was reported like a complete one's |
| G3c | the non-prefix reuse was never decided | the field stayed `null`, so the sum identity could never be evaluated for any request |
| G4 | distinct quantities were published from one variable | the rendered prompt tokens were the submitted ones (`set_prompt_tokens(rendered=submitted, ...)`), and the generated tokens were the emitted ones (`set_generation(generated=generated, emitted=generated)`) |
| G4b | the requested and the effective output budget were not measured | both stayed `null`: nothing wrote them |
| G4c | some durations were wall-clock differences | the total was `time.time() - started` across two clock domains, and the first token came from the shared `self.status` |
| G5 | the engine's completion finalized the record | `_finish_telemetry` sealed the record and put it in the store; a request that was refused, cancelled while queued or disconnected never got a receipt, and the in-flight registry kept it forever |
| G6 | the cache-reuse ratio mixed two populations | the numerator and the denominator were summed independently, and a request with a submitted prompt but no measured reuse counted in the denominator only |
| G6b | the engine's eviction counter was a maximum, not a counter | it kept the highest value ever seen, so a restarted engine's counter never went down and never went up either |
| G6c | the evidence writer's drops were not published | the summary did not carry the writer's counters |
| G7 | a cursor named only a sequence number | a cursor of another server, or an old one, was accepted and silently pointed somewhere else |
| G9 | one module held everything | `serve/reqtelemetry.py` was 1 044 lines with the record, the schema, the store, the evidence, the correlation and the wiring in it |

## The reproductions that were run

```bash
# the entry commit, in its own worktree
git worktree add /tmp/kurchatov-base c45ec82846b2671673ff712009c8a85e1f034e2e
cd /tmp/kurchatov-base
PYTHONPATH=/tmp/pystubs /usr/bin/python3 -m unittest serve.test_reqtelemetry   # 49 tests, OK
```

The witnesses of the amendment (`serve/test_telemetry_integrity.py`, `tools/test_telemetry_mutations.py`) fail
against that tree and pass against the corrected tree - that is the non-vacuity proof (10 - the non-vacuity).
