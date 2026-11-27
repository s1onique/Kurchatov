// include/strata/program/reqtelemetry.hpp - the native half of the per-request telemetry
// (ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01).
//
// The ENGINE is the authority for the cache state and the model execution: how much of the prompt it reused,
// how much it actually read, where the reusable state came from, and why it could not reuse more.  The server
// cannot reconstruct any of that from the outside - it only sees the request's answer.
//
// Those numbers travel on the request's OWN DONE line, in key=value pairs.  That matters for two reasons:
//
//   * the DONE line is the request's own channel - the server reads it while it holds that request's control
//     lines, so the numbers belong to that request BY CONSTRUCTION.  No timestamp proximity, no "the most
//     recently active request", no FIFO assumption;
//   * the DONE line already has a key=value suffix (chunk=, experts_streamed=), so a new field is an extension
//     of an existing protocol, not a new one.  An older server ignores the keys it does not know.
//
// NOTHING HERE CARRIES USER DATA: no prompt text, no token ids, no image content, no hashes of any of them.
// The fields are counts, positions and fixed words.
//
// The values are filled in the engine's request loop (src/program/generate.cpp).  This header holds the
// ENCODING only, so a host test can check it without a GPU - the same split the cache diagnostics use
// (include/strata/program/cache_diag.hpp and src/program/cache_diag_test.cpp).
#ifndef STRATA_PROGRAM_REQTELEMETRY_HPP
#define STRATA_PROGRAM_REQTELEMETRY_HPP

#include <cstdint>
#include <cstdio>
#include <string>

