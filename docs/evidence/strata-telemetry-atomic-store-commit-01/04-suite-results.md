# ACT-STRATA-TELEMETRY-ATOMIC-STORE-COMMIT-01 - the suites

## The complete real-dependency suite

The suite was run SERIALLY against the committed tree, with the real dependencies of this host
(`~/anaconda3/bin/python`, Python 3.11.2).  No source or test file was edited while it ran.

```text
python -m unittest discover -s serve -p "test_*.py" -t .
Ran 1263 tests in 368.602s

FAILED (failures=4, errors=2, skipped=12)
```

## The baseline at ENTRY_HEAD

The same suite was run against the ENTRY_HEAD tree, exported unchanged with
`git archive 0d57d20be3c29b07a469e672214066499c71493f`:

```text
Ran 1252 tests in 377.077s

FAILED (failures=4, errors=2, skipped=12)
```

The two failure sets are IDENTICAL (the diff of the sorted `FAIL:`/`ERROR:` lines is empty):

```text
FAIL: test_invalid_generation_is_an_error_and_never_streams_content (serve.test_structured.Structured...) x3
FAIL: test_invalid_schema_is_400_and_local_refs_work (serve.test_structured.Structured...)
ERROR: test_a_text_answer_that_breaks_the_schema_fails_as_without_tools (serve.test_responses.JsonFormatWithTools...)
ERROR: test_json_schema_text_format (serve.test_responses.OverHttp...)
```

Those four failures and two errors are PRE-EXISTING at ENTRY_HEAD and are not telemetry: they are the
structured-output and JSON-schema cases of this host.  The correction adds 11 tests (1252 -> 1263) and no new
failure.

## The telemetry suites

| Suite | Result |
|---|---|
| `serve/test_telemetry_store_commit.py` | 11 tests, OK |
| `serve/test_telemetry_amendment01_final.py` | 18 tests, OK (the rollback witness now runs the real aggregation before the injection) |
| `serve/test_telemetry_amendment01.py`, `.../amendment02.py`, `.../amendment03.py`, `.../closure01.py`, `serve/test_reqtelemetry.py` | 199 tests, OK |
| `tools/test_reqtelemetry_schema.py` | all checks passed |
| `tools/test_telemetry_web_accounting.py` | 4 cases checked with osascript |
| `tools/test_telemetry_web_inspector.py` | the invocation inspector was checked with osascript |
| `tools/test_telemetry_web_status.py` | 3 cases checked with osascript |

The browser's JavaScript engine on this host is `osascript` (macOS); there is no `node` here.

## The native engine

No native file changed (`include/`, `src/`, `CMakeLists.txt` are untouched), so the isolated CUDA build and the
native live qualification are unchanged.  They remain INDEPENDENT qualifications and are not claimed here.
