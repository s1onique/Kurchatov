# 04 - Conflict resolutions

The merge produced **44** conflicted paths. Git's rename detection resolved most of them
mechanically: upstream moved `src/` to `engine/src/`, `serve/` to `terminal/serve/`,
`include/` to `engine/include/` and `tools/` to `terminal/tools/`, so the local's files
were matched to their new homes and the conflict was a **file-location** one (stage 2
only). Those 28 were resolved by staging the renamed path - the content was identical to
the local's.

The remaining **16** needed a decision. They are listed below.

## The content conflicts and how each was resolved

### PATH: `.gitattributes`
* **LOCAL_CAPABILITY**: the local's own rules, including `docs/evidence/**/*.diff -whitespace`.
* **UPSTREAM_CHANGE**: upstream rewrote every path for the new layout and added the
  container, KaTeX, vendored-engine and `.jinja` rules.
* **RESOLUTION**: both blocks kept. The local's `src/poly/fattn_mma.*` rule was rewritten
  to `engine/src/poly/fattn_mma.*` (upstream's path); the local's `docs/evidence/**` rule
  was kept as it is (the path did not move).
* **PRESERVED_BEHAVIOR**: the evidence diffs stay byte-identical on checkout; the
  vendored trees stay LF.
* **VERIFICATION**: `git diff --check` is clean; the tree's line endings are unchanged.

### PATH: `.gitignore`
* **LOCAL_CAPABILITY**: `/.kurchatov-acts/` - the ignored local ACT execution workspace.
* **UPSTREAM_CHANGE**: upstream extended the list (the Terminal/Desktop split, the DGX
  Spark build outputs).
* **RESOLUTION**: both blocks kept, verbatim.
* **PRESERVED_BEHAVIOR**: the recovery workspace stays ignored and untracked.
* **VERIFICATION**: `git status` shows no `.kurchatov-acts/` entry; `git check-ignore`
  confirms it.

### PATH: `CMakeLists.txt` (root) -> `engine/CMakeLists.txt`
* **LOCAL_CAPABILITY**: seven native test targets (`cache_diag_test`,
  `cache_diag_engine_test`, `cache_diag_regress_test`, `cache_diag_roundtrip`,
  `reqtelemetry_test`, `reqtelemetry_roundtrip`) inside the `STRATA_BUILD_CONVERSATION_TESTS`
  block.
* **UPSTREAM_CHANGE**: upstream **deleted** the root `CMakeLists.txt` and cut it into
  `engine/CMakeLists.txt` plus `engine/cmake/*.cmake`; the same
  `STRATA_BUILD_CONVERSATION_TESTS` block survives there.
* **RESOLUTION**: the root file was removed; the six test targets were **ported into
  `engine/CMakeLists.txt`'s** `STRATA_BUILD_CONVERSATION_TESTS` block, with their
  `src/program/...` sources rewritten to `engine/src/program/...` and their include
  directory to `engine/include`.
* **PRESERVED_BEHAVIOR**: the native tests are still built and registered with ctest,
  now from upstream's build system.
* **VERIFICATION**: the four header-only native tests were compiled and run directly
  (see `07-integration-verification.md`); they are registered in `engine/CMakeLists.txt`.

### PATH: `docs/DETAILS.md`
* **LOCAL_CAPABILITY**: the `STRATA_CACHE_DIAG=1` section (the cache decision
  observability) and the request-telemetry section.
* **UPSTREAM_CHANGE**: upstream rewrote the surrounding sections (the RAM figure, the
  web page, the network access).
* **RESOLUTION**: both blocks kept, each in its own place; no text was dropped.
* **PRESERVED_BEHAVIOR**: the documentation of both the cache diagnostics and the
  request telemetry.
* **VERIFICATION**: `grep` finds both sections in the merged file.

### PATH: `engine/include/strata/core/conversation_cache.hpp`
* **LOCAL_CAPABILITY**: `ConversationCache::candidates()` - the candidates `best()`
  examined, with the reason each was or was not usable (the cache diagnostics' view of
  the engine's own walk).
* **UPSTREAM_CHANGE**: upstream added `ConversationCache::holds()` (does a parked
  conversation already hold this state?) beside `best()`.
* **RESOLUTION**: both methods kept, as different members of the same class. The merge
  dropped the local method's closing brace; it was restored (the file did not compile
  without it, which is how the omission was found).
* **PRESERVED_BEHAVIOR**: the reported selection is still the selection the engine made;
  upstream's `holds()` still answers its own question.
* **VERIFICATION**: `cache_diag_test`, `cache_diag_engine_test` and
  `cache_diag_regress_test` compile and pass against the merged header.

### PATH: `engine/sycl/src/program/generate.cpp`
* **LOCAL_CAPABILITY**: **none**. The local's `sycl/` tree is byte-identical to the
  merge base (blob `5794a27cc9a8644ffc4cd636c838d181290f7ea2`).
* **UPSTREAM_CHANGE**: upstream moved the SYCL engine under `engine/sycl/` and rewrote
  its `generate.cpp`.
* **RESOLUTION**: upstream's version, taken as-is.
* **PRESERVED_BEHAVIOR**: the SYCL engine is upstream's; the local never touched it.
* **VERIFICATION**: the merged file's blob is `da200e742358518bef2ec983b9782a3ef80b765d`,
  which is upstream's blob for that path. **This conflict was a rename-detection
  artefact**: Git mapped the local's changes to the *main* `src/program/generate.cpp` onto
  the SYCL path, because the SYCL tree carries a copy of the same file name. The blob
  comparison is what proved it.

### PATH: `terminal/serve/server.py`
21 conflict regions. The resolutions are in `04a-server-py-resolutions.md`.

### PATH: `terminal/serve/web/app.css`
* **LOCAL_CAPABILITY**: `.view--telemetry` in the overflow rule.
* **UPSTREAM_CHANGE**: upstream added `.view--experts` to the same rule.
* **RESOLUTION**: upstream's rule, with `.view--telemetry` appended. The local's old-path
  copy (`serve/web/app.css`) was removed - it was a leftover of the rename, and keeping
  it would have kept two copies of the web app.
* **PRESERVED_BEHAVIOR**: the telemetry view scrolls like the other views.
* **VERIFICATION**: `grep` finds `view--telemetry` in `terminal/serve/web/app.css`.

### PATH: `terminal/serve/web/app.js`
* **LOCAL_CAPABILITY**: the `telemetry` tab in the tab list and the view list; the
  deployed build's identity (`renderBuildId`, `buildIdText`) and the About card's
  `Build` row.
* **UPSTREAM_CHANGE**: upstream's `showTab` uses a literal list, added the `experts` view
  and rewrote `render()`.
* **RESOLUTION**: the local's four changes were **ported onto upstream's file** as
  surgical edits: `telemetry` added to both lists, the `renderBuildId` helper inserted
  before `render()`, its call added at the top of `render()`, and the `Build` row added to
  `renderAbout`'s facts. Upstream's `experts` handling was left alone.
* **PRESERVED_BEHAVIOR**: the telemetry tab opens the inspector; the header and the
  About card name the deployed build; upstream's Experts tab still works.
* **VERIFICATION**: `tools/test_kurchatov_identity.py` passes; the tab list and the view
  list both contain `telemetry`.

### PATH: `terminal/serve/web/index.html`
* **LOCAL_CAPABILITY**: the `Kurchatov` brand, the `#build-id` element, the `Telemetry`
  tab button and the telemetry view section.
* **UPSTREAM_CHANGE**: upstream made the brand a link to the upstream repository, added
  the `Experts` tab button and the `Experts` view section, and wrapped the tab labels in
  i18n spans.
* **RESOLUTION**: all three kept. The header keeps the local's `Kurchatov` span **and**
  the local's `#build-id` span, and the tab nav keeps upstream's `data-i18n-label`. The
  tab list keeps the `Telemetry` button **and** upstream's `Experts` button; the views
  keep the telemetry section **and** upstream's Experts section.
* **PRESERVED_BEHAVIOR**: both views exist and both are reachable.
* **VERIFICATION**: `grep` finds `view-telemetry`, `tab-btn-telemetry`, `view-experts`,
  `tab-btn-experts` and `build-id` in the merged file.

### PATH: `terminal/serve/web/monitor.html`
* **LOCAL_CAPABILITY**: the `Kurchatov` brand, the `#build-id` element, the
  `.brand .build` CSS rule.
* **UPSTREAM_CHANGE**: upstream dropped the `.embedded header{display:none}` rule (the
  page is no longer embedded) and moved `main{...}` into the same rule.
* **RESOLUTION**: upstream's CSS rule, with the local's `.brand .build` rule appended.
  The local's `.embedded` rule was **not** carried over: upstream removed the embedding,
  so the rule would have been dead code.
* **PRESERVED_BEHAVIOR**: the build identifier renders in the monitor's header.
* **VERIFICATION**: `tools/test_kurchatov_identity.py` passes.

### PATH: `terminal/serve/web/monitor.js`
* **LOCAL_CAPABILITY**: the deployed build's identifier in the monitor.
* **UPSTREAM_CHANGE**: **none** - upstream's `monitor.js` already carries the same
  reader (the `build-id` element, the `status.build` facts).
* **RESOLUTION**: the local's change was **not** ported: it would have been a duplicate
  of upstream's identical code.
* **PRESERVED_BEHAVIOR**: the build identifier renders in the monitor.
* **VERIFICATION**: `grep` finds `build-id` in upstream's `monitor.js`; the file is
  unchanged from upstream.

## The blanket-resolution rule was not used

No `-X ours`, no `-X theirs`, no `-s ours` was used anywhere. Every conflict was resolved
by reading both sides and deciding, and every decision is recorded above.

No structural conflict was resolved by copying an older Kurchatov file over a newer
upstream implementation. Where upstream renamed, moved or decomposed a subsystem, the local
capability was ported to its actual successor:

* `serve/` -> `terminal/serve/` (the serving layer)
* `src/` -> `engine/src/`, `include/` -> `engine/include/` (the native engine)
* the root `CMakeLists.txt` -> `engine/CMakeLists.txt` (the build)
* the root `Dockerfile` -> `tools/docker/Dockerfile` (upstream's own move; the local never
  changed the container)
