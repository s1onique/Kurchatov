# 11 - The exit report of ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-02

```yaml
ACT_ID: ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-02
ADDENDUM: FULL_DIFF_REVIEW_01
ENTRY_HEAD: 579f5cef1b5ead2c38079f9b7e5b867838bf703e
TESTED_CODE_HEAD: 10c094df1267a60121c826f72988346ee48c266f
FINAL_HEAD: 7fd2d359cab5ba2bb7e6cd5c02e82f4ddbdc74a3  (the evidence commit; the last commit only records this line)
CODE_TREE_BINDING: the acceptance suite ran against the working tree of d770e7d8284a6c42c6d4420fa1ddc5f546fff1e6; the evidence commits add
  only docs/evidence/... and change no production file (the diff of the evidence commits is the evidence itself)

G1_MEASUREMENT_ADMISSION: CORRECTED - a measurement enters an authoritative total only when it is valid, its
  accounting holds and its receipt is correlated; the invalid, unattributed and broken ones stay diagnostic
  receipts.  Six witnesses (serve/test_telemetry_amendment02.py::Admission).
G2_NATIVE_INVOCATION_IDENTITY: CORRECTED - a new hexadecimal invocation id per dispatch, bound before the
  dispatch and checked before ANY native number is applied; a foreign, stale, duplicate or missing id never
  enters the record's authoritative fields.  Six witnesses, including the recovery witness (A -> B, C).
G3_NATIVE_ACCOUNTING: CORRECTED IN SOURCE, NOT EXECUTED - the cumulative work is no longer aliased to the
  distinct count on the re-read path (it stays "not measured" there); the native diff is 01-native-production.diff.
  No CUDA toolchain on this host: NOT_EXECUTED.
G4_NATIVE_ERROR_EVIDENCE: CORRECTED IN SOURCE, NOT EXECUTED - the terminal ERR line carries the telemetry the
  engine did measure, and the server reads it (parse_error_figures).  NOT_EXECUTED (no CUDA build here).
G5_MONOTONICITY_AND_BOUNDS: CORRECTED - the engine's eviction counter is a high-water mark per instance
  (10, 8, 11 -> 10, 10, 11); the evidence writer's bound counts the record being written, its bytes are UTF-8
  bytes and its flush means "every accepted record reached a terminal outcome".
G6_CURSOR_CONTRACT: CORRECTED - a cursor without an owner, with a sequence below one, dated in the future,
  expired or pointing at an evicted page is refused; the HTTP endpoint answers 400.
G7_EXECUTABLE_WITNESSES: DONE - 37 new witnesses in the production paths (the store, the correlation, the
  writer, the HTTP handlers, the exporter) and 12 non-vacuity witnesses; among them the three controls the
  amendment names by name: a genuinely QUEUED request that the client abandons (a real socket), an actual
  TRANSPORT DISCONNECTION mid-stream, and the terminalization FAULT INJECTION through the HTTP path.  The whole
  suite ran with the repository's real dependencies.
G8_REVIEW_COMPLETENESS: DONE - 01-native-production.diff, 02-http-production.diff,
  03-telemetry-core-production.diff, 04-test-witnesses.diff, 05-evidence-summary.md and SHA256SUMS, all
  generated from the repository itself.

REAL_DEPENDENCY_FULL_SUITE: 1129 tests, OK (skipped=20), exit code 0 - /tmp/stratavenv has the repository's
  real jinja2, regex and jsonschema; no stand-in was used.
HOST_NATIVE_TESTS: NOT_EXECUTED - the native writer/reader roundtrip needs the engine binary, which needs a
  build; this host has no CUDA toolkit.  The telemetry's own host-compilable test (src/program/reqtelemetry_test.cpp)
  was NOT rebuilt either: the encoder was not changed.
CUDA_BUILD: NOT_EXECUTED - no CUDA toolkit on this host (SM61 and SM120).
LIVE_NATIVE_QUALIFICATION: NOT_EXECUTED - not authorized here; it is the next ACT's work.
PERFORMANCE_PARITY: NOT_EXECUTED - it needs the engine and a GPU.

PRODUCTION_STATE_CHANGED: false - nothing was deployed, no engine was restarted, the infrastructure repository
  and the running instance were not touched, and `.kurchatov-acts/` was not modified.
UNRESOLVED_DEFECTS: none in the source.  Three native items are source-corrected but NOT COMPILED and NOT
  EXECUTED here (the cumulative work on the re-read path, the telemetry on the terminal ERR line, and the
  batch slot's segment attribution), and the live cache controls and the performance parity remain the work of
  the separately authorized live-qualification ACT.
EVIDENCE_LOCATION: docs/evidence/strata-request-causal-telemetry-01-amendment-02/
FINAL_DISPOSITION: SOURCE_CORRECTED_NATIVE_BUILD_PENDING
```

