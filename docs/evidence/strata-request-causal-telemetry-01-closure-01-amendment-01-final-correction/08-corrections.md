# The corrections of ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 - FINAL-CORRECTION

The entry head of this segment was `3769eed7bc82784ce9d06be78a553b2620b38329`.  The historical evidence of the
earlier segments is UNCHANGED: this directory is a successor, not a rewrite.

## F1 - the population accounting is request-local

**The defect.**  `ServerTelemetry.finish()` counted the dispatches of a failed request by comparing the GLOBAL
counters before and after the failure:

```python
counted_before = self.store.native_counters_snapshot()
...
accounted, missing = self.store.native_counters_snapshot()
already = (accounted - counted_before[0]) + (missing - counted_before[1])
self.store.count_unaccounted_dispatches(max(0, dispatched - already))
```

A CONCURRENT request that completed while the failed request was sealing moved the global counters, so the
failed request's own dispatch was read as already accounted.  The reviewer reproduced it deterministically: request
A dispatches one invocation, blocks inside its sealing; request B dispatches one invocation and completes; A
resumes and its sealing fails.  The result was `native_invocations_accounted: 1, native_invocations_missing: 0` -
the failed request's dispatch was never counted as missing.

**The correction.**  The outcome is counted on the REQUEST's own bookkeeping (`RequestRecord._population_*`), never
on another request's counters.  `TelemetryStore.count_unaccounted_dispatches(record)` computes
`dispatched - accounted - missing` from that record's own fields.  `count_dispatch_population` checks
`_population_counted` and sets it INSIDE the store's lock - the synchronized accounting boundary - so the
population is counted exactly once.  `TelemetryStore.add()` is atomic: a failure inside the aggregation rolls the
counters, the eviction bookkeeping, the histograms and the stored record back, so a failure cannot partially
commit measurements and then count them again.  The serialization happens OUTSIDE the store's lock, and the
sealing happens outside it too.

**The unresolved population.**  A dispatched invocation is UNRESOLVED from the moment its dispatch is counted
until the moment its aggregation outcome is known.  It is neither accounted nor missing while it is unresolved,
and the new counter `native_invocations_unresolved` publishes it.  At quiescence it is empty and
`dispatched = accounted + missing` holds.

**The witnesses.**  `serve/test_telemetry_amendment01_final.py::ConcurrentPopulation`:
`test_a_concurrent_request_does_not_account_for_a_failed_one` (the deterministic barrier witness),
`test_the_dispatch_population_is_counted_exactly_once`,
`test_the_concurrent_accounting_is_the_request_s_own`, `test_a_failed_aggregation_commits_nothing`.
The reversals are in `tools/test_telemetry_amendment01_final_mutations.py`.

## F2 - the prompt-domain authority survives the retention

**The defect.**  `TelemetryStore._request_coverage_ids()` decided the uniqueness of the request's own prompt
domain from the RETAINED receipts.  A request that dispatched its own prompt twice, lost the first receipt and
kept the second, was treated as a single request-domain dispatch - the exact request-level coverage became
CERTAIN because the evidence was lost.

**The correction.**  The multiplicity is the REQUEST's own: `RequestRecord.note_prompt_domain()` counts the
dispatches per domain at the dispatch boundary, and `InvocationReceipt.prompt_domain` became a property that
tells the parent when the domain is named.  The counts live in the parent, so they survive the retention of the
receipts.  `TelemetryStore._domain_authority(record)` reads them; `_request_coverage_ids()` refuses the exact
request-level coverage when the request's own domain was carried more than once, or when a dispatch's domain could
not be established.  The domain is a NAME ("request", "continuation", "other") - never a prompt hash, never content -
and the per-dispatch memory is bounded.

**What this leaves alone.**  The cumulative native work and the invocation-weighted ratio are unchanged: every
invocation's own positions are still counted, and the ratio still has both populations.

**The witnesses.**  `serve/test_telemetry_amendment01_final.py::RetentionIndependentDomainAuthority`: both
discard orders, both retained, the known continuation, the unestablishable domain, and
`test_retention_does_not_improve_the_certainty` (the counts of the retained and the discarded case are the same).

## F3 - one normalized terminal authority

**The defect.**  `normalize_terminal_evidence()` read the native state and the partial classification from the
POSITIONAL dictionary, while `apply_engine()` applied SEPARATELY SUPPLIED arguments.  The evidence that was
compared and the evidence that was committed could disagree: a duplicate that changed the effective native
outcome looked like an identical duplicate.

**The correction.**  `effective_terminal_inputs()` resolves the effective state and the effective partial
classification ONCE, and the normalization consumes exactly those values, so the comparison and the commit can
never disagree.  A change of the effective state or of the effective partial classification is a CONFLICT.  The
accepted measurements, the accepted outcome and the accepted correlation are unchanged; the conflict is reported
as a diagnostic annotation beside the accepted receipt.

**The witnesses.**  `serve/test_telemetry_amendment01_final.py::OneNormalizedTerminalAuthority`: the changed
state, the changed partial classification, the same outcome through the production error path, the identical
complete duplicate, and the native-versus-HTTP outcome separation.

## F4 - the dashboard renders the card again

**The defect.**  The RESUME-01 patch replaced the assignment to the `reuse-ratio` element with a call to
`$("#reuse-detail")`.  Two things were wrong: the card's own value was never drawn again, and `$` is
`getElementById` on this page, so the id is `reuse-detail` and NOT `#reuse-detail`.  The coverage line also
disappeared entirely when the cache ratio was unavailable, so the populations were hidden with it.

**The correction.**  `renderStatus()` draws the card's value again (`$("reuse-ratio").textContent =
reuseRatioText(reuse)`) and writes the coverage line to `$("reuse-detail")`.  `reuseRatioText()` is a new PURE
function in `serve/web/telemetry_accounting.js`: a measured zero is "0.0%", an unavailable ratio is "—".  The
coverage line always names the populations, and it only ADDS the note when the ratio is unavailable.

**The witnesses.**  `tools/test_telemetry_web_status.py` runs the ACTUAL `renderStatus` of the page against a
stub DOM and reads back what it wrote: the measured ratio (90.0%), the measured zero (0.0%) and the unavailable
ratio ("—" with the coverage populations still visible).  The witness has teeth: with the card's own assignment
removed, the same check fails.  The accepted `invocationFacts` implementation is unchanged.

## F5 - the schema resource identity

**The defect.**  The current contract (`strata.request-telemetry/3`) carried the HISTORICAL resource identifier
(`strata-request-telemetry-2.json`), so the two contracts were one resource under two names.

**The correction.**  The current contract has its own identifier:
`https://github.com/s1onique/Kurchatov/schemas/strata-request-telemetry-3.json`.  The historical v2 contract keeps
its own, and the historical file is unchanged.  The contract was NOT bumped to v4.

**The witnesses.**  `tools/test_reqtelemetry_schema.py` checks the two identifiers, that each schema is the
contract that is on disk, that a historical record validates against v2 and a current record against v3, and that
the cross-version validation rejects the incompatible records.  `serve/test_telemetry_amendment01_final.py::
SchemaResourceIdentity` checks the same identities from the code.

## The deferred technical debt

The `_SeenEngines` membership filter prevents authoritative double-counting but uses a constant hash stride.  Its
false-positive characteristics deserve a separate bounded-accounting maintenance item.  The filter was NOT
redesigned in this segment, and the accepted 74-to-75 and forgotten-engine witnesses still hold.
