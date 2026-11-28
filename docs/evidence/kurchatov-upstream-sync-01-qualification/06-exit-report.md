# 06 - Exit report

ACT: **ACT-KURCHATOV-UPSTREAM-SYNC-01**, execution segment `QUALIFICATION-HANDOFF`

```yaml
ACT_ID: ACT-KURCHATOV-UPSTREAM-SYNC-01
ACCEPTED_MERGE_HEAD: 74e89653e98d855d292c373075a5f1978df56a23
EXPECTED_EVIDENCE_HEAD: 859d62c4a
PINNED_UPSTREAM_HEAD: 42e489d145aaf4430b54f2c58679be27d45faf17

MERGE_HEAD: 74e89653e98d855d292c373075a5f1978df56a23   # the accepted integration, unchanged
TESTED_CODE_HEAD: 859d62c4a7f6bf3b1942ff1c6e61e4405f91623a
FINAL_HEAD: 859d62c4a7f6bf3b1942ff1c6e61e4405f91623a   # this evidence receipt

SM61_BUILD: DONE - the exact candidate revision built on a Tesla P40 (compute capability 6.1) with
            CUDA 12.9.86 and STRATA_EXPERIMENTAL_SM60=ON: 189 of 189 targets, 0 failures, the full
            native executable produced (strata, 91665880 bytes,
            sha256 0f5686d872b78b5451813d3c6d9ac4c5c70b8194d05c39be95db92821bf8cb23), the embedded
            architecture targets read out of the linked binary with cuobjdump are sm_61 and nothing
            else, the selected native ctest 6 of 6 passed, both roundtrips exit 0, and the running
            service was not disturbed (the same MainPID, the same start timestamp, NRestarts=0).
SM120_BUILD: NOT BUILT - this host has no Blackwell card and no CUDA 13.x toolkit. The profile is the
            repository's own declaration (.github/workflows/backends.yml:74):
            { cuda: '13.0', image: '13.0.2-devel-ubuntu24.04', archs: '75-real;86-real;120-real',
              sm60: 'OFF' }. No build, no checksum and no claim is made for it.

QUALIFIED_EXECUTION_ENVELOPE:
  ONE_ENGINE_PER_GPU_HOST: true
  MODEL: the existing Qwen model and its existing quantization
  SSD_CONVERSATION_CACHE_SPILLING: disabled  (--conversation-spill-mib 0)
  STRATA_SLOT_READ: disabled              (unset; the engine's own rule reads unset as off)
  REPLICA_ROUTING: disabled               (no --replicas, no "replicas" in the run config)
  SPLIT_PREFILL_DECODE_SERVING: disabled (no --split-serve, no "split_serve" in the run config)
  NO_UPSTREAM_DEFAULT_CHANGED: true - the envelope is a deployment profile, not a change to the tree

SSD_CACHE_TELEMETRY: DEFERRED - an SSD-restored image is reported with a RAM-tier source name
                    (parked_live / parked_checkpoint) and a matched prefix derived from the RAM
                    candidates alone; the Source enumeration has no name for the SSD tier. The tier is
                    DISABLED in the initial profile, so no qualified measurement comes out of it, and
                    no RAM-tier match is fabricated from an SSD reuse.
SLOT_READ_TELEMETRY: UNAVAILABLE - the fast path prints its own DONE line with no telemetry suffix
                    (the encoder is never called on that path), so the evidence is ABSENT, not
                    correlated and not admitted; the server reports it as unavailable. The optimization
                    is DISABLED for the initial native measurements.
REPLICA_TELEMETRY: UNAVAILABLE - ReplicaEngine has no set_request_id, so the rid= never reaches a
                    replica's engine; the file is byte-identical to the pinned upstream's (inherited
                    technical debt). NOT redesigned in this ACT; the replicas are outside the envelope.
SPLIT_SERVING_TELEMETRY: UNAVAILABLE - no invocation correlation and no native measurement authority;
                    published as unavailable, never as zero. Excluded from the envelope.

NATIVE_EXECUTABLE_IDENTITY:
  REVISION: 859d62c4a7f6bf3b1942ff1c6e61e4405f91623a
  SOURCE_ARCHIVE_SHA256: cb785c1e383994f850652e3b738bc061a8ce38fde76704089df238affbbcc4a9 (verified on both sides)
  BINARY: strata, 91665880 bytes, sha256 0f5686d872b78b5451813d3c6d9ac4c5c70b8194d05c39be95db92821bf8cb23
  EMBEDDED_ARCHITECTURES: sm_61 (only), read out of the linked executable
  COMPILER: nvcc release 12.9, V12.9.86; GNU c++ 13.3.0; CMake 3.28.3; Ninja 1.11.1

PROMETHEUS_EXPOSITION: VERIFIED - the actual HTTP exposition, against a populated telemetry store:
             18 633 bytes, content type "text/plain; version=0.0.4; charset=utf-8", 20 upstream-
             compatible families and 31 canonical families in the SAME scrape, the canonical families
             process-scoped (no model_name label) and the upstream-compatible families keeping theirs,
             and an unmeasured duration publishing NO sample (never a family of zeros).

CROSS_SURFACE_CONSERVATION: VERIFIED - every telemetry module and every cache-diagnostics file is
             byte-identical to the Kurchatov entry head's version (only the location changed), and the
             one file that was extended, terminal/serve/prometheus.py, was extended ADDITIVELY. The
             merge's authority about that file was WRONG and is corrected in 05-cross-surface-
             conservation.md: upstream's exporter was adopted as the base and Kurchatov's canonical
             telemetry families were appended to it, additively - it was not a replacement.

INFRASTRUCTURE_HANDOFF: PREPARED - 04-infrastructure-handoff.md names the nine mandatory
             requirements and, for each one, the evidence in this repository that the successor must
             satisfy it. The separate infrastructure repository was NOT mutated.
BUILD_CONTEXT_POLICY: RECORDED - tools/docker/Dockerfile.src.dockerignore carries the inherited
             exclusions; the successor must add /.kurchatov-acts/, /.act-worktrees/, the local
             credentials and the new layout's generated artifacts.
WORKFLOW_REVIEW: RECORDED - .github/workflows/docker-images.yml downloads an UPSTREAM RELEASE
             EXECUTABLE and publishes it to ghcr.io/niko1221/strata; this is the inherited defect that
             requirement 4 forbids, and the successor must change the path and the destination.
             backends.yml already declares the two CUDA profiles of requirement 2.

MAIN_CHANGED: false - main and origin/main are both still 859d62c4a7f6bf3b1942ff1c6e61e4405f91623a
REMOTE_PUSHED: false
PRODUCTION_STATE_CHANGED: false - the running service on the P40 host was never stopped, restarted or
             replaced; the build was isolated and the service's identity is unchanged

UNRESOLVED_DEFECTS:
  - the SSD cache tier's telemetry attribution (deferred; the tier is disabled in the initial profile)
  - the slot-read fast path's missing telemetry suffix (recorded; the optimization is disabled)
  - the replica engine's missing set_request_id (inherited upstream debt; not redesigned here)
  - the inherited publication path that ships an upstream release executable (the successor's job)
  - UPSTREAM, in the auxiliary diagnostic target strata-device: the undefined reference to
    strata::kernels::cpu::expert_layout() (pinned.cu calls it; the target does not link the
    translation unit that defines it). Every file of that link chain is byte-identical to the
    pinned upstream's, and the release engine (strata) and the upstream CI's target list do not
    include it. Recorded, not patched - see 03-native-build.md section 8.
  - PRE-EXISTING, the 13 files that terminal/tools/polystrata_names.py would rename: the SAME 13
    before and after the merge, so not a regression of it. NOT renamed here: the renamer would
    rewrite the telemetry's own historical evidence and its wire-protocol header name. Recorded
    for the successor - see 07-test-results.md section 5.2.
EVIDENCE_LOCATION: docs/evidence/kurchatov-upstream-sync-01-qualification/
FINAL_DISPOSITION: QUALIFIED_FOR_SUCCESSOR_INFRASTRUCTURE_ACT
```

