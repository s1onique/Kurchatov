# 00 - The entry state of ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-02

```yaml
ACT_ID: ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-02
ADDENDUM: FULL_DIFF_REVIEW_01
REPOSITORY: s1onique/Kurchatov
ENTRY_HEAD: 579f5cef1b5ead2c38079f9b7e5b867838bf703e   # the tree the amendment started from
REVIEWED_CODE_HEAD: 646c066d62f9df57382f6d56fc6147bc4967d4e9
PRODUCTION_DEPLOYMENT_AUTHORIZED: false
LIVE_GPU_QUALIFICATION_AUTHORIZED: false
```

## What was already in the tree

* `646c066d` is the predecessor's code head (the corrections of AMENDMENT-01);
* `579f5cef` adds the evidence of that code head: the evidence commits do not touch the production tree
  (the diff of the evidence commits is `docs/evidence/` only);
* the working tree had exactly one untracked path, `.kurchatov-acts/`, which this amendment does not touch.

## The host

| | |
|---|---|
| the host | macOS (Darwin), no CUDA toolkit, no GPU |
| the Python | `/tmp/stratavenv` - the repository's REAL dependencies (`jinja2`, `regex`, `jsonschema`) are installed there |
| the JavaScript | `osascript -l JavaScript` (macOS); no `node` |

The predecessor's full-suite gate was `BLOCKED_ENVIRONMENT` because the `regex` wheel was missing.  It is
installed now, so the full suite ran with the repository's real dependencies (see `03-test-evidence.md`).

## What this amendment does NOT touch

`.kurchatov-acts/`, the deployment repository, the running production instance, the cache policy, the sampling,
the model's execution and the context handling.  The engine's cache selection, checkpoint policy and scheduler
are unchanged: the native diff is two measurement sites (see `04-native-production.diff`).
