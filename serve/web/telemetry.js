"use strict";
// serve/web/telemetry.js - the request telemetry view (ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01).
//
// The page shows what the ENGINE measured for each request: the tokens it reused, the tokens it evaluated, where
// the reusable state came from and how long each stage took.  It shows METADATA ONLY: the server's telemetry
// keeps no prompts and no answers, and this page never asks for any.
//
// The refresh is bounded (two seconds by default) and never overlaps: a poll that has not come back yet is not
// followed by another one.
const $ = id => document.getElementById(id);
const num = n => typeof n === "number" && Number.isFinite(n) ? n.toLocaleString() : "—";
const ms = n => typeof n === "number" && Number.isFinite(n) ? (n >= 1000 ? `${(n / 1000).toFixed(2)} s` : `${n.toFixed(0)} ms`) : "—";
const rate = (tokens, durationMs) => typeof tokens === "number" && typeof durationMs === "number" && durationMs > 0
  ? (tokens / (durationMs / 1000)).toFixed(1) : "—";
const when = t => typeof t === "number" ? new Date(t * 1000).toLocaleTimeString() : "—";

let apiKey = sessionStorage.getItem("strata.telemetry.key") || (localStorage.getItem("strata.apikey") || "");
let records = [], selected = null, cursor = null, timer = null, busy = false, stopped = false, stamp = "";

document.documentElement.dataset.theme = localStorage.getItem("strata.theme") || "dark";
$("theme").onclick = () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("strata.theme", next); } catch (e) { /* ignore */ }
};
$("key").onclick = () => { $("auth").hidden = !$("auth").hidden; if (!$("auth").hidden) $("api-key").focus(); };
$("auth").onsubmit = event => {
  event.preventDefault();
  apiKey = $("api-key").value.trim();
  sessionStorage.setItem("strata.telemetry.key", apiKey);
  $("auth").hidden = true;
  poll();
};

async function api(path) {
  const response = await fetch(path, {cache: "no-store", headers: apiKey ? {Authorization: `Bearer ${apiKey}`} : {}});
  const value = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) $("auth").hidden = false;
    throw new Error(value.error?.message || `HTTP ${response.status}`);
  }
  return value;
}
function notice(message) { $("error").hidden = !message; if (message) $("error").textContent = message; }

// The filters: the server does the filtering, so the page shows what the server actually holds.
function query(extra = {}) {
  const params = new URLSearchParams();
  params.set("limit", "100");
  const status = $("filter-status").value;
  const cache = $("filter-cache").value;
  const client = $("filter-client").value.trim();
  if (status) params.set("request_status", status);
  if (cache) params.set("cache_disposition", cache);
  if (client) params.set("client_request_id", client);
  for (const [key, value] of Object.entries(extra)) if (value) params.set(key, value);
  return params.toString();
}

async function poll() {
  if (busy || stopped) return;                 // never overlap two polls
  busy = true;
  try {
    const [status, summary, page] = await Promise.all([
      api("/v1/telemetry/status"),
      api("/v1/telemetry/summary"),
      api(`/v1/telemetry/requests?${query()}`),
    ]);
    notice("");
    records = page.records || [];
    cursor = page.next_cursor || null;
    renderStatus(status, summary);
    renderTable();
    renderDetail();
    $("updated").textContent = `Updated ${when(Date.now() / 1000)}`;
  } catch (e) {
    notice(e.message || String(e));
  } finally {
    busy = false;
  }
}

function renderStatus(status, summary) {
  $("engine-state").textContent = status.model || "—";
  $("engine-id").textContent = status.engine_instance_id || status.build_revision || "identity unavailable";
  $("tele-state").textContent = status.enabled ? "On" : "Off";
  const quality = status.quality || "unknown";
  $("tele-detail").textContent = `Quality: ${quality}`;
  const counters = summary.counters || {};
  $("req-count").textContent = num(counters.requests_total);
  const failed = (counters.requests_cancelled || 0) + (counters.requests_failed || 0);
  $("req-detail").textContent = `${num(failed)} cancelled or failed · ${num(counters.retention_evictions)} evicted`;
  // The token-weighted cache reuse ratio: reused tokens over submitted tokens, both from the engine's counters.
  const submitted = counters.prompt_tokens_submitted || 0;
  const reused = counters.prompt_tokens_reused || 0;
  $("reuse-ratio").textContent = submitted ? `${((reused / submitted) * 100).toFixed(1)}%` : "—";
  $("reuse-detail").textContent = `${num(reused)} of ${num(submitted)} tokens reused`;
}

