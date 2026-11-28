# 01 - The supported qualification envelope (W1)

ACT: **ACT-KURCHATOV-UPSTREAM-SYNC-01**, execution segment `QUALIFICATION-HANDOFF`
Candidate revision: `859d62c4a7f6bf3b1942ff1c6e61e4405f91623a`
Accepted merge head: `74e89653e98d855d292c373075a5f1978df56a23`
Pinned upstream head: `42e489d145aaf4430b54f2c58679be27d45faf17`

This document records the **actual** configuration keys of the upstream revision - the ones the engine's own
source reads - and the effective settings that the initial native qualification envelope uses. Every key
below was read out of the candidate's own source; **no configuration name is invented here**.

## 1. The keys, as the candidate's own source reads them

| Restriction of the envelope | The actual key | Where the candidate reads it | How it is turned off |
| --- | --- | --- | --- |
| The telemetry itself | `STRATA_TELEMETRY` | `engine/include/strata/program/reqtelemetry.hpp:40` (`enabled()`), `engine/src/program/generate.cpp:13908` | `=0` (the rule is `switch_on`: only the value `"1"` turns it on, `engine/include/strata/program/reqtelemetry.hpp:35`) |
| SSD conversation-cache spilling | `--conversation-spill-mib` (CLI) / `o.conversation_spill_mib` | `engine/src/program/generate.cpp:4106` (the CLI), `:14070` (`!= 0` enables the tier), `:1116` (the option's own comment) | `--conversation-spill-mib 0` |
| Slot-read optimization | `STRATA_SLOT_READ` | `engine/src/program/generate.cpp:16230` (`slot_read_cap`), `:7849` (`STRATA_SLOT_READ_WIDE` is subordinate to it) | unset, empty or `0` (the rule is `e == nullptr \|\| e[0] == '\0' \|\| e[0] == '0'`) |
| Replica routing | `--replicas` (CLI) / `"replicas"` (the run config) | `terminal/serve/server.py:11170` (the CLI), `:11260` (the config), `:10532` (`start_replicas`) | not passed (the default is `None`, so no replica group is built) |
| Split prefill/decode serving | `--split-serve` (CLI) / `"split_serve"` (the run config) | `terminal/serve/server.py:11178` (the CLI), `:11261` (the config), `terminal/serve/split.py` | not passed (the default is `None`, so no split engine is built) |

The two subordinate slot-read switches are `STRATA_SLOT_READ_WIDE` and `STRATA_SLOT_READ_AHEAD`
(`engine/src/program/generate.cpp:17616` and `:17623`). Both are read only *after* `slot_read_cap` is true,
so turning `STRATA_SLOT_READ` off turns the whole family off; they are listed here so that the envelope is
complete, not because they need a separate setting.

## 2. The effective settings of the initial envelope

```yaml
QUALIFIED_EXECUTION_ENVELOPE:
  ONE_ENGINE_PER_GPU_HOST: true
  MODEL: the existing Qwen model and its existing quantization (unchanged by this ACT)
  SSD_CONVERSATION_CACHE_SPILLING: disabled   -- --conversation-spill-mib 0
  STRATA_SLOT_READ: disabled                   -- unset (the rule reads unset as off)
  REPLICA_ROUTING: disabled                    -- no --replicas, no "replicas" in the run config
  SPLIT_PREFILL_DECODE_SERVING: disabled      -- no --split-serve, no "split_serve" in the run config
```

**These restrictions apply only to the initial qualification envelope.** No upstream default is changed and
no feature is removed: the keys above are the upstream's own opt-ins and opt-outs, read at their upstream
boundary, and the tree's defaults are untouched.

## 3. The effective configuration, read from the actual running engine

The engine is the authority for its own effective settings. Three of them are reported by the engine itself:

| Setting | How the engine reports it | Source |
| --- | --- | --- |
| the telemetry switch | the `DONE` line's `key=value` suffix carries `cache_source=` / `cache_reason=` only when `STRATA_TELEMETRY=1` | `engine/src/program/generate.cpp:23901` (`tele_txt`), `:23858` (`tele.source`) |
| the slot-read state | the `INFO` line carries `slot_read=0` / `slot_read=1` | `engine/src/program/generate.cpp:16285` |
| the conversation cache's own state | the `INFO` line's `cache=` and the `parked=` / `bytes=` counters of the restore line | `engine/src/program/generate.cpp:20225` (the restore line), `:16285` |

The **record** of the effective configuration is therefore the engine's own `INFO` line and the `DONE` line
of the first request, taken from the running engine's log - not a value typed into a configuration file.
Section 03 of this evidence records the run that produced them.

### 3.1 The effective configuration of the actual running engine, as measured

The incumbent deployment on the qualification host was read out of the **running engine's own process**
(PID `2181002`, the process that holds the card's VRAM). Its own command line is:

```text
/opt/polystrata/engine-cuda12/strata --serve
  --pack /srv/polystrata-data/packs/q2_0
  --native /srv/polystrata-data/models/Q2_0/Qwen3.8-Flash-Next-GSQ-RCO-Q2_0-00001-of-00002.gguf
  --ple-gguf /srv/polystrata-data/models/Q2_0/Qwen3.8-Flash-Next-GSQ-RCO-Q2_0-00002-of-00002.gguf
  --expert-profile /opt/polystrata/data/expert-profile.bin
  --expert-cache auto --prefill auto --spec 4 --spec-min-p 0.5
  --mtp /srv/polystrata-data/mtp/rt --max-context 131072 --kv int8 --kv-resident 32768
```

and the environment of that same process carries **none** of the envelope's keys
(`STRATA_SLOT_READ`, `STRATA_TELEMETRY`, `STRATA_CACHE_DIAG` are all absent).

| The envelope's restriction | The running engine's effective setting | How it was measured |
| --- | --- | --- |
| one engine per GPU host | **one** engine, one card (the P40), `CUDA 0` in the engine's own log line `GPU 0: Tesla P40, compute capability 6.1` | the engine's own log and the process list (`nvidia-smi --query-compute-apps`) |
| the existing Qwen model and quantization | **Qwen3.8-Flash-Next, Q2_0**, the native pack's two shards, in the existing data folder | the engine's own command line |
| SSD conversation-cache spilling | the tier's **own** state: the engine's log carries no `conversation-spill` line at all, so the tier never opened a folder | the engine's own log (`grep -c "conversation-spill"` -> 0) |
| `STRATA_SLOT_READ` | **off** - the variable is absent, and the engine's own rule (`engine/src/program/generate.cpp:16230`) reads an absent value as off; the engine's own log carries **no** `slot_read=` line, which is what the engine prints only when the capability is on (`:16285`) | the process's own environment and the engine's own log |
| replica routing | **off** - the command line carries no `--replicas`, and the count of the envelope-switching flags in the engine's own command line is **0** | the engine's own command line |
| split prefill/decode serving | **off** - the command line carries no `--split-serve` | the engine's own command line |

The envelope is therefore **already the running configuration** of the incumbent deployment on this host,
which is why the native measurement needs no change of the deployment to be taken inside it. The two
settings that the incumbent does **not** carry are the SSD tier's `--conversation-spill-mib 0` and the
telemetry's `STRATA_TELEMETRY=1`; both are **deployment profile** settings that the successor applies
when it takes the native measurements, and neither changes a default of the tree.

## 4. Why the envelope excludes the three paths of W3

The three paths are excluded because their measurement authority is **not established**, and the reason for
each is different. Section 02 records the evidence.

| Path | What the candidate's own source does | Why it is outside the envelope |
| --- | --- | --- |
| SSD cache tier | the engine tracks `from_ssd` (`engine/src/program/generate.cpp:19675`) and reads an SSD entry back at `:19708`-`:19752`, but the telemetry's source classification at `:20236` does not consult it | an SSD-restored image is reported as `parked_live` / `parked_checkpoint`, which are RAM-tier names: a RAM-tier match would be **fabricated** from an SSD reuse |
| Slot-read fast path | the fast path prints its own `DONE` line at `engine/src/program/generate.cpp:19657` **without** the telemetry suffix, while the normal path appends it at `:23902` | the encoder is bypassed: the evidence is **absent**, and the fast path's `DONE 0` line is not a request's own measured answer |
| Replica routing | `ReplicaEngine` (`terminal/serve/replicas.py:334`) has no `set_request_id` method, and the server only calls it behind `hasattr` (`terminal/serve/server.py:7648`) | the `rid=` never reaches the engine: the invocation correlation is **absent**, and the file is byte-identical to upstream's (inherited technical debt) |
| Split serving and the other engines | the split engine (`terminal/serve/split.py`) and the additional engines (`strata-poly`, `strata-glm`, `strata-hy4`, `strata-inkling`) have no invocation correlation and no native measurement authority | their measurements are published as **unavailable**, never as zero |

## 5. The evidence of this section

| What | Where |
| --- | --- |
| the keys, read out of the candidate's source | section 1, with the file and the line of every key |
| the effective envelope | section 2 |
| the effective configuration of the actual running engine | section 3 and `03-native-build.md` |
| the three paths' defects | `02-measurement-authority.md` |
