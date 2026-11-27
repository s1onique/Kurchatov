# 02 - Divergence inventory

The candidate's delta against the pinned upstream revision: the **surviving Kurchatov
capability delta**, which is what a reviewer needs to read.  The upstream's own
8 000-path change against the old Kurchatov revision is the reverse direction and is NOT
reproduced here: it is upstream's history, not this ACT's work.

```
165 files changed, 44915 insertions(+), 65 deletions(-)
150 added, 15 modified
```

## The complete delta, by area

| Area | Files | What it is |
|---|---|---|
| `docs/evidence/` | 98 | the historical evidence packages of the telemetry ACTs (preserved byte for byte) |
| `terminal/serve/` | 34 | the request-causal telemetry: the 11 `reqtelemetry/` modules, the 10 test modules, the web inspector (3 files + the tab wiring) |
| `engine/src/program/` | 7 | the native half: the cache diagnostics' 4 programs and the telemetry's 2 programs, plus the ported `generate.cpp` |
| `engine/include/strata/` | 3 | the native headers: `cache_diag.hpp`, `reqtelemetry.hpp`, and `conversation_cache.hpp` (the `candidates()` method beside upstream's `holds()`) |
| `engine/CMakeLists.txt` | 1 | the six ported native test targets |
| `tools/` | 14 | the mutation witnesses and the tools-level witnesses (the paths adapted to the new tree) |
| `docs/telemetry/` | 2 | the schema files of the historical contracts (`strata-request-telemetry-2.schema.json`, `-3.schema.json`) |
| `docs/forensics/` | 2 | the cache observability's and the CUDA validation's forensics reports |
| `docs/TELEMETRY.md`, `docs/DETAILS.md` | 2 | the documentation of the request telemetry and of the cache diagnostics |
| `.gitattributes`, `.gitignore` | 2 | the merged rules (both sides kept) |

## The complete file list

The full machine-readable list is the `git diff --name-status` against the pinned
revision. The compact form, by path:

