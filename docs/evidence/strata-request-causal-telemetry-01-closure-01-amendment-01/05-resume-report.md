# ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 - RESUME-01

The continuation of the amendment. The previous execution segment was restricted by its runtime mutation
authority to the evidence writer and reported `PARTIAL_CORRECTION`. This segment had the full mutation authority
of the resume and closed the remaining gates A1, A2, A3, A4, A5a (HTTP), A5b, A5c, A6 and A7.

The historical evidence of the previous segment (01-source-only.diff, 02-corrections.md, 04-exit-report.md,
SHA256SUMS, final-head.txt) is UNCHANGED. This report and the two diffs beside it are the successor.

## The corrections

| Gate | The defect | The correction | The witness |
|---|---|---|---|
| A1 | the native dispatch population was counted from the receipts that were STORED, so a lost terminal receipt removed its whole invocation population | the population is counted at the terminal boundary, BEFORE the receipt is sealed (`ServerTelemetry.finish` -> `TelemetryStore.count_dispatch_population`); a failed seal, serialization or store lowers the coverage instead of shrinking the population; a running request is not in it yet; the physical request population of `cache_reuse.requests` is the number of requests that reached a terminal outcome | `serve/test_telemetry_amendment01.py::DispatchPopulation` |
| A2 | the request's own prompt coverage was the SUM of every invocation of the request's prompt domain, and an unnamed domain was admitted through a length comparison | the coverage is counted once (the ONE invocation that carried the request's own prompt domain); when several did, the request-level coverage is unavailable and the cumulative native work is counted instead (`requests_with_ambiguous_prompt_coverage`); the length fallback is gone | `serve/test_telemetry_amendment01.py::PromptDomainConservation` (five controls) |
| A3a | the duplicate comparison covered five prompt counters, and a foreign duplicate changed the accepted receipt's correlation | the COMPLETE normalized terminal evidence is compared BEFORE anything is applied; the snapshot is committed once (`InvocationReceipt.terminal_evidence`); a duplicate never updates a measurement and never changes the correlation | `serve/test_telemetry_amendment01.py::ImmutableTerminalEvidence` |
| A3b | the native outcome was taken from the request's HTTP outcome and from the position of the dispatch in a list | the native outcome is the dispatch's OWN (`native_terminal_state`); an earlier failed invocation stays failed, a completed one stays completed when the delivery fails, an unavailable one stays unknown | `serve/test_telemetry_amendment01.py::NativeOutcomeAuthority` (the production dispatch path) |
| A3c | the compatibility path built an authoritative receipt without a dispatch | the receipt is marked `synthetic`, published as `compatibility_receipt`, refused by the native admission and excluded from the dispatched population | `serve/test_telemetry_amendment01.py::ImmutableTerminalEvidence` |
| A4 | a forgotten engine identity looked like a new one and its whole counter was counted again | a bounded MEMBERSHIP filter (`_SeenEngines`) remembers that an identity was ever seen; a forgotten one is refused from the authoritative total and the attribution loss is published | `serve/test_telemetry_amendment01.py::EngineCounterDomain` |
| A5a (HTTP) | the telemetry's HTTP boundary could write a bare `NaN` | the boundary is strict: the answer is serialized with `allow_nan=False` and a non-finite value is refused with a proper JSON error | `serve/test_telemetry_amendment01.py::HttpSerialization` (the actual transport, a strict reader) |
| A5b | a discarded sole invocation left its mirrored measurements on the parent | the parent's mirrored native fields are cleared; the HTTP-owned fields stay | `serve/test_telemetry_amendment01.py::RetentionIntegrity` |
| A5c | the incompatible corrections were published under the v2 identity | the historical `strata.request-telemetry/2` contract is preserved (code, file and fixture) and the corrected one has its own identity: `strata.request-telemetry/3` | `tools/test_reqtelemetry_schema.py` |
| A6 | the invocation inspector's facts were built inside the page | they are built by a pure function (`serve/web/telemetry_accounting.js`), so the inspector and its witness cannot drift apart; the coverage line uses the corrected populations | `tools/test_telemetry_web_inspector.py` |

## The reversals (A7)

Every named reversal was implemented and executed. Each reverses ONE correction IN MEMORY and shows that the
witness that guards it fails.

| Reversal | Where |
|---|---|
| LOST_PARENT_RECEIPT_REMOVES_NATIVE_DISPATCH_POPULATION | `tools/test_telemetry_amendment01_mutations.py` |
| REPEATED_REQUEST_PROMPT_POSITIONS_ACCUMULATED | `tools/test_telemetry_amendment01_mutations.py` |
| UNKNOWN_PROMPT_DOMAIN_ADMITTED_AS_REQUEST | `tools/test_telemetry_amendment01_mutations.py` |
| PARTIAL_PAYLOAD_DUPLICATE_COMPARISON | `tools/test_telemetry_amendment01_mutations.py` |
| FOREIGN_DUPLICATE_MUTATES_ACCEPTED_RECEIPT | `tools/test_telemetry_amendment01_mutations.py` |
| NATIVE_OUTCOME_INFERRED_FROM_HTTP_OUTCOME | `tools/test_telemetry_amendment01_mutations.py` |
| FORGOTTEN_ENGINE_COUNTER_COUNTED_AGAIN | `tools/test_telemetry_amendment01_mutations.py` |
| NONFINITE_JSONL_ACCEPTED | `serve/test_telemetry_evidence_writer.py` (the accepted correction of the previous segment; its teeth check is "without `allow_nan=False` the writer accepts the record again") |
| DROPPED_INVOCATION_PARENT_MIRROR_SURVIVES | `tools/test_telemetry_amendment01_mutations.py` |
| INVOCATION_INSPECTOR_PROPERTY_MISSPELLED | `tools/test_telemetry_web_inspector.py` (the witness runs the same inspector with the property misspelled and shows that no invocation is rendered) |

## The exit contract

```yaml
ACT_ID: ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01
ORIGINAL_AMENDMENT_ENTRY_HEAD: a0daa4c710bf3502342dcc14ee72d595b4a062c6
RESUME_ENTRY_HEAD: 64eb7f6df538664c3d3d7d54baa9b3867101084e
TESTED_CODE_HEAD: 4b788abcb0694435c9ad3ddde99f3bf0716167de
FINAL_HEAD: (the evidence commit that carries this report)
CODE_TREE_BINDING: 4b788abcb0694435c9ad3ddde99f3bf0716167de

MUTATION_AUTHORITY: the runtime authorized the paths of the resume (serve/reqtelemetry/, serve/server.py,
  serve/web/, serve/test_*.py, serve/fixtures/, tools/, docs/); every change of this segment is inside them
PYTHON_EXECUTABLE: /tmp/stratavenv/bin/python
PYTHON_VERSION: 3.12.14
SERVER_IMPORT: OK (serve.server imports; jinja2, regex, jsonschema present)
DEPENDENCY_SOURCE: the qualified environment /tmp/stratavenv of the previous segment (no dependency was installed
  and no dependency declaration was changed)

A1: CLOSED - the native dispatch population is counted at the terminal boundary, independently of the receipt's
  storage; the control is 2 physical requests, 2 native dispatches, 1 retained receipt, 1 lost receipt ->
  requests 2, invocations 2, eligible_invocations 1, missing_invocations 1, request_coverage 0.5, coverage 0.5
A2: CLOSED - the request's own prompt coverage is counted once; five controls (the same prompt twice, the same
  prompt with different measurements, two prompts of equal length, an unknown domain, a continuation)
A3: CLOSED - the immutable terminal snapshot (A3a), the native outcome authority (A3b) and the compatibility
  isolation (A3c), with the production dispatch path for the multi-invocation and recovery controls
A4: CLOSED - the bounded membership filter; the accepted 74 -> 75 witness still holds
A5a_JSONL: CLOSED (the accepted correction of the previous segment, unchanged)
A5a_HTTP_PAYLOAD: CLOSED - the telemetry's HTTP boundary refuses a non-finite value
A5a_HTTP_TRANSPORT: CLOSED - the actual transport (status, summary, list, one record) with a strict reader
A5a_HTTP_BOUNDARY: CLOSED - the refusal is a proper JSON error; the inference is unchanged
A5b: CLOSED - a discarded sole invocation clears the parent's mirrored native fields
A5c: CLOSED - the historical v2 contract is preserved; the corrected contract is strata.request-telemetry/3
A6: CLOSED - the inspector's facts are a pure function; two asymmetrical invocation receipts are rendered, the
  missing measurements stay unavailable, and the coverage line names the corrected populations
A7: CLOSED - the ten named reversals were implemented and executed

LOST_PARENT_NATIVE_COVERAGE: PASS (the population stays 2, the coverage falls to 0.5)
REPEATED_PROMPT_COVERAGE: PASS (the request-level coverage is unavailable, the cumulative work is counted)
CONFLICTING_DUPLICATE_MUTATIONS: PASS (the accepted snapshot is kept, the conflict is reported)
FOREIGN_DUPLICATE_MUTATIONS: PASS (the correlation of the accepted receipt stays verified)
FORGOTTEN_ENGINE_COUNTER_DELTA: PASS (the delta is 0 or 1, never the whole counter)
STRICT_JSONL: PASS (the accepted writer correction)
STRICT_JSON_HTTP: PASS (the transport writes strict JSON)
WIRE_SCHEMA_VERSION: PASS (strata.request-telemetry/3, the historical v2 contract preserved)
INVOCATION_INSPECTOR_WITNESS: PASS (tools/test_telemetry_web_inspector.py, with the misspelling check)

REAL_DEPENDENCY_FULL_SUITE: PASS - /tmp/stratavenv/bin/python -m unittest discover -s serve -t . -v
  -> Ran 1234 tests, OK (skipped=20), 376 s
HOST_NATIVE_ROUNDTRIP: PASS - tools/test_reqtelemetry_roundtrip.py -> 6 tests OK
MUTATION_RESULTS: PASS - 37 tests OK (tools/test_telemetry_mutations.py 12, tools/test_telemetry_amendment03_
  mutations.py 8, tools/test_telemetry_closure01_mutations.py 9, tools/test_telemetry_amendment01_mutations.py 8)
SCHEMA_VALIDATION: PASS - tools/test_reqtelemetry_schema.py -> all checks passed
BROWSER_PRESENTATION: PASS - tools/test_telemetry_web_accounting.py (4 cases) and
  tools/test_telemetry_web_inspector.py, both with osascript (no node on this host)
ACTUAL_WRITER_TESTS: PASS - serve/test_telemetry_evidence_writer.py (the accepted correction)
CUDA_SM61_BUILD: NOT_APPLICABLE - no CUDA, HIP or SYCL source is touched by this segment
CUDA_SM120_BUILD: NOT_APPLICABLE - no CUDA, HIP or SYCL source is touched by this segment

PRODUCTION_STATE_CHANGED: NO - no deployment, no engine restart, no live inference; the running instance was
  not touched
UNRESOLVED_DEFECTS: none of A1-A7. Two notes for the reviewer:
  1. at RESUME_ENTRY_HEAD the inspector's property was already the correct one (`record.invocations`); the
     A6 witness and its misspelling check are in place and pass, so the named reversal is executed, but it did
     not reproduce a defect at the entry head;
  2. the A2 correction changes the request-level coverage semantics: a request whose prompt coverage cannot be
     measured exactly (several dispatches of its own prompt, or an unnamed prompt domain) is no longer counted
     as "with complete accounting". The predecessor's witnesses that relied on the length fallback were updated
     to name the prompt domain at the dispatch boundary, as the production path does.
MODULARITY_DEBT: serve/reqtelemetry/record.py and serve/reqtelemetry/store.py still carry several
  responsibilities each. The debt is TRACKED SEPARATELY: this correction did not split them, and no unrelated
  refactoring was done.
EVIDENCE_LOCATION: docs/evidence/strata-request-causal-telemetry-01-closure-01-amendment-01/
  05-resume-report.md (this report), 05-resume-source-only.diff (RESUME_ENTRY_HEAD..TESTED_CODE_HEAD),
  06-complete-amendment-range.diff (the complete amendment range, the evidence directories excluded)
FINAL_DISPOSITION: SOURCE_ACCEPTANCE_READY
```