function renderTable() {
  const body = $("req-body");
  const next = JSON.stringify([records.map(r => r.identity.request_id), selected]);
  if (stamp === next) return;
  stamp = next;
  body.replaceChildren();
  if (!records.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 17; cell.className = "muted";
    cell.textContent = "No requests yet.";
    row.append(cell); body.append(row);
    return;
  }
  for (const r of records) {
    const identity = r.identity, prompt = r.prompt, cache = r.cache, timing = r.timing_ms || {};
    const row = document.createElement("tr");
    if (identity.request_id === selected) row.className = "selected";
    const cells = [
      when(r.lifecycle.received_at),
      identity.client_request_id || identity.request_id.slice(0, 8),
      r.lifecycle.state,
      identity.model_id || "—",
      identity.slot_id === null || identity.slot_id === undefined ? "—" : num(identity.slot_id),
      num(prompt.rendered_tokens), num(prompt.submitted_tokens),
      num(prompt.matched_prefix_tokens), num(prompt.reused_prefix_tokens),
      num(prompt.evaluated_tokens), num(prompt.replayed_tokens),
      cache.disposition,
      ms(timing.prefill_wall),
      rate(prompt.submitted_tokens, timing.prefill_wall),
      ms(timing.http_first_token),
      rate(r.generation.emitted_tokens, timing.decode_wall),
      r.lifecycle.finish_reason || "—",
    ];
    cells.forEach((value, index) => {
      const cell = document.createElement("td");
      cell.textContent = value === null || value === undefined ? "—" : String(value);
      if ([4, 5, 6, 7, 8, 9, 12, 13, 14, 15].includes(index)) cell.className = "num";
      if (index === 2) { const tag = document.createElement("span"); tag.className = `tag ${value}`; tag.textContent = value; cell.textContent = ""; cell.append(tag); }
      row.append(cell);
    });
    row.onclick = () => { selected = identity.request_id; stamp = ""; renderTable(); renderDetail(); };
    body.append(row);
  }
}

function fact(label, value) {
  const box = document.createElement("div"); box.className = "fact";
  const name = document.createElement("span"); name.textContent = label;
  const text = document.createElement("b"); text.textContent = value;
  box.append(name, text);
  return box;
}

