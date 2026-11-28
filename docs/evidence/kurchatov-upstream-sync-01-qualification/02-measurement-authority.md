# 02 - The measurement authority of the newly introduced paths (W3)

ACT: **ACT-KURCHATOV-UPSTREAM-SYNC-01**, execution segment `QUALIFICATION-HANDOFF`
Candidate revision: `859d62c4a7f6bf3b1942ff1c6e61e4405f91623a`

The review identified four paths that need a qualification of their own. This document records, for each of
them, **what the candidate's own source actually does**, and what that means for the measurements that the
path may produce. Each finding is read out of the candidate's source at the stated line; none of them is a
hypothesis and none of them was inferred from a name.

The three that are newly introduced by the merge are the **SSD cache tier**, the **slot-read optimization**
and **replica routing**. The fourth is **split serving and the additional engines**.

**No new instrumentation framework is authorized, and none was added.** The findings below are recorded as
they are, and the paths are kept outside the qualified envelope.

## 1. The SSD cache tier: a RAM-tier name on an SSD-tier source

### 1.1 What the source does

The engine has a **tier** of its own for the conversation cache: a conversation the RAM tier evicts or
cannot hold is written to a folder on the SSD (`engine/src/program/generate.cpp:14061`, the tier's own
setup) and read back later (`engine/src/program/generate.cpp:19708`-`:19752`).

The engine **knows** which tier a restored image came from. The flag is `from_ssd`:

```cpp
// engine/src/program/generate.cpp:19675
bool from_ssd = false;
```

and it is set on both paths that take an image out of the SSD tier - the writer's own hand-back
(`:19703`) and the read-back from the tier (`:19732`). The flag then guards the RAM-tier borrow
(`:19754`), the RAM-tier take (`:19762`) and the snapshot exchange (`:19921`).

### 1.2 The defect

The **telemetry's** source classification does not consult the flag. When the engine mounts a parked
conversation it names the source:

```cpp
// engine/src/program/generate.cpp:20236
cdiag.selected = parked_taken_live ? strata::program::cache_diag::Source::parked_live
                                    : strata::program::cache_diag::Source::parked_checkpoint;
```

The `Source` enumeration has **no** name for the SSD tier:

```cpp
// engine/include/strata/program/cache_diag.hpp:62
enum class Source : int {
    none = 0, live, active_checkpoint, parked_live, parked_checkpoint, slot,
};
```

The engine's own comment at `:20202` even records the distinction and then drops it:

```cpp
resume = taken.tokens;   // (parked.tokens unless the image came from the SSD tier)
```

So an image that came back from the **SSD** is reported to the server as `parked_live` or
`parked_checkpoint` - the two names that mean "a conversation the RAM tier held". The server maps them to
the canonical sources (`terminal/serve/reqtelemetry/correlation.py:19`-`:26`):

```python
SOURCE_NAMES = {
    "none": SOURCE_NONE,
    "live": SOURCE_RESIDENT_SLOT,
    "active_checkpoint": SOURCE_CONVERSATION_CACHE,
    "parked_live": SOURCE_CONVERSATION_CACHE,
    "parked_checkpoint": SOURCE_RESTORED_CHECKPOINT,
    "slot": SOURCE_RESIDENT_SLOT,
}
```

### 1.3 The matched prefix is derived from the RAM candidates alone

The `matched_prefix` the telemetry publishes is the common prefix against the **RAM tier's** candidates:
the walk is `ConversationCache::candidates()`
(`engine/include/strata/core/conversation_cache.hpp:411`), which walks `entries_` - the RAM-resident
entries - and the engine calls it at `engine/src/program/generate.cpp:19514`. The SSD tier's entries are
not in `entries_`; they are in the tier's own store
(`engine/include/strata/core/conversation_spill.hpp`).

So a request that was served from the SSD tier reports:

* a `cache_source` that names the **RAM** tier, and
* a `matched_prefix` that was derived from the **RAM** candidates, while the
  prefix that was really reused came from the **SSD** tier.