namespace strata {
namespace program {
namespace reqtelemetry {

/// The switch's rule, as a pure function of the environment value: only "1" turns it on.  Kept separate from
/// `enabled()` so a test can check the rule without the process-wide latch below.
inline bool switch_on(const char* value) { return value != nullptr && value[0] == '1'; }

/// The switch: STRATA_TELEMETRY=1.  Read once, so a run's behaviour cannot change under it.  With it off the
/// engine does no extra work and the DONE line is byte-identical to the release's.
inline bool enabled() {
    static const bool on = switch_on(std::getenv("STRATA_TELEMETRY"));
    return on;
}

/// What the engine measured for ONE request.  Every field is a count, a position or a fixed word; a field the
/// engine did not measure stays at its "not measured" value and is NOT written out at all (the server then
/// reports it as unavailable, never as zero).
///
/// The token accounting keeps two things apart on purpose:
///   * `matched_prefix` - the contiguous token-prefix match against the best candidate, BEFORE the execution
///     state is considered.  It says how far the tokens agreed;
///   * `reused_prefix` - the contiguous prefix whose usable execution state was really retained or restored,
///     so those positions were not evaluated again.  It says how much work was saved.
/// A candidate whose tokens match but whose state is unusable moves the first without moving the second.
struct RequestTelemetry {
    int64_t matched_prefix = -1;      ///< the token-prefix match; -1: not measured
    int64_t reused_prefix = -1;       ///< the prefix whose state was really reused; -1: not measured
    int64_t evaluated = -1;           ///< the distinct prompt positions the engine evaluated; -1: not measured
    int64_t replayed = -1;            ///< the evaluated positions that were previously processed material; -1
    int64_t work = -1;               ///< the executed prompt-token evaluations (repeats count again); -1
    int64_t first_divergent = -2;     ///< the first differing token's position; -1: no mismatch, -2: not measured
    int64_t slot = -1;               ///< the execution slot this request ran in; -1: the solo path
    int64_t invalidations = -1;       ///< the cache invalidations this request saw; -1: not measured
    int64_t evictions = -1;           ///< the cache evictions this request saw; -1: not measured
    double restore_ms = -1.0;        ///< the time the state restoration took; negative: not measured
    double lookup_ms = -1.0;         ///< the time the cache LOOKUP took (the candidates examined and the choice);
                                     ///< negative: not measured
    bool restore_attempted = false;  ///< whether a restoration was tried
    bool restore_succeeded = false;  ///< whether it worked
    std::string source = "unknown";   ///< where the reusable prefix came from
    std::string reason = "unknown";   ///< why the engine did what it did
    std::string request_id;           ///< the server's id for this request, echoed back (empty: none was sent)
};

/// The token accounting, as the engine measured it.  The two prefixes are different things on purpose:
///
///   * `matched` is the CONTIGUOUS TOKEN PREFIX MATCH against the candidates the engine examined, before the
///     execution-state constraints were applied: how far the tokens agreed.  It comes from the cache diagnostics'
///     own comparison - the ACTUAL common prefix, never a candidate's length.
///   * `reused` is the contiguous prefix whose usable execution state was really retained or restored, so those
///     positions were NOT evaluated again.  It is 0 when the state was re-read instead of mounted.
///
/// A candidate whose tokens match but whose state is unusable moves the first without moving the second: that is
/// the difference between a match and a reuse.
struct TokenAccounting {
    int64_t submitted = -1;      ///< the prompt tokens admitted to the engine
    int64_t matched = -1;        ///< the token-prefix match
    int64_t reused = -1;         ///< the prefix whose state was really reused
    int64_t evaluated = -1;      ///< the distinct prompt positions evaluated
    int64_t replayed = -1;       ///< the evaluated positions that were previously processed prompt material
    int64_t work = -1;           ///< the executed prompt-token evaluations (repeats count again)
    int64_t non_prefix_reused = -1;   ///< the reused positions OUTSIDE the contiguous prefix: Strata has none
};

/// The accounting identities that must hold when the domains are equivalent, non-overlapping and complete:
///
///     0 <= reused <= matched <= submitted
///     submitted = reused + non_prefix_reused + evaluated
///     replayed <= evaluated
///     work >= evaluated
///
/// They are CHECKED, never enforced: a measurement is never adjusted to make an identity come out right.  A broken
/// identity means the accounting was incomplete (a cancel, a re-read), and the record says so.
struct AccountingCheck {
    bool ok = true;
    const char* problem = "";
};

inline AccountingCheck check_accounting(const TokenAccounting& a, bool complete) {
    AccountingCheck c;
    auto fail = [&](const char* why) { c.ok = false; c.problem = why; };
    if (a.reused >= 0 && a.matched >= 0 && a.reused > a.matched)
        fail("the reused prefix is longer than the matched prefix");
    if (a.matched >= 0 && a.submitted >= 0 && a.matched > a.submitted)
        fail("the matched prefix is longer than the submitted prompt");
    if (a.replayed >= 0 && a.evaluated >= 0 && a.replayed > a.evaluated)
        fail("more replayed positions than evaluated positions");
    if (a.work >= 0 && a.evaluated >= 0 && a.work < a.evaluated)
        fail("less executed work than evaluated positions");
    // The sum identity holds only for a COMPLETE accounting: a cancelled request evaluated part of its prompt,
    // and the rest was never evaluated at all.
    if (complete && a.submitted >= 0 && a.reused >= 0 && a.evaluated >= 0 &&
        a.non_prefix_reused >= 0 && a.reused + a.non_prefix_reused + a.evaluated != a.submitted)
        fail("the submitted prompt is not the reused prefix plus the evaluated positions");
    return c;
}

/// The key names.  They are the wire format; the server reads the same names.  They are written once here so
/// the two halves cannot drift apart over a renamed field.
namespace keys {
constexpr const char* kMatched = "matched";
constexpr const char* kReused = "reused";
constexpr const char* kEvaluated = "evaluated";
constexpr const char* kReplayed = "replayed";
constexpr const char* kWork = "work";
constexpr const char* kDivergent = "divergent";
constexpr const char* kSlot = "slot";
constexpr const char* kInvalidations = "invalidations";
constexpr const char* kEvictions = "evictions";
constexpr const char* kRestoreMs = "restore_ms";
constexpr const char* kLookupMs = "lookup_ms";
constexpr const char* kRestore = "restore";
constexpr const char* kSource = "cache_source";
constexpr const char* kReason = "cache_reason";
constexpr const char* kRequestId = "rid";
}  // namespace keys

/// The restoration's outcome, as one word: what the engine actually did, not what it hoped to do.
inline const char* restore_state(const RequestTelemetry& t) {
    if (!t.restore_attempted) return "none";
    return t.restore_succeeded ? "succeeded" : "failed";
}

/// The key=value pairs for one request, as a single space-separated string, ready to be appended to the DONE
/// line.  A field the engine did not measure is left out entirely, so the server sees no key at all and reports
/// the measurement as unavailable (never as zero).
///
/// The order is fixed, so two runs of the same request produce the same bytes.
inline std::string encode(const RequestTelemetry& t) {
    std::string out;
    auto num = [&](const char* key, int64_t v) {
        if (v < 0) return;                               // -1: not measured, so the key is left out entirely
        out += ' ';
        out += key;
        out += '=';
        out += std::to_string(v);
    };
    if (!t.request_id.empty()) {
        out += ' ';
        out += keys::kRequestId;
        out += '=';
        out += t.request_id;
    }
    num(keys::kMatched, t.matched_prefix);
    num(keys::kReused, t.reused_prefix);
    num(keys::kEvaluated, t.evaluated);
    num(keys::kReplayed, t.replayed);
    num(keys::kWork, t.work);
    if (t.first_divergent >= -1) {
        out += ' ';
        out += keys::kDivergent;
        out += '=';
        out += std::to_string(t.first_divergent);
    }
    if (t.slot >= 0) {
        out += ' ';
        out += keys::kSlot;
        out += '=';
        out += std::to_string(t.slot);
    }
    num(keys::kInvalidations, t.invalidations);
    num(keys::kEvictions, t.evictions);
    if (t.restore_ms >= 0.0) {
        out += ' ';
        out += keys::kRestoreMs;
        out += '=';
        char buf[64];
        std::snprintf(buf, sizeof(buf), "%.1f", t.restore_ms);
        out += buf;
    }
    if (t.lookup_ms >= 0.0) {
        out += ' ';
        out += keys::kLookupMs;
        out += '=';
        char buf[64];
        std::snprintf(buf, sizeof(buf), "%.1f", t.lookup_ms);
        out += buf;
    }
    if (t.restore_attempted) {
        out += ' ';
        out += keys::kRestore;
        out += '=';
        out += restore_state(t);
    }
    if (t.source != "unknown") {
        out += ' ';
        out += keys::kSource;
        out += '=';
        out += t.source;
    }
    if (t.reason != "unknown") {
        out += ' ';
        out += keys::kReason;
        out += '=';
        out += t.reason;
    }
    return out;
}

}  // namespace reqtelemetry
}  // namespace program
}  // namespace strata

#endif  // STRATA_PROGRAM_REQTELEMETRY_HPP