function renderDetail() {
  const record = records.find(r => r.identity.request_id === selected);
  $("no-selection").hidden = !!record;
  $("selection").hidden = !record;
  if (!record) return;
  const identity = record.identity, prompt = record.prompt, cache = record.cache;
  const timing = record.timing_ms || {}, generation = record.generation || {};
  $("detail-title").textContent = identity.request_id;
  $("detail-sub").textContent = `${identity.client_request_id ? `client ${identity.client_request_id} · ` : ""}${identity.api || ""} · ${identity.model_id || "—"}`;

  // The warnings: what an operator must not miss.
  const warnings = $("detail-warnings");
  warnings.replaceChildren();
  const list = document.createElement("ul"); list.className = "warn-list";
  const add = (message, bad) => { const item = document.createElement("li"); if (bad) item.className = "bad"; item.textContent = message; list.append(item); };
  if (typeof prompt.matched_prefix_tokens === "number" && typeof prompt.reused_prefix_tokens === "number"
      && prompt.matched_prefix_tokens > prompt.reused_prefix_tokens) {
    add(`The tokens matched ${prompt.matched_prefix_tokens} deep, but only ${prompt.reused_prefix_tokens} could be reused: the state was not usable.`);
  }
  if (cache.restore_attempted === true && cache.restore_succeeded === false) {
    add("The state restoration FAILED. The prefix was re-read, not reused.", true);
  }
  const quality = record.measurement_quality || {};
  if (quality.state && quality.state !== "complete") {
    add(`The measurement is ${quality.state}: ${Object.values(quality.unavailable_fields || {}).join("; ") || "some fields are unavailable"}`);
  }
  if (!record.identity.engine_instance_id && !record.identity.engine_invocation_id) {
    add("The engine reported no telemetry for this request: the native figures are unavailable.");
  }
  if (list.children.length) warnings.append(list);

  const facts = $("detail-facts");
  facts.replaceChildren();
  for (const [label, value] of [
    ["Request id", identity.request_id],
    ["Client request id", identity.client_request_id || "—"],
    ["Engine instance", identity.engine_instance_id || "—"],
    ["Engine invocation", identity.engine_invocation_id || "—"],
    ["Server instance", identity.server_instance_id || "—"],
    ["Build revision", identity.build_revision || "—"],
    ["Slot", identity.slot_id === null || identity.slot_id === undefined ? "—" : String(identity.slot_id)],
    ["Cache source", cache.source],
    ["Cache reason", cache.reason_code || "—"],
    ["Restore", cache.restore_attempted === null ? "—" : cache.restore_succeeded ? "succeeded" : "failed"],
    ["Rendered tokens", num(prompt.rendered_tokens)],
    ["Submitted tokens", num(prompt.submitted_tokens)],
    ["Matched prefix", num(prompt.matched_prefix_tokens)],
    ["Reused prefix", num(prompt.reused_prefix_tokens)],
    ["Evaluated tokens", num(prompt.evaluated_tokens)],
    ["Replayed tokens", num(prompt.replayed_tokens)],
    ["Evaluation work", num(prompt.evaluation_work_tokens)],
    ["First divergent token", prompt.first_divergent_token_index === null || prompt.first_divergent_token_index === undefined ? "—" : String(prompt.first_divergent_token_index)],
  ]) facts.append(fact(label, value));

  // The token accounting bar: the reused prefix, the evaluated positions and the replayed part of them.
  const bar = $("detail-bar");
  bar.replaceChildren();
  const reused = prompt.reused_prefix_tokens || 0;
  const evaluated = prompt.evaluated_tokens || 0;
  const replayed = prompt.replayed_tokens || 0;
  const total = Math.max(1, reused + evaluated);
  const parts = [["reused", reused, "Reused"], ["evaluated", Math.max(0, evaluated - replayed), "Evaluated"],
                 ["replayed", replayed, "Replayed"]];
  for (const [className, value, title] of parts) {
    if (value <= 0) continue;
    const part = document.createElement("div");
    part.className = className;
    part.style.width = `${(value / total) * 100}%`;
    part.title = `${title}: ${value} tokens`;
    bar.append(part);
  }
  const legend = $("detail-legend");
  legend.replaceChildren();
  for (const [className, title] of [["reused", "Reused (not evaluated)"], ["evaluated", "Evaluated"],
                                    ["replayed", "Replayed (previously processed)"]]) {
    const item = document.createElement("span");
    const swatch = document.createElement("i"); swatch.className = className; swatch.style.background = "var(--st-accent)";
    if (className === "evaluated") swatch.style.background = "var(--st-info)";
    if (className === "replayed") swatch.style.background = "var(--st-warn)";
    item.append(swatch, document.createTextNode(title));
    legend.append(item);
  }

  const timings = $("detail-timings");
  timings.replaceChildren();
  for (const [label, value] of Object.entries(timing)) {
    timings.append(fact(`${label.replace(/_/g, " ")} (${(record.measurement_quality.timing_authority || {})[label] || "?"})`, ms(value)));
  }
  if (!Object.keys(timing).length) timings.append(fact("No timings", "—"));
  $("detail-json").textContent = JSON.stringify(record, null, 2);
}

// The refresh: bounded, and never overlapping (poll() returns early while one is in flight).
function schedule() {
  if (timer) clearInterval(timer);
  timer = null;
  const interval = Number($("interval").value);
  if (interval > 0) timer = setInterval(poll, interval);
}
$("interval").onchange = () => { schedule(); poll(); };
for (const id of ["filter-status", "filter-cache"]) $(id).onchange = () => { selected = null; poll(); };
$("filter-client").onchange = () => { selected = null; poll(); };
$("more").onclick = async () => {
  if (!cursor) return;
  try {
    const page = await api(`/v1/telemetry/requests?${query({cursor})}`);
    records = records.concat(page.records || []);
    cursor = page.next_cursor || null;
    stamp = "";
    renderTable();
  } catch (e) { notice(e.message || String(e)); }
};
document.addEventListener("visibilitychange", () => {
  stopped = document.hidden;              // a hidden tab does not poll
  if (!stopped) poll();
});
poll();
schedule();
