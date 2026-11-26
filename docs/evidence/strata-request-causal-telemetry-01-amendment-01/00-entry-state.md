# 00 - The entry state (ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-01)

```yaml
ACT_ID:       ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-01
PREDECESSOR: ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01
REPOSITORY:   s1onique/Kurchatov
TARGET_ENGINE: strata
PRIORITY:     P0
ENTRY_HEAD:   c45ec82846b2671673ff712009c8a85e1f034e2e
BRANCH:       main
```

## The working copy

| | |
|---|---|
| the working copy | `/Volumes/UserData/Users/chistyakov/Projects/SPbNIX/Kurchatov` |
| the host | macOS (Darwin), no CUDA toolkit, no GPU |
| the interpreter used here | `/usr/bin/python3` (3.9) with `jinja2` 3.1.2; the `regex` wheel is NOT installed on this host |
| tracked dirt at entry | none (only the pre-existing untracked `.kurchatov-acts/`, which was not read, not written and not committed) |
| the production instance | not touched: no rebuild, no restart, no configuration change, no deployment |

## The dependency that this host does not have

`tools/strata_tokenizer.py` imports `regex` (the compiled wheel). It is not installed here and there is no network
to install it. The server's test suite therefore cannot run as it is on this host: every test that builds a
`Service` fails at the import.

To run the suite here, a **local-only** stand-in for `regex` was used (it lives in `/tmp`, it is not part of the
repository and it is not committed):

```bash
# /tmp/pystubs/regex.py translates \p{L}, \p{N} and \p{M} into the standard library's \w and \d
PYTHONPATH=/tmp/pystubs /usr/bin/python3 -m unittest discover -s serve -p 'test_*.py'
```

The stand-in changes the tokenizer's pre-tokenizer, so nine tests that depend on the exact token boundaries fail
**in the unmodified entry commit as well** (see 04-test-evidence.md: the baseline run). They are an artefact of the
stand-in, not of this amendment. The predecessor's own evidence shows the suite passing with the real wheel
(1054 tests, 23 skipped).

## What this amendment may and may not do

* it corrects the measurement, the causal attribution and the evidence integrity;
* it does **not** deploy, does **not** restart the production engine, does **not** touch the infrastructure
  repository and does **not** touch `.kurchatov-acts/`;
* it does not change the inference semantics, the cache policy or the model execution.
