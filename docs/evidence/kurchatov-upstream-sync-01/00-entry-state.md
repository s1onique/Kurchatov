# 00 - Entry state

ACT: **ACT-KURCHATOV-UPSTREAM-SYNC-01**

## Repository identity

| Field | Value |
|---|---|
| Repository | `s1onique/Kurchatov` (origin) |
| Upstream | `https://github.com/simplexai-labs/PolyStrata.git` (upstream remote, pre-existing) |
| Working tree | `/Volumes/UserData/Users/chistyakov/Projects/SPbNIX/Kurchatov` |
| Branch at entry | `main` |
| HEAD at entry | `7ad7c531dc8f7d00bd483d9baa1270a58bf2ba06` |
| `origin/main` at entry | `7ad7c531dc8f7d00bd483d9baa1270a58bf2ba06` (identical) |
| Tracked dirt | none (`git status` clean) |
| Untracked files | none in the tracked tree |
| Stashes | none |
| Worktrees at entry | one (the operator's own `main` checkout) |
| Local branches | `main`, `act/strata-cache-cuda-validation-02`, `act/strata-cache-observability-01` |
| Tags | 21 (`v0.1.41-poly.1` .. `v0.1.45-poly.10`) |

## Expected vs observed inputs

Every expected input in the ACT's authority block matched the repository exactly.
No discrepancy was found, so the integration proceeded without a report-and-stop.

| Field | Expected | Observed | Match |
|---|---|---|---|
| `KURCHATOV_HEAD` | `7ad7c531dc8f7d00bd483d9baa1270a58bf2ba06` | `7ad7c531dc8f7d00bd483d9baa1270a58bf2ba06` | yes |
| `ORIGIN_MAIN_HEAD` | (the entry head) | `7ad7c531dc8f7d00bd483d9baa1270a58bf2ba06` | yes |
| `PINNED_UPSTREAM_HEAD` | `42e489d145aaf4430b54f2c58679be27d45faf17` | `42e489d145aaf4430b54f2c58679be27d45faf17` | yes |
| `UPSTREAM_CURRENT_HEAD` | - | `42e489d145aaf4430b54f2c58679be27d45faf17` | (the pin IS the tip: **no drift**) |
| `MERGE_BASE` | `3e1642161198c50ff1abed4046f4e4f476099dbb` | `3e1642161198c50ff1abed4046f4e4f476099dbb` | yes |
| `LEFT_ONLY_COMMITS` | 71 | 71 | yes |
| `RIGHT_ONLY_COMMITS` | 6911 | 6911 | yes |

The merge base `3e1642161198c50ff1abed4046f4e4f476099dbb` ("Merge the engine work for
0.1.45-poly.10") is an ancestor of the entry head, and the pinned upstream revision was
absent from the local object store before the fetch (it was resolved independently of the
upstream tip, and the tip turned out to be the same revision).

## Recovery

| Artifact | Where | Verified |
|---|---|---|
| Recovery ref | `refs/heads/act/kurchatov-upstream-sync-01-recovery/entry` | `git rev-parse` -> the entry head |
| Recovery bundle | `/tmp/kurchatov-recovery-bundles/ACT-KURCHATOV-UPSTREAM-SYNC-01-ENTRY.bundle` | `git bundle verify` -> "is okay ... The bundle records a complete history" |

Bundle SHA-256: `46a77c025aa8381d35451e2cd447eca2bbe4eb7385a3db5c2f3a58712a346d5f`
(size 38 245 499 bytes; head `7ad7c531dc8f7d00bd483d9baa1270a58bf2ba06`).

The bundle lives **outside** the repository. The historical infrastructure recovery
workspace `.kurchatov-acts/` was **not** used, modified, pruned, relocated or incorporated
into Git: it stays ignored (`.gitignore` line `/.kurchatov-acts/`) and untouched.

## Worktrees created (all inside the repository's own `.act-worktrees/`)

| Worktree | Revision | Purpose |
|---|---|---|
| `.act-worktrees/kurchatov-original` | `7ad7c531dc8f7d00bd483d9baa1270a58bf2ba06` (detached) | the local baseline |
| `.act-worktrees/polystrata-upstream` | `42e489d145aaf4430b54f2c58679be27d45faf17` (detached) | the upstream baseline |
| `.act-worktrees/kurchatov-integration` | branch `act/kurchatov-upstream-sync-01` | the integration candidate |

The operator's own `main` checkout was never altered by the merge: the merge ran inside
the integration worktree.

## Authorization honoured

* Upstream integration: authorized.
* Local commits: authorized.
* Main mutation, force push, remote push, production deployment, production engine
  restart: **not** performed.
* No new telemetry feature was developed; no unrelated refactoring was done.
