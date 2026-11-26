# 02 - The telemetry contract (W1)

The canonical record is defined once, in `serve/reqtelemetry.py`, and exported as a JSON Schema
(`docs/telemetry/strata-request-telemetry-1.schema.json`). The file on disk and the code's `SCHEMA` are checked
against each other by `tools/test_reqtelemetry_schema.py`, so the contract on the wire and the contract in the
code cannot drift apart.

## The sections

```
schema_version
identity        who the request was and which engine ran it
lifecycle       how it ended
prompt          the token accounting
cache           where the reusable prefix came from and what happened to it
timing_ms       each stage's duration, and who measured it
generation      what was produced
measurement_quality   what is missing, and why
```

## The rules that matter

### An unavailable measurement is null, never 0

`0` is a measured zero: "the engine reused no tokens" is a measurement. "the engine did not say" is not.

The record has exactly three ways to become null, and no fourth:

| How | Where |
|---|---|
| the engine did not send the field | `apply_engine` leaves it null and says so in `unavailable_fields` |
| the server did not measure it | the timing is simply absent from `timing_ms` |
| the measurement does not exist in this build | `mark_unavailable` records why |

There is no path that turns a missing number into a zero, and no path that derives a missing number from a
duration.

### The accounting identities are checked, never enforced

```
0 <= reused_prefix_tokens <= matched_prefix_tokens <= submitted_tokens
submitted_tokens = reused_prefix_tokens + non_prefix_reused_tokens + evaluated_tokens
replayed_tokens <= evaluated_tokens
evaluation_work_tokens >= evaluated_tokens
```

`RequestRecord.conservation()` returns the broken identities as a list of sentences. `seal()` marks the record
`partial` when the list is not empty and records the reason. **No measurement is ever adjusted to make an
identity come out right** - the broken numbers stay in the record, visible.

The same identities are checked natively, in `include/strata/program/reqtelemetry.hpp`
(`check_accounting`), and the native test drives them.

### The cache disposition comes from evidence, never from a duration

`derive_disposition()` looks at the matched prefix, the reused prefix and the submitted prompt - and at nothing
else. A fast request with no reuse is a cold miss; a slow request with a full hit is a full hit.

### The identity

| Field | Who makes it | What it is for |
|---|---|---|
| `request_id` | the server | the primary key: unique per physical attempt, never derived from the client's |
| `client_request_id` | the client (`X-Request-ID`) | a label for the operator: checked, never a key, never an authentication |
| `server_instance_id` | the server | changes when the server restarts |
| `engine_instance_id` | the server | the engine process (`pid` and generation): changes when the engine restarts |
| `engine_invocation_id` | the engine (echoed) | the id the request carried into the engine |
| `slot_id` | the engine | the execution slot |
| `model_id`, `build_revision` | the server | what ran |

Concurrent requests with the same client id stay distinct: the store's key is the server's id, and the client's
id is only a filter.

## The vocabulary

| Field | Values |
|---|---|
| `lifecycle.state` | `queued`, `running`, `completed`, `cancelled`, `failed`, `rejected` |
| `cache.source` | `none`, `resident_slot`, `conversation_cache`, `restored_checkpoint`, `multiple`, `unknown` |
| `cache.disposition` | `cold_miss`, `full_hit`, `partial_hit`, `match_without_usable_state`, `bypassed`, `invalidated`, `unknown` |
| `measurement_quality.state` | `complete`, `partial`, `unsupported`, `instrumentation_error` |

The engine's own words are mapped into them, not replaced: `cache.reason_code` keeps the engine's reason
(`exact_match`, `token_mismatch`, `steering_mismatch`, `ineligible`, `evicted`, `absent`, ...), and the mapping is
in `serve/reqtelemetry.py`'s `REASON_CODES`.

## The JSON Schema

`docs/telemetry/strata-request-telemetry-1.schema.json` (draft 2020-12). It requires every section, fixes the
section keys, bounds the enumerations and the numbers, and forbids an unknown key.

`validate()` uses the `jsonschema` package when it is installed and a built-in checker when it is not, so the
contract can be checked on a bare Python.

Both were run against the exported schema file and the record the server produces: **VALID** with the real
`jsonschema` (draft 2020-12) and **VALID** with the built-in checker. `tools/test_reqtelemetry_schema.py` also
checks that the file on disk and the code's `SCHEMA` are the same contract, and that a record which is NOT valid
is rejected (a broken field, a missing section, an unknown disposition, an unknown section).
