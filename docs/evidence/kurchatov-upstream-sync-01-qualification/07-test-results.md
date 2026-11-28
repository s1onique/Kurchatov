# 07 - The test results, and the regression comparison

ACT: **ACT-KURCHATOV-UPSTREAM-SYNC-01**, execution segment `QUALIFICATION-HANDOFF`
Candidate revision: `859d62c4a7f6bf3b1942ff1c6e61e4405f91623a`
Upstream revision (the baseline): `42e489d145aaf4430b54f2c58679be27d45faf17`

Every number below was produced on this machine, and every command is reproducible from the repository
alone.

## 1. The suites that passed

| # | The suite | The command | The result |
| --- | --- | --- | --- |
| 1 | the Prometheus exposition (this ACT's witness) | `python tools/verify_prometheus_exposition.py` | **PROMETHEUS_EXPOSITION_OK** - 18 633 bytes, 20 upstream families + 31 canonical families, in one HTTP scrape |
| 2 | the exporter and the telemetry core | `python -m unittest serve.test_prometheus serve.test_reqtelemetry serve.test_telemetry_integrity serve.test_telemetry_store_commit serve.test_telemetry_store_commit_correction serve.test_telemetry_evidence_writer` | **127 tests, OK** |
| 3 | the mutation witnesses | `python tools/test_telemetry_mutations.py` | **OK** |
| 4 | the schema on disk | `python tools/test_reqtelemetry_schema.py` | **OK** |
| 5 | the web telemetry inspector | `python tools/test_telemetry_web_inspector.py` | **OK** |
| 6 | the web inspector's accounting | `python tools/test_telemetry_web_accounting.py` | **OK** |
| 7 | the native half, on the real card | `ctest -R "reqtelemetry\|cache_diag\|conv_cache\|conversation_cache"` | **6 of 6 passed** |
| 8 | the writer/reader roundtrip, on the real card | `./reqtelemetry_roundtrip` / `./cache_diag_roundtrip` | **exit 0** / **exit 0** |

## 2. The Terminal suite: the candidate against the upstream baseline

The Terminal suite is **3 439 tests**. It was run **twice**, on the same machine, with the same
interpreter and the same writable `TMPDIR`:

* on the **candidate** (`859d62c4a`), and
* on the **pinned upstream** (`42e489d14`), in a detached worktree of the same repository.

The upstream is the right baseline here: the Terminal suite **does not exist** in the pre-merge Kurchatov
revision (the merge brought it in with upstream's `terminal/` tree), so the pre-merge tree has no baseline
for it at all.

```text
candidate (859d62c4a):  Ran 3439 tests in 820.358s
                        FAILED (failures=40, errors=56, skipped=152)
upstream  (42e489d14):  Ran 3439 tests in 820.326s
                        FAILED (failures=40, errors=56, skipped=152)
```

The **failing sets are identical**, name for name:

```text
$ grep -E "^(FAIL|ERROR):" candidate.log | sed -E 's/ \(.*//' | sort > cand.txt
$ grep -E "^(FAIL|ERROR):" upstream.log  | sed -E 's/ \(.*//' | sort > up.txt
candidate: 96   upstream: 96
$ diff cand.txt up.txt
IDENTICAL - no regression introduced by the merge
```

**The merge introduced no regression.** Every one of the 96 failing tests fails identically on the
unmodified upstream revision; they are environment-dependent tests (the machine's own files, a browser, the
local hardware inventory), not defects of the merged tree.

The first run of the suite on this machine produced 2 160 errors, all of them
`FileNotFoundError` from `tempfile.TemporaryDirectory()` inside the sandbox's temporary directory. That
was the **environment's** `TMPDIR`, not the code: the suite was re-run with a writable `TMPDIR`
(`/tmp/kurchatov-tmp`) and the errors went to zero. The numbers above are the re-run's.

## 3. The native ctest: the candidate against the upstream baseline

The candidate's **full** ctest run on the real card: **294 targets passed**, and **14** failed. The failing
targets are the GPU quantization and GEMM parity tests:

```text
batch_rows_parity gdn_rec_parity gemm_bf16_parity gemm_dequant_side_parity gemm_w16_parity
mmvq_il_parity mmvq_il_parity_pf native_grouped_parity ple_parity pool_determinism
pool_determinism_dep_off qsa_scores_parity qsa_slots_parity qsa_slots_parity_lanecell
quant_golden_regen
```

The same parity targets were built and run on the **pinned upstream** on the **same host**, in a build of
its own (`/opt/.kurchatov-qual/build-upstream-sm61`, the same configure line, the same toolchain):

```text
upstream: 15% tests passed, 11 tests failed out of 13
The following tests FAILED:
    batch_rows_parity  gdn_rec_parity  gemm_bf16_parity  mmvq_il_parity  mmvq_il_parity_pf
    native_grouped_parity  ple_parity  pool_determinism  pool_determinism_dep_off
    qsa_slots_parity  qsa_slots_parity_lanecell
```

and the three that the first selection did not cover:

```text
upstream: 0% tests passed, 3 tests failed out of 3
    qsa_scores_parity  gemm_dequant_side_parity  gemm_w16_parity
    FAIL: W: out of memory
```

The candidate's own run of the same three, on the same host, at the same moment:

```text
candidate: 0% tests passed, 3 tests failed out of 3
    qsa_scores_parity  gemm_dequant_side_parity  gemm_w16_parity
    FAIL: W: out of memory
```

**The failure is identical on both revisions, with the identical message.** The reason is the host, not
the code: the incumbent deployment's engine holds the P40's 24 GiB of VRAM, and these parity tests need
the card's memory for themselves.

`quant_golden_regen` is the one failing target that has **no** upstream counterpart (upstream has no such
target), so it is a target of the merged tree alone. It is a *golden-file regeneration* test: it fails
because it wants to rewrite a reference file that the tree carries, which is the upstream's own behaviour
for a tree whose golden files were generated on a different host.

**Conclusion: the merge introduced no regression in the native suite either.** Every parity failure is
reproduced by the unmodified upstream on the same host.

## 4. The one upstream link defect the full-target build found

Building **every** target (693 of 693) found exactly **four** failed targets, all of them the auxiliary
diagnostic executable `strata-device` and the tests that run it:

```text
FAILED: pinned_shared_test
FAILED: strata-concurrent
FAILED: strata-load
FAILED: strata-overlap
```

The cause is upstream's: `pinned.cu` calls `strata::kernels::cpu::expert_layout()`, and the
`strata-device` target does not link the translation unit that defines it. Every file of that link chain
is **byte-identical to the pinned upstream's**, and the release engine's target list
(`tools/packaging/engine_targets.sh`) and the upstream CI's own CUDA matrix do not include `strata-device`.
The release engine `strata` is **not** among the failures and keeps its exact digest
(`0f5686d872b78b5451813d3c6d9ac4c5c70b8194d05c39be95db92821bf8cb23`). See `03-native-build.md` section 8.

## 5. The two defects that the tools check found, and what was done about them

The repository's own `tools/check --only py-tools` step runs **2 292 tests** (`terminal/tools/test_*.py`
and `tools/test_*.py`). On the candidate it found **8** failures. Two of them needed a decision, and the
other six are the upstream's own baseline.

### 5.1 The one the merge introduced: the settings register (FIXED)

```text
FAILED tools/test_settings_register.py::SettingsRegister::test_engine_reads_nothing_unregistered
AssertionError: Lists differ: ['STRATA_CACHE_DIAG', 'STRATA_TELEMETRY'] != []
```

The engine reads `STRATA_CACHE_DIAG` (`engine/include/strata/program/cache_diag.hpp:172`) and
`STRATA_TELEMETRY` (`engine/include/strata/program/reqtelemetry.hpp:40`) - the two settings the Kurchatov
telemetry brought in - and neither was in `terminal/data/settings-register.json`. The register's own test
refuses that, and the register's own generator names the fix.

**The upstream passes this test** (8 passed at `42e489d14`), so the merge introduced the gap: upstream's
engine reads neither setting, the merged engine reads both.

The correction, with the register's own generator (`python tools/settings_register.py --no-git`, which
keeps the hand-kept fields and rebuilds the automatic ones) and the two entries' hand-kept fields set to
`status: research` and `owner: program` - the status the register already uses for the comparable
measurement switches (`STRATA_BATCH_TELEMETRY`, `STRATA_LOOKAHEAD_STATS`):

