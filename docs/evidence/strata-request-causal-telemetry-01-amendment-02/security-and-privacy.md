# 08 - The security and the privacy

The amendment adds measurements and identities; it adds **no** content.

| Never captured | Where it would have come from |
|---|---|
| raw prompts, conversation messages | the record has counts only |
| generated answers, private reasoning, tool arguments, tool results | the record has counts and fixed words |
| authorization headers, API keys | the record has no header and no key |
| raw token ids, prompt hashes | the record has counts and positions |

The amendment's new fields are:

| Field | What it is |
|---|---|
| `identity.engine_invocation_ordinal` | a whole number: which attempt of the request it was |
| `measurement_quality.native_correlation` | one of four fixed words |
| `measurement_quality.native_partial` | true or false |
| `measurement_quality.measurement_valid` | true or false |
| `measurement_quality.aggregate_eligible` | true or false |

The privacy witness of the predecessor (`serve/test_reqtelemetry.py::Evidence.test_the_evidence_carries_no_content`)
lists every key the evidence may hold; the amendment's four new keys were added to that list, and the witness
still fails when a forbidden key appears.

The access control is unchanged: the request-level endpoints fail closed on a non-loopback listener without an API
key, the existing authentication is not weakened, no CORS permission was added and no credential was placed in a
URL or in the browser's stored configuration.

## The evidence writer's bounds

The writer is metadata-only, bounded and asynchronous:

* the queue is bounded by RECORDS and by BYTES, and the BYTES are the serialized UTF-8 bytes with the framing;
* the bound counts the queued records AND the record the worker is writing;
* a full queue DROPS the record and counts it; a write that fails counts a failure; a refused write (no handle)
  counts a failure;
* `flush()` returns true only when every record it accepted reached a terminal writer outcome; a timeout is
  counted as an incomplete flush and the evidence is **not** reported as durable;
* the worker owns the file handle until it has stopped using it;
* nothing is written synchronously on the inference thread.

These are serialized-data budgets, not a claim about the process's RSS: the bytes the writer holds are bounded,
and the Python objects around them are the writer's own.
