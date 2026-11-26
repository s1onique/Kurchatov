# 05 - The evidence summary

ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-03: a narrow closure amendment over the amendment-02 tree.

| | |
|---|---|
| the entry head | `57fe8dfd15b3b02fba0ce837101b685251ef487c` |
| the tested code | `ed2b10b27f6e8db69b6f654419f99f8510bb268a` |
| the final repository head | the commit that adds this directory; its hash is recorded in `final-head.txt` |
| the source tree between them | the evidence directory only (the proof is in `final-head.txt`) |

## What was corrected

| Gate | The defect that was reproduced | The correction | The witness |
|---|---|---|---|
| G1 | One mutable set of native measurements on the record: the numbers of an earlier invocation survived under the identity of a later one. | Every dispatch owns a measurement receipt (`serve/reqtelemetry/invocation.py`), bound before the dispatch and validated against that identity. The record's native fields describe ONE invocation; with more than one they are null. | `serve/test_telemetry_amendment03.py` - `InvocationOwnership` (11 witnesses, the production dispatch loop and the real HTTP transport) |
| G2a | The complete cache-reuse ratio admitted an `unevaluated` accounting. | The ratio's class needs an accounting that **satisfied**. | `MetricAdmission.test_an_unevaluated_accounting_is_not_admitted_to_the_complete_ratio` |
| G2a | A valid partial work counter was excluded with the complete accounting. | The work counters have their own class: an unevaluated accounting does not exclude them. | `MetricAdmission.test_a_valid_partial_work_counter_stays_eligible` |
| G2b | The duration observer bypassed the correlation and the segment-completeness checks. | The native durations are observed from the receipt that measured them, and only when it is correlated and whole. | `MetricAdmission.test_an_uncorrelated_native_duration_is_not_observed` and the five beside it |
| G2c | The coverage had no documented denominator; the browser's numbers mixed two populations. | The coverage publishes the eligible and the missing population of the native invocations and the request's coverage beside it; the browser's rates use the population their duration describes. | `MetricAdmission.test_the_coverage_publishes_both_populations`, `serve/web/telemetry.js` |
| G3 | The writer's bound used `len(queue) + writing`: the records the worker had DETACHED were not counted. | The bound uses the authoritative `outstanding_records`; the acceptance boundary closes atomically; the counter domains are exact; the handle is closed later when a timed-out shutdown finally stops the worker. | `EvidenceWriterClosure` (4 witnesses) |
| G4 | The native error path emitted a correlated ERR receipt but dropped the already measured `tele_restore_ms`. | The duration goes out with the evidence. | `src/program/generate.cpp`, `src/program/reqtelemetry_test.cpp` (case 7), the source-level mutation witness |
| G5 | An unexpected handler exception after a 200 produced a completed outcome; the evidence delivery loss was invisible; the retired engine instances' state was unbounded; an unknown engine identity merged domains; the cursor's validation and the page came from two snapshots. | Each was corrected narrowly (see the commit message). | `LifecycleAndBounds` and `HttpLifecycle` (9 witnesses) |

## The non-vacuity witnesses

Every correction was reversed in memory and its witness was shown to FAIL: `tools/test_telemetry_amendment03_mutations.py`
(8 witnesses, one per named mutation). The predecessor's own mutation witnesses still pass
(`tools/test_telemetry_mutations.py`, 12 witnesses).

## The test evidence

Every command was run on this host (macOS, no GPU, no CUDA) against the committed tree. The Python is
`/tmp/stratavenv`, which has the repository's REAL dependencies (`jinja2`, `regex`, `jsonschema`).