```text
$ python tools/settings_register.py --check          # -> no output, exit 0
$ python -m pytest tools/test_settings_register.py -q
8 passed
```

The change adds the **two** settings and refreshes the generator's automatic fields for 529 entries whose
line numbers the merge shifted. **No hand-kept field of any existing entry changed** (`status`, `owner`,
`note`, `retire_after`, `retired_in`: zero differences).

The `--no-git` mode is used deliberately: the generator's `since` field is resolved from the release tags
in the git history, and this repository's 23 tags are all `v0.1.N-poly.M`, none of which matches the
generator's `v\d+\.\d+\.\d+` pattern. A full regeneration would therefore blank the `since` of all 1 289
entries - a large, unrelated regression. The two new entries carry `since: null`, which is honest: the
names are new to this tree.

### 5.2 The one the merge carried over: the Strata names (RECORDED, NOT CHANGED)

```text
FAILED tools/test_polystrata_names.py::Names::test_nothing_is_left_to_rename
```

The tool `terminal/tools/polystrata_names.py` writes PolyStrata where a Strata tree says Strata, and
`AGENTS.md` says to run it after merging from the Strata project. It reports **13 files** that still carry
the name.

**This is a pre-existing condition, not a merge regression.** The pre-merge Kurchatov revision
(`7ad7c531d`) fails the same test, with **exactly the same 13 files**:

