# 09 - The performance parity (W8)

## NOT_EXECUTED

**No performance measurement was taken, because there is no GPU on this host.**

| | |
|---|---|
| the host | macOS (Darwin), no CUDA toolkit, no GPU |
| what W8 asks for | two arms (the telemetry off, the telemetry on), the same model, the same build, the same hardware, the same sampling, the same cache configuration and the same request sequence, measured over 1K/8K/32K/80K prompts |
| what was possible here | the Python side's own cost, measured without a model |

Nothing in this document claims a threshold was met. The targets (`median prefill regression <= 2%`, `median
decode regression <= 2%`) are **not** claimed to hold; they are unmeasured.

## What the design says about the overhead, and why it is bounded

This is a design argument, **not** a measurement.

| The requirement | How the implementation meets it |
|---|---|
| no per-token JSON serialization | the engine writes the telemetry **once**, on the DONE line. Nothing is serialized per token. |
| no GPU synchronization | the engine's timings are the ones it already keeps (`prompt_ms`, `decode_ms`) plus two `Clock::now()` calls per request. **No stream synchronization is added**: the prefill and the decode times are the engine's existing figures, not new ones taken around a sync. |
| no filesystem I/O on the hot path | the evidence log is written by a background thread. The token path never touches the disk. |
| no unnecessary hot-path allocations | the telemetry's per-request state is a fixed-size struct (`RequestTelemetry`): a handful of scalars and two short strings. No per-token allocation. |
| no unbounded CPU-side growth | the store is bounded by a record count **and** a byte budget; the evidence queue is bounded. |
| no new persistent GPU allocations | the telemetry allocates **nothing** on the device: it is host-side bookkeeping. |

The engine's extra work with the telemetry on is:

1. the **cache candidate analysis** - the same comparison the `STRATA_CACHE_DIAG` diagnostics already do, and
   only once per request (not per token);
2. two `Clock::now()` calls per request;
3. the DONE line grows by a few dozen bytes.

With the telemetry **off** (`STRATA_TELEMETRY=0`), the engine's behaviour is byte-identical to the release's: the
collector is not filled and the DONE line carries nothing extra. That is the switch's own test
(`reqtelemetry_test`'s `switch_on` checks and the writer's `encode`).

## What would execute it

On a Linux/CUDA machine with the engine built:

```
# arm A: the telemetry off
STRATA_TELEMETRY=0 ./strata --serve ... (the same model, the same args)
# arm B: the telemetry on
STRATA_TELEMETRY=1 ./strata --serve ... (the same model, the same args)
```

the same request sequence at 1K, 8K, 32K and 80K tokens, the same sampling (a fixed seed), the same cache
configuration, the same warm-up, and the paired observations compared on the median and the dispersion. The
measurements to take: the cold and the warm prefill throughput, the decode throughput, the TTFT, the request's
wall time, the process RSS, the GPU memory, the CPU utilization and the telemetry's own retention memory.

**That work is not done here, and this ACT does not claim it.**
