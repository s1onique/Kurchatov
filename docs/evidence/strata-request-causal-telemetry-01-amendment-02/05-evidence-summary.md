# 05 - The review payload (G8)

The payload is source-only, complete and separately reviewable:

| File | What it holds |
|---|---|
| `01-native-production.diff` | the whole native production diff (`src/program/generate.cpp`, the telemetry header) |
| `02-http-production.diff` | the whole HTTP production diff (`serve/server.py`, `serve/prometheus.py`, the web assets) |
| `03-telemetry-core-production.diff` | the whole telemetry core diff (`serve/reqtelemetry/`, the JSON Schema) |
| `04-test-witnesses.diff` | the whole test diff (`serve/test_*.py`, `tools/test_telemetry_mutations.py`, `tools/test_telemetry_web_accounting.py`) |
| `defects-reproduced.md` | what each defect was, and the witness that guards it |
| `corrections.md` | where each correction is, file by file and symbol by symbol |
| `test-evidence.md` | the commands, the exit codes and the results |
| `exit-report.md` | the exit contract |

The diffs are generated from the repository itself (`git diff 579f5cef..HEAD -- <paths>`), so they cannot be
edited by hand and cannot drift from the tree they describe.  The historical evidence of the predecessor
(`docs/evidence/strata-request-causal-telemetry-01*`) is NOT part of this payload: it is history, and it would
duplicate the review content.

The evidence is bound to the tested code head (see `SHA256SUMS` and the exit report), and the repository's final
head is recorded separately.
