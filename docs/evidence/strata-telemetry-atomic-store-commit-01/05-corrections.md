# ACT-STRATA-TELEMETRY-ATOMIC-STORE-COMMIT-01 - the corrections

## The stale `TESTED_CODE_HEAD` of the predecessor's exit report

The exit report of `strata-request-causal-telemetry-01-closure-01-amendment-01-final-correction` carried

```yaml
TESTED_CODE_HEAD: 4b788abcb0694435c9ad3ddde99f3bf0716167de
FINAL_HEAD: f1a7233bdd36f3c9b7b83fde158be8657eac7f7c
```

`4b788abc` is the code head of the PREVIOUS segment (the A1-A6 corrections).  The code that was tested in the
final-correction segment is `f1a7233b` - the F1-F5 corrections, the witnesses they brought and the reversal suite.
The commit `0d57d20b` added only the evidence documents.

A correction is APPENDED to that report (its text is preserved, nothing above is rewritten):

```yaml
ENTRY_HEAD: 3769eed7bc82784ce9d06be78a553b2620b38329
TESTED_CODE_HEAD: f1a7233bdd36f3c9b7b83fde158be8657eac7f7c
FINAL_HEAD: f1a7233bdd36f3c9b7b83fde158be8657eac7f7c
EVIDENCE_HEAD: 0d57d20be3c29b07a469e672214066499c71493f
```

## The corrections of this segment

| Where | Before | Now |
|---|---|---|
| the retention on a failure | the record was kept, and the old records evicted, BEFORE the aggregation ran | the retention is part of the commit: the record is kept and the old records are evicted only after the aggregation committed |
| the rollback of an oversized receipt | it removed a record that the retention had already dropped, and the original exception was lost | nothing is removed that does not exist, the original exception is preserved, and the sequence and the retention accounting stay consistent |
| the engine identity on a failure | it was written into the membership filter inside the aggregation | it is remembered when the transaction commits |
| the retained size | it was measured before the sequence field was inserted | it is the exact size of the document that is kept, sequence field and width included |
| a record that is committed twice | it could be committed again, and counted again | a committed record is recognized by its own content and is not committed again; the committed identities are bounded |