## The addendum's own fields

```yaml
A1_QUEUE_DURATION: CORRECTED - the wait is measured where it happens and is never overwritten; a request that
  waited for its turn reports the wait.  The witness uses two real HTTP requests.
A2_INVOCATION_BINDING: CORRECTED - a new id per dispatch, the parent request id kept beside it, the ordinal
  separate, the engine instance captured with it, and the echoed id checked before any native number is applied.
A3_HTTP_EMISSION_AUTHORITY: CORRECTED - the first MEANINGFUL content is timed at the write boundary; the
  service's observation is published separately; the emitted-token count is null with a reason.
A4_LIFECYCLE_CONSERVATION: CORRECTED - the accepted count is taken at the admission, the terminal outcome
  before the seal, and the receipt's delivery is counted beside them; a seal that fails keeps the accounting.
A5_EVIDENCE_WRITER_INTEGRITY: CORRECTED - UTF-8 bytes, the bound counts the record being written, the flush
  is exact, the worker owns the handle, a refused write is a counted failure.
A6_PRODUCTION_PATH_NON_VACUITY: DONE - the seven named witnesses each reverse the PRODUCTION behavior and
  each makes the production-path witness fail.
A7_BROWSER_ACCOUNTING: CORRECTED - the bar's arithmetic is one pure function; four presentation cases are
  checked with the host's JavaScript engine.
A8_MODEL_SWITCH_ATTRIBUTION: CORRECTED - the canonical telemetry metrics are process-scoped (no model label).
A9_BATCH_AND_YIELD_AUTHORITY: CORRECTED IN SOURCE - a slot's BDONE marks the figures as ONE segment: they
  stay in the record as diagnostics and out of the authoritative totals.

ACTUAL_ACCEPTED_REQUESTS: the witness's own counts (the summary's counters: requests_accepted)
ACTUAL_TERMINAL_OUTCOMES: the same summary's counters (requests_terminal_completed / _cancelled / _failed /
  _rejected); the identity is checked at quiescence
LOST_TERMINAL_RECEIPTS: 0 in the witnesses (receipt_delivery_failures counts the ones that could not be
  delivered; the fault-injection witness shows the accounting still balances)
INFLIGHT_AT_QUIESCENCE: 0
OUTSTANDING_EVIDENCE_AT_SHUTDOWN: 0 (the writer's counters: outstanding_records, outstanding_bytes)
REAL_DEPENDENCY_FULL_SUITE: 1129 tests, OK (skipped=20), exit 0
```

## What a reviewer should read first

1. `defects-reproduced.md` - what each defect was, and the witness that guards it;
2. `corrections.md` - where each correction is;
3. `01-native-production.diff` - the whole native change (39 lines, two measurement sites);
4. `test-evidence.md` - the commands and the results.

## The honest limits

* The native corrections are **not compiled** here: this host has no CUDA toolkit and no GPU.  They are marked
  `NOT_EXECUTED` everywhere, and a macOS build that excludes the CUDA code would not be proof anyway.
* The live cache controls (the predecessor's T01-T07) and the performance parity need the engine and a GPU:
  `NOT_EXECUTED`.
* Three predecessor expectations were changed, each because the amendment demands it: the canonical telemetry
  metrics no longer carry a model label (A8), the emitted-token count is null with a reason (A3), and two
  hand-built records now go through the engine's receipt so that they are correlated measurements (G1).
