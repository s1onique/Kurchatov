# 04 - The test evidence

## The commands

```bash
# the telemetry's own suites (the production exporter, the production store, the real HTTP handlers)
PYTHONPATH=/tmp/pystubs /usr/bin/python3 -m unittest serve.test_reqtelemetry serve.test_telemetry_integrity

# the schema on disk is the schema in the code
/usr/bin/python3 tools/test_reqtelemetry_schema.py

# the engine's writer against the server's reader
/usr/bin/python3 tools/test_reqtelemetry_roundtrip.py

# the non-vacuity: every witness fails when its correction is reversed
/usr/bin/python3 tools/test_telemetry_mutations.py

# the native encoder (no CUDA needed)
g++ -std=c++20 -Iinclude -o /tmp/reqtelemetry_test src/program/reqtelemetry_test.cpp && /tmp/reqtelemetry_test

# the whole server suite
PYTHONPATH=/tmp/pystubs /usr/bin/python3 -m unittest discover -s serve -p 'test_*.py'
```

## The results

| Command | Result |
|---|---|
| `serve.test_reqtelemetry` | 49 tests, OK |
| `serve.test_telemetry_integrity` | 38 tests, OK |
| `tools/test_reqtelemetry_schema.py` | all checks passed |
| `tools/test_reqtelemetry_roundtrip.py` | 6 tests, OK |
| `tools/test_telemetry_mutations.py` | 8 tests, OK |
| `src/program/reqtelemetry_test.cpp` | all checks passed (exit 0) |
| `src/program/reqtelemetry_roundtrip.cpp` | builds (g++ -std=c++20) |
| the whole server suite | see 05-suite-results.md |

## The environment's own limit

The `regex` wheel is not installed on this host and there is no network, so the suite runs with the **local-only**
stand-in described in 00-entry-state.md. The nine tests that fail because of it fail **in the unmodified entry
commit as well** (the baseline run of 05-suite-results.md). They are not caused by this amendment.