## 1. What this segment did, and what it did not

**It did** establish the supported qualification envelope out of the candidate's own source, build the
**exact** candidate revision for the Pascal profile on a real GPU host and verify the full native
executable's identity, record the measurement authority of the four newly introduced paths, verify the
actual HTTP Prometheus exposition against a populated store, correct the merge's capability-preservation
authority, and prepare the successor infrastructure ACT.

**It did not** add a telemetry subsystem, rewrite the merge, promote `main`, activate a production engine,
publish anything, push anything, or change a single upstream default.

## 2. The three things the ACT asked to be careful about

### 2.1 The measurement authority was not extended to the unqualified paths

The four paths are held outside the qualified envelope, each for its own measured reason
(`02-measurement-authority.md`). The important distinction is the one the ACT asks for:

* the SSD tier's defect would make an **incorrect authoritative measurement** (a RAM-tier name and a
  RAM-derived prefix on an SSD reuse) - so the tier is **disabled**;
* the slot-read fast path's evidence is **absent** (the encoder is never called) - so it is not correlated
  and not admitted, and the optimization is **disabled**;
* the replica engine's `rid=` is **absent** (no `set_request_id`) - so the correlation cannot bind, and the
  replicas stay **outside** the envelope;
* the split engine and the additional engines have **no** native measurement authority - their
  measurements are published as **unavailable**, never as zero.

Nothing was fabricated to fill a gap, and no new instrumentation framework was added.

### 2.2 The capability-preservation authority was corrected, not repeated

The merge's exit report and its commit message both said that upstream's Prometheus exporter "was
adopted". The bytes say otherwise: the merged file is Kurchatov's own exporter, carried over by a
**byte-identical rename** (similarity index 100%), and upstream's file is a byte-identical **prefix** of
it. The corrected authority is in `05-cross-surface-conservation.md`: upstream's exporter was adopted as
the **base** and Kurchatov's canonical telemetry families were **appended** to it, additively. The
capability is unaffected - the exposition proves that both surfaces are in one scrape - but the authority
for it was wrong and is now right.