### 1.4 The consequence, stated plainly

**A RAM-tier match would be fabricated from an SSD reuse.** The measurement would not be wrong by a
margin; it would name a tier that did not supply the state, and its prefix would come from a candidate
set that did not contain the state that was used. That is not a precision problem that a bigger sample
fixes: it is a wrong attribution of where the reused state came from.

### 1.5 The decision

The SSD-tier measurement qualification is **deferred**. The tier is therefore **disabled** in the initial
deployment profile (`--conversation-spill-mib 0`, `engine/src/program/generate.cpp:14070`), so that no
qualified measurement can ever come out of the SSD path.

No fabrication was performed: no RAM-tier match is derived from an SSD reuse anywhere in this ACT. The
defect is **recorded**, not fixed: fixing it would mean either a new `Source` name (a change to the
telemetry contract, which is frozen) or a second accounting of the same decision (a parallel
implementation of the cache diagnostics' own walk, which the ACT's own design forbids -
`engine/src/program/generate.cpp:13903`-`:13908`).

## 2. The slot-read optimization: the evidence is absent, not correlated

### 2.1 What the source does

The slot-read fast path is a separate branch in the engine's request loop. It reads a conversation's next
turn into an idle slot and prints its own answer line:

```cpp
// engine/src/program/generate.cpp:19657
std::printf("DONE 0 %lld %.1f 0.0 length 0 0 %lld 0 0 0 0 0.0 %lld 0 chunk=0 experts_streamed=0\n",
            (long long) n, set_ms, (long long) rd_from, (long long) (n - rd_from));
std::printf("BADM %d 1\n", b);
```

The **normal** path appends the telemetry suffix to its `DONE` line:

```cpp
// engine/src/program/generate.cpp:23901
const std::string tele_txt = tele_on ? strata::program::reqtelemetry::encode(tele) : std::string();
std::printf("DONE %lld %lld %.1f %.1f %s ... chunk=%lld experts_streamed=%lld%s\n",
            ..., tele_txt.c_str());
```

The fast path's line carries `chunk=0 experts_streamed=0` and **no** `tele_txt`: the encoder is never
called on that path.

### 2.2 The consequence, stated plainly

The fast path's `DONE` line is an **admission's** answer, not a request's own measured answer, and it
carries **no** `rid=`, no `cache_source=`, no `cache_reason=` and no token accounting. The server's parser
(`terminal/serve/server.py:1588`) reads the `key=value` fields after the positional ones, so a line
without them yields a telemetry figure set with **no** key in it.

The server's own correlation treats an absent figure as **unavailable**, not as zero
(`terminal/serve/reqtelemetry/correlation.py:341`-`:347`: `figures.get("cache_source", "")` maps an absent
key to `SOURCE_UNKNOWN`, and the durations stay `None`). So the evidence is **explicitly unavailable**.

It is *not* wrongly correlated: the `rid=` is absent, so the figures cannot be attached to another
request's receipt - the correlation is keyed on the `rid`, and a receipt without one is not applied
(`terminal/serve/reqtelemetry/correlation.py:120`-`:145`, the `rid` is part of the terminal evidence, and a
foreign id is a conflict, not an application).

### 2.3 The decision

