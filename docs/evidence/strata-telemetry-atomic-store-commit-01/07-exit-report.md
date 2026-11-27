# ACT-STRATA-TELEMETRY-ATOMIC-STORE-COMMIT-01 - EXIT REPORT

## The heads

```yaml
ENTRY_HEAD: 0d57d20be3c29b07a469e672214066499c71493f
TESTED_CODE_HEAD: 075fdcf147e23c4b0cb1f5574979330da946d875
FINAL_HEAD: 075fdcf147e23c4b0cb1f5574979330da946d875
```

`REVIEWED_CODE_HEAD` of the act was `f1a7233bdd36f3c9b7b83fde158be8657eac7f7c` (the predecessor's code head).
The corrections are one commit on top of the ENTRY_HEAD, and the evidence is one commit on top of that.

## The five defects

```yaml
R1_RETENTION_ROLLBACK: CLOSED - the retention is part of the commit: the record is kept and the old records are
  evicted only after the aggregation committed.  A failed transaction touches nothing that was retained, B is
  not retained, A is retained and unchanged, the retained bytes describe A exactly, the retention-eviction
  counter is unchanged, and B's dispatch is counted as missing.  The retained history is NOT copied: only the
  counters, the bounded engine marks, the histograms and the sequence state are snapshotted.
R2_OVERSIZED_RECEIPT_ROLLBACK: CLOSED - with the supported 4096-byte budget and a receipt above it, the
  original exception is preserved, the rollback removes nothing that does not exist, the sequence and the
  retention accounting stay consistent, the dispatch population conserves, and the records that were retained
  before are unchanged.  The documented retention policy of the successful oversized receipt is unchanged: it
  is dropped at once and the request itself is committed.
R3_MEMBERSHIP_FILTER_ROLLBACK: CLOSED - the engine identity is remembered in the membership filter when the
  transaction commits, not inside the aggregation.  authoritative_evictions_after_failure: 0,
  authoritative_evictions_after_success: 11, unattributed_evictions_after_success: 0.  The filter and its
  hashing are not redesigned.
R4_EXACT_RETAINED_BYTES: CLOSED - the retained size is the exact size of the document that is kept: the UTF-8
  serialized representation, sequence field included.  The sequence's own width is part of it (9 -> 10 and
  99 -> 100 cost one byte each).  The serialization stays outside the global lock.
R5_STORE_COMMIT_IDEMPOTENCY: CLOSED - a record that is already committed is recognized by its own content and is
  not committed again: requests 1, eligible_requests 1, invocations 1, eligible_invocations 1, coverage 1.0,
  request_coverage 1.0.  The authoritative measurements, the histograms and the population resolution are not
  duplicated.  The committed identities are bounded (COMMITTED_RECORDS_LIMIT = 1024).
```

## The rest of the closure

```yaml
POPULATION_CONSERVATION: HELD - dispatched = accounted + missing + unresolved at quiescence, and the
  unresolved population is empty.  Measured on the real path (three completed requests and one whose
  aggregation really ran and then failed): dispatched 4, accounted 3, missing 1, unresolved 0.
FULL_SUITE: PASS (with the pre-existing failures of this host) - 1263 tests, 4 failures and 2 errors, the
  IDENTICAL failure set of the ENTRY_HEAD baseline (1252 tests, 4 failures and 2 errors).  The four failures
  and the two errors are the structured-output and JSON-schema cases of this host; they are not telemetry and
  they are not new.  The telemetry suites (208 tests), the schema tool and the three browser tools all pass.
MUTATION_RESULTS: 5 + 49 - the five narrow reversals of this segment each make their witness fail, and the five
  predecessor mutation suites (12 + 9 + 8 + 8 + 7) still pass.
PATCH_HYGIENE: CLEAN - the incremental source-only diff touches five paths and nothing else:
  serve/reqtelemetry/store.py (the correction), serve/test_telemetry_store_commit.py (the witnesses, new),
  serve/test_telemetry_amendment01_final.py (the predecessor's rollback witness, strengthened),
  tools/test_telemetry_store_commit_mutations.py (the reversals, new), docs/TELEMETRY.md (the documentation of
  the correction).  No native file, no build artifact, no unrelated refactoring.
PRODUCTION_STATE_CHANGED: NONE - no deployment, no engine restart, no live inference qualification, and no
  change to the deployment repositories or to .kurchatov-acts/.  The native engine (include/, src/,
  CMakeLists.txt) is untouched, so the isolated CUDA build and the native live qualification are unchanged and
  remain INDEPENDENT qualifications.
UNRESOLVED_DEFECTS: NONE in R1-R5.  The predecessor's F2-F5 and the request-local population accounting are
  preserved: their witnesses pass unchanged.
EVIDENCE_LOCATION: docs/evidence/strata-telemetry-atomic-store-commit-01/
FINAL_DISPOSITION: SOURCE_ACCEPTANCE_READY
```

## The witnesses

| Witness | Result |
|---|---|
| RETENTION_ROLLBACK_WITNESS | PASS - the retained evidence is untouched by the failed transaction.  FAILS at ENTRY_HEAD (`the retained evidence was lost`) |
| OVERSIZED_ROLLBACK_WITNESS | PASS - the original exception survives, and nothing that does not exist is removed.  ERRORS at ENTRY_HEAD (`IndexError: pop from empty list`) |
| MEMBERSHIP_FILTER_ROLLBACK_WITNESS | PASS - 0 authoritative evictions after the failure, 11 after the success, 0 unattributed.  FAILS at ENTRY_HEAD (the engine was marked as observed) |
| RETAINED_BYTES_WITNESS | PASS - the retained size is the exact size of the kept document.  FAILS at ENTRY_HEAD (`1992 != 2002`) |
| STORE_COMMIT_IDEMPOTENCY_WITNESS | PASS - requests 1, eligible_requests 1, invocations 1, eligible_invocations 1, coverage 1.0, request_coverage 1.0.  FAILS at ENTRY_HEAD (`2 != 1`) |

## What was not touched

* The membership filter's design and its hashing: the identity is only DEFERRED to the commit.
* The receipt model, the native instrumentation, the dashboard, the request-local population accounting and the
  accepted F2-F5 corrections.
* The historical evidence of the earlier segments: only the correction of the stale `TESTED_CODE_HEAD` was
  appended to the predecessor's exit report.
