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
if (typeof module !== "undefined" && module.exports) module.exports = { accountingBarParts };
