# 01 - Source identities

The three immutable source authorities of the integration:

```text
BASE    = 3e1642161198c50ff1abed4046f4e4f476099dbb   (the common ancestor)
LOCAL   = 7ad7c531dc8f7d00bd483d9baa1270a58bf2ba06   (the Kurchatov entry head)
UPSTREAM= 42e489d145aaf4430b54f2c58679be27d45faf17   (the pinned PolyStrata head)
```

| Identity | Value | How it was established |
|---|---|---|
| The Kurchatov entry head | `7ad7c531dc8f7d00bd483d9baa1270a58bf2ba06` | `git rev-parse HEAD` at the operator's checkout, before any mutation |
| `origin/main` at entry | `7ad7c531dc8f7d00bd483d9baa1270a58bf2ba06` | `git rev-parse origin/main` - identical to the entry head |
| The pinned upstream head | `42e489d145aaf4430b54f2c58679be27d45faf17` | `git cat-file -t` after the fetch; the revision was **absent** before the fetch and was resolved independently of the upstream tip |
| The upstream tip at fetch time | `42e489d145aaf4430b54f2c58679be27d45faf17` | `git rev-parse upstream/main` - **the tip IS the pin: no drift** |
| The common ancestor | `3e1642161198c50ff1abed4046f4e4f476099dbb` | `git merge-base` - "Merge the engine work for 0.1.45-poly.10" |
| The ancestor is an ancestor of the entry head | yes | `git merge-base --is-ancestor` |
| The candidate | `74e89653e98d855d292c373075a5f1978df56a23` | the merge commit, with the two parents above |

## The divergence

| Measure | Value |
|---|---|
| `LEFT_ONLY_COMMITS` (the Kurchatov side, `UPSTREAM..LOCAL`) | 71 |
| `RIGHT_ONLY_COMMITS` (the upstream side, `BASE..UPSTREAM`) | 6911 |
| The commits the two sides share | the whole history up to `3e164216` |

## The machine-readable inventories

The inventories the ACT asks for were generated and are referenced by name:

| Inventory | Path | Content |
|---|---|---|
| the local's changes against the base | `git diff --name-status BASE LOCAL` | 159 paths |
| upstream's changes against the base | `git diff --name-status BASE UPSTREAM` | 8 029 paths |
| the local's diffstat against the base | `git diff --stat BASE LOCAL` | 159 paths |
| upstream's diffstat against the base | `git diff --stat BASE UPSTREAM` | 8 030 paths |
| the candidate against upstream | `git diff --stat UPSTREAM LOCAL` | 8 174 paths before the merge; the candidate's own delta is in `02-divergence-inventory.md` |
| the local's commit list | `git log --oneline BASE..LOCAL` | 71 commits |
| the upstream's commit count | `git rev-list --count BASE..UPSTREAM` | 6911 |

These were produced with `git diff --renameLimit` raised, because the upstream side
renames so much that the default limit skips the exhaustive rename detection.

## The upstream's structural change (the summary)

Upstream moved almost everything. The candidate's tree is upstream's layout with the
Kurchatov capabilities in it:

| Before (the Kurchatov entry revision) | After (the candidate) |
|---|---|
| `src/` | `engine/src/` |
| `include/strata/` | `engine/include/strata/` |
| `serve/` | `terminal/serve/` |
| `setup.py` (root) | `terminal/setup.py` |
| `CMakeLists.txt` (root, 163 kB) | `engine/CMakeLists.txt` + `engine/cmake/*.cmake` |
| `Dockerfile` (root) | `tools/docker/Dockerfile` |
| `tools/` (mostly) | `terminal/tools/` (the engine's tools stay at the root `tools/`) |
| `tests/` | `engine/tests/` + `terminal/tests/` |
| `bench/` | `terminal/bench/` + `docs/bench-results/` |
| `docs/` | `docs/` (upstream's own; the local's evidence directories stay) |