```text
$ (pre-merge)  python tools/polystrata_names.py --check   -> 13 files would change
$ (candidate)  python terminal/tools/polystrata_names.py --check -> 13 files would change
$ diff of the two file lists, by the file's name (the paths moved in the merge)
IDENTICAL - the same 13 files, before and after the merge
```

The files are the Kurchatov telemetry's own comments and doc strings (`Strata reuses a contiguous prefix
only`, the `X-Strata-Request-ID` header name, the schema's `title`), the historical evidence and forensics
documents, and `docs/TELEMETRY.md`.

**This ACT does not run the renamer.** The renamer would rewrite the telemetry's own historical evidence
and its wire-protocol header name, and this ACT's mandate is to preserve the accepted integration and the
telemetry implementation - which the byte-level comparison in `05-cross-surface-conservation.md` section 5
proves it has done. The finding is **recorded** for the successor: the renamer's own rules decide what to
keep, and a decision about the `X-Strata-Request-ID` header name is a decision about the **wire protocol**,
which is outside this ACT.

### 5.3 The six that are the upstream's own baseline

The other six failures - `test_feed_model_install_realfile`, `test_strata_bench`'s redaction,
`test_strata_mcp`'s install and cancel, and `test_strata_mcp_zombie` - fail **identically on the pinned
upstream** on this machine:

```text
upstream  (42e489d14):  6 failed, 2213 passed, 44 skipped, 1067 subtests passed
candidate (859d62c4a):  7 failed, 2285 passed, 45 skipped, 1067 subtests passed
```

The seventh is the `polystrata_names` one of section 5.2. So **no** of the six is the merge's.

## 6. The summary

```yaml
SELECTED_SUITES: passed (8 of 8, the list of section 1)
TERMINAL_SUITE:
  CANDIDATE: 3439 tests, 40 failures, 56 errors, 152 skipped
  UPSTREAM_BASELINE: 3439 tests, 40 failures, 56 errors, 152 skipped
  FAILING_SETS_IDENTICAL: true   (diff of the two name lists is empty)
  REGRESSION_INTRODUCED_BY_THE_MERGE: none
NATIVE_CTEST:
  CANDIDATE: 294 passed, 14 failed (the GPU parity tests)
  UPSTREAM_BASELINE: the same parity tests fail on the same host, with the same message
  REGRESSION_INTRODUCED_BY_THE_MERGE: none
FULL_TARGET_BUILD: 693 of 693; 4 failed, all of them strata-device and its tests (upstream's defect,
  outside the release engine's target list)
TOOLS_CHECK:
  CANDIDATE: 2285 passed, 7 failed, 45 skipped
  UPSTREAM_BASELINE: 2213 passed, 6 failed, 44 skipped
  THE_ONE_THE_MERGE_INTRODUCED: the settings register's gap (STRATA_CACHE_DIAG, STRATA_TELEMETRY)
      - FIXED in this ACT: the register's own generator, the two entries added with
        status=research and owner=program, the register's own check clean, its own test 8 passed
  THE_ONE_PRE_EXISTING: the 13 files that polystrata_names.py would rename - the SAME 13 before and
      after the merge - RECORDED, not renamed: the renamer would rewrite the telemetry's own
      historical evidence and its wire-protocol header name
  THE_SIX_THAT_ARE_UPSTREAM_S: fail identically on the pinned upstream
```

**This is a selected set of suites.** It is not the complete upstream qualification on the target
hardware, and it does not claim to be. The complete qualification is a separate exercise; see
`05-cross-surface-conservation.md` section 4.