| # | Command | Result |
|---|---|---|
| 1 | `/tmp/stratavenv/bin/python -m unittest discover -s serve -p 'test_*.py'` | **1162 tests, OK (20 skipped)**, exit 0, 388 s - the whole server suite, with the repository's real dependencies |
| 2 | `/tmp/stratavenv/bin/python -m unittest serve.test_reqtelemetry serve.test_telemetry_integrity serve.test_telemetry_amendment02 serve.test_telemetry_amendment03 serve.test_prometheus` | 163 tests, OK |
| 3 | `/tmp/stratavenv/bin/python tools/test_reqtelemetry_schema.py` | `test_reqtelemetry_schema: all checks passed` (the schema on disk IS the schema in the code) |
| 4 | `/tmp/stratavenv/bin/python tools/test_telemetry_mutations.py` | 12 witnesses, OK (the predecessor's non-vacuity witnesses still hold) |
| 5 | `/tmp/stratavenv/bin/python tools/test_telemetry_amendment03_mutations.py` | 8 witnesses, OK (one per named mutation: every correction reversed makes its witness fail) |
| 6 | `/tmp/stratavenv/bin/python tools/test_telemetry_web_accounting.py` | 4 cases checked with osascript (the browser presentation) |
| 7 | `/tmp/reqtelemetry_test` (`clang++ -std=c++17 -O1 -Iinclude src/program/reqtelemetry_test.cpp`) | `reqtelemetry_test: all checks passed`, exit 0 (the native encoding, without a GPU) |
| 8 | `/tmp/stratavenv/bin/python tools/test_reqtelemetry_roundtrip.py` (the real native writer, built) | 6 tests, OK (the engine's writer against the server's reader) |
| 9 | `git diff --check 57fe8dfd..HEAD` | clean (no whitespace error) |
| 10 | `git diff --check 5b0e549b..HEAD` | clean (no whitespace error) |

## What was NOT executed here, and why

| | |
|---|---|
| the CUDA build (sm_61 / sm_120) | **NOT_EXECUTED**: this host has no CUDA toolkit (`nvcc` is not installed) and no NVIDIA GPU. The isolated build may run on a CUDA host, independently of the running engine. |
| the live native qualification | **NOT_EXECUTED**: it needs the engine on a GPU. The native half that does not need one (the encoding) is covered by `src/program/reqtelemetry_test.cpp`. |
| the performance parity | **NOT_EXECUTED**: nothing on the inference path changed - the native production diff is 17 lines, all of them in the restoration's error path - and this host cannot measure a GPU run. The server's per-dispatch cost grows by one small receipt; it was not measured here. |
| fsync-level durability | **NOT_CLAIMED**: the evidence writer flushes; it does not claim the bytes reached the disk's platter. |

## The scope

Nothing outside the telemetry changed: no cache policy, no scheduler, no kernel, no model path, no API shape. The
record's contract changed incompatibly (the schema version is `strata.request-telemetry/2`), and the version is
published in the record, in the schema file and in the documentation.

The `.kurchatov-acts/` directory, the deployment repositories and the running production instance were not touched.

## The artifacts

| File | What it holds |
|---|---|
| `01-native-production.diff` | the native production change (the restoration's error evidence) |
| `02-http-production.diff` | the HTTP server, the exporter and the browser view |
| `03-telemetry-core-production.diff` | the telemetry core, the schema and the documentation |
| `04-test-witnesses.diff` | the witnesses, the mutation witnesses and the native host test |
| `05-evidence-summary.md` | this file |
| `SHA256SUMS` | the checksums of the five files above |

The historical evidence directory of the predecessor is NOT embedded in this one: each digest covers only the
files of this amendment.

## The replay, the cumulative work and the lookup/restore overlap

The record publishes the **cumulative** evaluation work of an invocation (`evaluation_work_tokens`) and the
**distinct** positions it evaluated (`evaluated_tokens`). They are two different numbers and both are published;
their difference is never asserted to be zero.

The lookup duration (`cache_lookup`) covers the candidates the engine examined and the choice; the restoration
duration (`cache_restore`) covers the state mount, which happens INSIDE that window. The two durations therefore
OVERLAP in wall-clock time. The record publishes them as two separate observations and does **not** publish a
"total native time": their sum is not a duration, and nothing here claims it is. A measurement that was not taken
stays null - no zero is asserted for it, and no equivalence between the two windows is asserted.

The measured domains are exactly these: the lookup (the candidate examination and the choice), the restoration
(the state mount), the engine's own prefill wall time and its own decode wall time.

## The CUDA-dependent assumptions (registered, not verified here)

| Assumption | Where it lives | How it would be checked |
|---|---|---|
| the engine echoes the invocation's id on its DONE line | `include/strata/program/reqtelemetry.hpp` | a live run with `STRATA_TELEMETRY=1` |
| the engine echoes it on its ERR line too | `src/program/generate.cpp` | a live run whose request fails |
| the ERR line carries the measured restoration duration | `src/program/generate.cpp` | a live run that fails a restoration |
| a batch slot's admission segment is marked as partial | the batch path | a live run with `--batch` |
| the prefill and decode durations the engine reports | the DONE line | a live run |
| the cumulative work and the distinct positions the engine reports | the DONE line | a live run with a reused prefix |

These need a GPU. The half that does not - the encoding the server reads - is covered by the host-compilable test
(`src/program/reqtelemetry_test.cpp`, case 7 for the error evidence).

## The proof of the source tree

`final-head.txt` (added by the commit that follows the one that adds this directory) records the hash of the
commit that carries these artifacts and the one command that shows the tree did not change between the tested
code and it:

```
git diff --stat ed2b10b27f6e8db69b6f654419f99f8510bb268a..<the evidence commit>
```

The only files that differ are the ones under `docs/evidence/strata-request-causal-telemetry-01-amendment-03/`.
The production sources, the tests and the schema are byte-identical to the tree that was tested.