The slot-read optimization is **disabled** for the initial native measurements (`STRATA_SLOT_READ` unset,
which the engine's own rule at `engine/src/program/generate.cpp:16230` reads as off). The defect is
**recorded**: the fast path bypasses the normal encoder, and a caller that wanted the fast path's
measurements would have to add the suffix there - a change to the engine's measurement surface, which
this ACT does not make.

## 3. Replica routing: the identity is delegated before the target is known

### 3.1 What the source does

The replica engine routes a request to one of several engines
(`terminal/serve/replicas.py:529`, `ReplicaEngine.route`). The routing decides **which** engine gets the
request, from the prompt's tokens and the engines' loads.

The server sets the invocation identity on the engine **before** the dispatch:

```python
# terminal/serve/server.py:7648
if hasattr(self.engine, "set_request_id"):
    self.engine.set_request_id(invocation_id)
gen = self.engine.generate(prompt, max_new - n, pass_sampling, cancel, embeddings=emb) if emb \
    else self.engine.generate(prompt, max_new - n, pass_sampling, cancel)
```

`StrataEngine` has that method (`terminal/serve/server.py:1805`). **`ReplicaEngine` does not**: the file
has no `set_request_id` and no `request_id` at all. The `hasattr` guard therefore skips it, and the `rid=`
never reaches any replica's engine.

### 3.2 The consequence, stated plainly

Both the predecessor's and the integrated `ReplicaEngine` delegate the request's identity to a **child**
before the routing decides the **actual** dispatch target. The identity is set on the replica wrapper, and
the wrapper - not the engine that actually answers - is what would have to carry it. With no
`set_request_id` on the wrapper, the `rid=` is **absent** from every replica's `DONE` line.

An absent `rid=` means the server cannot bind the native figures to the invocation that produced them. The
figures are therefore **explicitly unavailable** (the correlation's `rid` is `None`), not wrongly
correlated.

### 3.3 The inherited character of the debt

The file is **byte-identical to the pinned upstream's**:

```text
$ git show 42e489d145aaf4430b54f2c58679be27d45faf17:terminal/serve/replicas.py | sha256sum
a4ddf8089ccfb75a0ebf49b3865df8fbc73455834547be2a3b64b7b8b6840038  -
$ git show HEAD:terminal/serve/replicas.py | sha256sum
a4ddf8089ccfb75a0ebf49b3865df8fbc73455834547be2a3b64b7b8b6840038  -
```

The upstream itself has no `set_request_id` on the replica engine. This is **inherited technical debt**, not
a defect the merge introduced.

### 3.4 The decision

**Replica routing is not redesigned in this ACT.** The limitation is **recorded**, and the replicas are
kept **outside the qualified telemetry envelope**: the initial envelope runs **one engine per GPU host**, so
no replica group is built at all.

## 4. Split serving and the additional engines

The split engine (`terminal/serve/split.py`) hands the session from a prefill engine to a decode engine in
RAM, and the additional engines (`strata-poly`, `strata-glm`, `strata-hy4`, `strata-inkling`) are separate
executables with their own programs. Neither has an invocation correlation with the request's own `DONE`
line, and neither has a native measurement authority for the cache decision.

**No claim of complete native telemetry support is made for them.** Their measurements are published as
**unavailable**, never as zero - the rule the merged telemetry already follows
(`terminal/serve/reqtelemetry/correlation.py:341`-`:353`, and the store's own rule that an unavailable
duration is not observed: `terminal/serve/reqtelemetry/store.py:803`).

They are excluded from the initial envelope (`--split-serve` not passed, `terminal/serve/server.py:11178`).

## 5. The summary

```yaml
SSD_CACHE_TELEMETRY: DEFERRED - an SSD-restored image is reported with a RAM-tier source name and
                    a RAM-derived matched prefix; the tier is DISABLED in the initial profile
                    (--conversation-spill-mib 0), so no qualified measurement comes out of it.
                    No RAM-tier match is fabricated from an SSD reuse.
SLOT_READ_TELEMETRY: UNAVAILABLE - the fast path's DONE line carries no telemetry suffix at all;
                    the evidence is absent, not correlated, and the server reports it as unavailable.
                    The optimization is DISABLED for the initial native measurements.
REPLICA_TELEMETRY: UNAVAILABLE - the rid= never reaches a replica's engine (ReplicaEngine has no
                    set_request_id, and the file is byte-identical to upstream's: inherited debt).
                    NOT REDESIGNED in this ACT; the replicas are outside the qualified envelope.
SPLIT_SERVING_TELEMETRY: UNAVAILABLE - no invocation correlation and no native measurement authority;
                    published as unavailable, never as zero. Excluded from the initial envelope.
```

**No new instrumentation framework was added.** The findings are recorded from the candidate's own source,
and the paths are held outside the qualified envelope until they are qualified on their own.
