// serve/web/telemetry_accounting.js - the token accounting bar's arithmetic, as a PURE function.
//
// ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-AMENDMENT-02 (A7): the bar must not draw a picture the numbers do not
// support.
//
//   * the denominator is the SUBMITTED prompt - the positions that went to the engine - when it is known;
//   * the positions nobody accounted for are shown as such, not hidden;
//   * an UNKNOWN replay is not a measured zero: it is left out of the bar and it is said;
//   * a violated or an unevaluated accounting gets NO normalized bar at all;
//   * a request the engine never measured gets no bar either - only the words that say so.
//
// The function touches no DOM, so a test can run it (tools/test_telemetry_web_accounting.py).  The page uses it
// through the same file; there is one implementation, not two.
function accountingBarParts(prompt, quality) {
  const q = quality || {};
  const accounting = q.accounting || {};
  const num = (v) => (typeof v === "number" && isFinite(v) ? v : null);
  const submitted = num(prompt.submitted_tokens);
  const reused = num(prompt.reused_prefix_tokens);
  const evaluated = num(prompt.evaluated_tokens);
  const nonPrefix = num(prompt.non_prefix_reused_tokens);
  const replayed = num(prompt.replayed_tokens);
  const state = accounting.state || "unevaluated";
  const notes = [];
  const parts = [];
  if (reused === null || evaluated === null) {
    notes.push("the engine reported no token accounting for this request");
    return { parts, notes, complete: false, state };
  }
  if (state === "violated" || state === "unevaluated") {
    notes.push(state === "violated"
      ? "the token accounting does not close: no bar is drawn"
      : "the token accounting could not be evaluated: no bar is drawn");
    return { parts, notes, complete: false, state };
  }
  const accounted = reused + (nonPrefix || 0) + evaluated;
  const total = submitted !== null ? submitted : Math.max(1, accounted);
  parts.push({ className: "reused", value: reused, title: `Reused: ${reused} tokens` });
  if (replayed === null) {
    notes.push("the replayed positions were not measured: they are not drawn as a measured zero");
    parts.push({ className: "evaluated", value: evaluated, title: `Evaluated: ${evaluated} tokens` });
  } else {
    parts.push({ className: "evaluated", value: Math.max(0, evaluated - replayed),
                 title: `Evaluated: ${Math.max(0, evaluated - replayed)} tokens` });
    parts.push({ className: "replayed", value: replayed, title: `Replayed: ${replayed} tokens` });
  }
  const unaccounted = submitted !== null ? Math.max(0, submitted - accounted) : null;
  if (unaccounted !== null && unaccounted > 0) {
    parts.push({ className: "unaccounted", value: unaccounted,
                 title: `Not accounted for: ${unaccounted} tokens` });
  }
  return { parts, notes, complete: true, state, total };
}
// ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01-CLOSURE-01-AMENDMENT-01 (A6): the INVOCATION inspector's facts and the
// coverage line are pure functions too, so a test can run them (tools/test_telemetry_web_inspector.py) and the
// page and the test cannot drift apart.
//
// A measurement that was NOT taken is shown as unavailable ("—"), never as a zero: 0 is a measured zero.
function telemetryNum(n) { return (typeof n === "number" && isFinite(n)) ? n.toLocaleString() : "—"; }
function telemetryMs(n) {
  return (typeof n === "number" && isFinite(n))
    ? (n >= 1000 ? `${(n / 1000).toFixed(2)} s` : `${n.toFixed(0)} ms`) : "—";
}

// The per-invocation facts of ONE record: every native dispatch of the request, with its own identity, its own
// prompt domain, its own cache attribution, its own native outcome and its own measurements.
function invocationFacts(record) {
  const facts = [];
  const invocations = (record && record.invocations) || [];
  for (const invocation of invocations) {
    const iidentity = invocation.identity || {};
    const iprompt = invocation.prompt || {};
    const icache = invocation.cache || {};
    const igen = invocation.generation || {};
    const itiming = invocation.timing_ms || {};
    const ordinal = (iidentity.ordinal === null || iidentity.ordinal === undefined) ? "?" : iidentity.ordinal;
    facts.push([`Invocation ${ordinal} state`, invocation.state || "—"]);
    facts.push([`Invocation ${ordinal} id`, iidentity.engine_invocation_id || "—"]);
    facts.push([`Invocation ${ordinal} prompt domain`, iprompt.domain || "—"]);
    facts.push([`Invocation ${ordinal} cache`, icache.disposition || "—"]);
    facts.push([`Invocation ${ordinal} matched`, telemetryNum(iprompt.matched_prefix_tokens)]);
    facts.push([`Invocation ${ordinal} reused`, telemetryNum(iprompt.reused_prefix_tokens)]);
    facts.push([`Invocation ${ordinal} evaluated`, telemetryNum(iprompt.evaluated_tokens)]);
    facts.push([`Invocation ${ordinal} generated`, telemetryNum(igen.generated_tokens)]);
    facts.push([`Invocation ${ordinal} native finish`, igen.finish_reason || "—"]);
    facts.push([`Invocation ${ordinal} prefill`, telemetryMs(itiming.prefill_wall)]);
    facts.push([`Invocation ${ordinal} decode`, telemetryMs(itiming.decode_wall)]);
  }
  return facts;
}

// The coverage line of the summary.  ACT-...-AMENDMENT-01 (A1): the populations it names are the CORRECTED ones -
// the dispatched native invocations (not the receipts that were kept) and the physical requests that reached a
// terminal outcome (not the receipts that were stored).
function reuseCoverageLine(reuse) {
  const r = reuse || {};
  const ratio = r.ratio;
  if (ratio === null || ratio === undefined) return "no request has a complete reuse accounting yet";
  const coverage = (typeof r.coverage === "number") ? `${(r.coverage * 100).toFixed(0)}%` : "—";
  return `${telemetryNum(r.reused_tokens)} of ${telemetryNum(r.submitted_tokens)} tokens reused · `
    + `${telemetryNum(r.eligible_invocations)} of ${telemetryNum(r.invocations)} native invocations accounted for (${coverage}) · `
    + `${telemetryNum(r.requests_with_complete_accounting)} of ${telemetryNum(r.requests)} requests`;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { accountingBarParts, invocationFacts, reuseCoverageLine, telemetryNum, telemetryMs };
}