### 2.3 The build was isolated and the deployment was not disturbed

The candidate lives in `/opt/.kurchatov-qual/`, outside the deployment's installation directory. The
running service's `MainPID`, its start timestamp and its restart counter are **identical** before and
after the build. No package was installed; the CUDA 12.9 toolkit was already there.

## 3. The limits of this qualification

* **No request was served by the built engine.** The native correctness rests on the native test targets
  and the two roundtrips, not on a live run against a model. The ACT's
  `ISOLATED_NATIVE_QUALIFICATION_PERMITTED` covers a native qualification; a *live* serving qualification
  on the real model is the successor's and the infrastructure ACT's business.
* **The Blackwell profile was not built** - there is no Blackwell card and no CUDA 13.x toolkit on this
  host. The profile is recorded from the repository's own declaration, and no build is claimed.
* **The selected suites are not the complete upstream qualification.** The complete qualification of the
  merged tree on the target hardware is a separate exercise; `05-cross-surface-conservation.md` section 4
  names exactly which suites were run and what each one does *not* establish.

## 3.1 The suites that were run, and their results

| The suite | The result | What it covers |
| --- | --- | --- |
| `tools/verify_prometheus_exposition.py` (this ACT's witness) | **PROMETHEUS_EXPOSITION_OK** | the actual HTTP exposition against a populated store |
| `serve.test_prometheus` + the telemetry suites (6 modules) | **127 tests, OK** | the exporter's contract, the store's accounting, the correlation, the evidence writer |
| `terminal/tests/terminal` | **3 439 tests; the failing set is IDENTICAL to the upstream baseline's** | the Terminal and the Control |
| `tools/test_telemetry_mutations.py` | **OK** | the mutation witnesses (the predecessor's non-vacuity witnesses still hold) |
| `tools/test_reqtelemetry_schema.py` | **OK** | the schema on disk is the schema in the code |
| `tools/test_telemetry_web_inspector.py` | **OK** | the web telemetry inspector |
| `tools/test_telemetry_web_accounting.py` | **OK** | the web inspector's accounting |
| `ctest -R "reqtelemetry\|cache_diag\|conv_cache\|conversation_cache"` (on the real card) | **6 of 6 passed** | the native half |
| `./reqtelemetry_roundtrip`, `./cache_diag_roundtrip` (on the real card) | **exit 0, exit 0** | the writer/reader roundtrip |

### 3.2 The regression comparison: the merge introduced none

The Terminal suite was run on the **candidate** and on the **pinned upstream** in a detached worktree of
the same repository, on the same machine, with the same interpreter and the same writable `TMPDIR`:

```text
candidate (859d62c4a):  Ran 3439 tests in 820.358s
                        FAILED (failures=40, errors=56, skipped=152)
upstream  (42e489d14):  Ran 3439 tests in 820.326s
                        FAILED (failures=40, errors=56, skipped=152)
```

The two failing sets are **identical name for name** (96 entries, `diff` empty). The native parity tests
fail on the upstream **on the same host, with the same message** (`FAIL: W: out of memory`, because the
incumbent deployment's engine holds the P40's VRAM).

**REGRESSION_INTRODUCED_BY_THE_MERGE: none** in these two suites.

### 3.3 The one regression the tools check found, and the fix

The repository's own `tools/check --only py-tools` step found **one** failure that the merge introduced: the
settings register did not list the two settings the Kurchatov telemetry brought in,
`STRATA_CACHE_DIAG` and `STRATA_TELEMETRY`. The upstream passes that test; the merged engine reads both.

**It is FIXED in this ACT**, with the register's own generator and the register's own rules: the two
entries added with `status: research` and `owner: program`, the register's own `--check` clean, and its
own test **8 passed**. No hand-kept field of any existing entry changed. The full account is in
`07-test-results.md` section 5.1.

The other seven failures of that step are **not** the merge's: six fail identically on the pinned
upstream, and the seventh (the `polystrata_names` renamer's 13 files) is the **same 13** before and after
the merge. It is **recorded**, not renamed - the renamer would rewrite the telemetry's own historical
evidence and its wire-protocol header name.

## 4. The disposition

**QUALIFIED_FOR_SUCCESSOR_INFRASTRUCTURE_ACT.** The Pascal profile of the exact candidate revision builds,
produces the full native executable, carries `sm_61` and nothing else, passes its selected native suites,
and leaves the running deployment untouched. The four unqualified paths are recorded and held outside the
envelope with their tiers and optimizations disabled. The exporter's capability-preservation authority is
corrected and the actual exposition is verified. The successor infrastructure ACT has its nine
requirements, its two build profiles, its build-context policy and the inherited publication defect.

The next ACT is the infrastructure one. This ACT stops here.
