# ACT-STRATA-TELEMETRY-ATOMIC-STORE-COMMIT-01-CORRECTION-01 - the suites

## The complete real-dependency suite

The suite was run SERIALLY against the committed tree, with the real dependencies of this host
(`~/anaconda3/bin/python`, Python 3.11.2).  No source or test file was edited while it ran.

```text
python -m unittest discover -s serve -p "test_*.py" -t .
Ran 1271 tests in 373.836s

FAILED (failures=4, errors=2, skipped=12)
```

**This is `FAIL_BASELINE_EQUIVALENT`, not `PASS`.**  The suite is not green on this host: four failures and two
errors are present, and they are the pre-existing structured-output and JSON-schema cases of this host.  They
are not telemetry, and they are not new.

## The reconciled totals

| Run | Tree | Tests | Failures | Errors | Skipped | Verdict |
|---|---|---|---|---|---|---|
| the baseline | ENTRY_HEAD `0d57d20b` | 1252 | 4 | 2 | 12 | FAIL_BASELINE_EQUIVALENT |
| the R1-R5 corrections | `075fdcf1` | 1263 (+11) | 4 | 2 | 12 | FAIL_BASELINE_EQUIVALENT |
| this correction | `2b8fb59b` | 1271 (+8) | 4 | 2 | 12 | FAIL_BASELINE_EQUIVALENT |

The three runs have the **IDENTICAL** failure set (the diff of the sorted `FAIL:`/`ERROR:` lines is empty):

```text
FAIL: test_invalid_generation_is_an_error_and_never_streams_content (serve.test_structured.Structured...) x3
FAIL: test_invalid_schema_is_400_and_local_refs_work (serve.test_structured.Structured...)
ERROR: test_a_text_answer_that_breaks_the_schema_fails_as_without_tools (serve.test_responses.JsonFormatWithTools...)
ERROR: test_json_schema_text_format (serve.test_responses.OverHttp...)
```

The totals reconcile: 1252 + 11 (the R1-R5 witnesses) + 8 (the correction's witnesses) = 1271, and the number of
failures and errors never moved.

## The focused suites

| Suite | Result |
|---|---|
| `serve/test_telemetry_store_commit.py` (the R1-R5 witnesses, unchanged) | 11 tests, OK |
| `serve/test_telemetry_store_commit_correction.py` | 8 tests, OK |
| `serve/test_telemetry_amendment01_final.py` | 18 tests, OK |
| `serve/test_telemetry_amendment01.py`, `.../amendment02.py`, `.../amendment03.py`, `.../closure01.py`, `serve/test_reqtelemetry.py` | 199 tests, OK |
| the seven mutation suites | 12 + 9 + 8 + 8 + 7 + 5 + 2 = 51 tests, all OK |
| `tools/test_reqtelemetry_schema.py` | all checks passed |
| `tools/test_telemetry_web_accounting.py` | 4 cases checked with osascript |
| `tools/test_telemetry_web_inspector.py` | the invocation inspector was checked with osascript |
| `tools/test_telemetry_web_status.py` | 3 cases checked with osascript |

The browser's JavaScript engine on this host is `osascript` (macOS); there is no `node` here.

## The native engine

No native file changed (`include/`, `src/`, `CMakeLists.txt` are untouched), so the isolated CUDA build and the
native live qualification are unchanged.  They remain INDEPENDENT qualifications and are not claimed here.
