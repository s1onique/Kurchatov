// src/program/reqtelemetry_test.cpp - the native half of the per-request telemetry
// (ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01), without a GPU.
//
// The engine is the authority for the cache state and the model execution.  What it measures travels on the
// request's own DONE line, in key=value pairs, so the server reads it from the request's own channel - never by
// matching timestamps and never by guessing which request is the newest.
//
// This test drives the ENCODING (include/strata/program/reqtelemetry.hpp) and checks the properties the server
// relies on:
//
//   1. a field the engine did not measure is LEFT OUT, so the server sees no key at all and reports the
//      measurement as unavailable - never as zero;
//   2. a measured zero IS written out (0 is a measured zero; null is "not measured");
//   3. the first divergent token index distinguishes "no mismatch" (-1) from "not measured" (-2);
//   4. the restoration's outcome is reported as what happened: attempted-and-failed is NOT "succeeded";
//   5. the request id is echoed back when there is one, and omitted when there is not;
//   6. the encoding carries no user data: no token ids, no prompt text, no hashes.
//
// The engine's own wiring (the DONE line in src/program/generate.cpp) is not exercised here - that needs the
// engine - but the SERVER's reader is checked against this writer in tools/test_reqtelemetry.py.
#include "strata/program/reqtelemetry.hpp"

#include <cstdio>
#include <cstdlib>
#include <string>

using strata::program::reqtelemetry::RequestTelemetry;

static int failures = 0;

static void check(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

static bool has(const std::string& text, const std::string& key) {
    return text.find(" " + key + "=") != std::string::npos;
}

static std::string value_of(const std::string& text, const std::string& key) {
    const size_t at = text.find(" " + key + "=");
    if (at == std::string::npos) return "";
    const size_t start = at + key.size() + 2;
    const size_t end = text.find(' ', start);
    return end == std::string::npos ? text.substr(start) : text.substr(start, end - start);
}

int main() {
    using namespace strata::program::reqtelemetry;

    {   // 1. a field the engine did not measure is left out entirely
        RequestTelemetry t;
        t.matched_prefix = 40;
        t.reused_prefix = -1;              // not measured
        t.evaluated = 60;
        const std::string s = encode(t);
        check(has(s, "matched"), "a measured field is written");
        check(!has(s, "reused"), "an unmeasured field is left out");
        check(!has(s, "evaluated=0"), "nothing is written as a zero by accident");
        check(value_of(s, "matched") == "40", "the value is the number");
    }

    {   // 2. a measured zero IS written out: 0 is a measured zero, not "not measured"
        RequestTelemetry t;
        t.reused_prefix = 0;               // measured: nothing was reused
        t.evaluated = 0;
        const std::string s = encode(t);
        check(has(s, "reused"), "a measured zero is written out");
        check(value_of(s, "reused") == "0", "the measured zero is 0");
        check(value_of(s, "evaluated") == "0", "the measured zero is 0");
    }

    {   // 3. "no mismatch" and "not measured" are different
        RequestTelemetry none;
        none.first_divergent = -1;         // the sequences agree throughout
        none.matched_prefix = 10;
        const std::string s_none = encode(none);
        check(has(s_none, "divergent"), "a divergence index of -1 is written out");
        check(value_of(s_none, "divergent") == "-1", "-1 means no mismatch");

        RequestTelemetry unknown;
        unknown.first_divergent = -2;      // not measured
        unknown.matched_prefix = 10;
        const std::string s_unknown = encode(unknown);
        check(!has(s_unknown, "divergent"), "an unmeasured divergence index is left out");
    }

    {   // 4. the restoration's outcome is what happened
        RequestTelemetry failed;
        failed.restore_attempted = true;
        failed.restore_succeeded = false;
        failed.restore_ms = 3.5;
        const std::string s = encode(failed);
        check(value_of(s, "restore") == "failed", "a failed restore says failed");
        check(value_of(s, "restore_ms") == "3.5", "the restore's time is written");

        RequestTelemetry ok;
        ok.restore_attempted = true;
        ok.restore_succeeded = true;
        check(value_of(encode(ok), "restore") == "succeeded", "a good restore says succeeded");

        RequestTelemetry none;
        check(!has(encode(none), "restore"), "no restore attempted says nothing about a restore");
    }

    {   // 5. the request id is echoed back when there is one
        RequestTelemetry t;
        t.request_id = "abc123";
        check(value_of(encode(t), "rid") == "abc123", "the request id is echoed back");
        RequestTelemetry none;
        check(!has(encode(none), "rid"), "no request id means no rid key");
    }

    {   // 6. the encoding carries no user data
        RequestTelemetry t;
        t.request_id = "abc123";
        t.matched_prefix = 40;
        t.reused_prefix = 40;
        t.evaluated = 60;
        t.replayed = 10;
        t.work = 70;
        t.first_divergent = 12;
        t.slot = 3;
        t.source = "conversation_cache";
        t.reason = "exact_match";
        const std::string s = encode(t);
        for (const char* forbidden : {"token", "prompt_text", "hash", "ids", "content"}) {
            check(s.find(forbidden) == std::string::npos, "the encoding carries no user data");
        }
        check(value_of(s, "cache_source") == "conversation_cache", "the source is a fixed word");
        check(value_of(s, "cache_reason") == "exact_match", "the reason is a fixed word");
        check(value_of(s, "slot") == "3", "the slot is a number");
    }

    {   // the switch: only "1" turns it on.  The latch itself (enabled()) is read once per process, so the
        // RULE is what this checks; the latch's value is checked by the runner, which starts the binary twice.
        check(!switch_on(nullptr), "an unset switch is off");
        check(switch_on("1"), "STRATA_TELEMETRY=1 turns the telemetry on");
        check(!switch_on("0"), "STRATA_TELEMETRY=0 leaves it off");
        check(!switch_on(""), "an empty switch leaves it off");
        check(!switch_on("true"), "only the exact value 1 turns it on");
        check(!switch_on("2"), "only the exact value 1 turns it on");
    }

    {   // the accounting identities: they are CHECKED, never enforced
        using namespace strata::program::reqtelemetry;
        TokenAccounting a;
        a.submitted = 100; a.matched = 40; a.reused = 40; a.evaluated = 60;
        a.replayed = 0; a.work = 60; a.non_prefix_reused = 0;
        AccountingCheck c = check_accounting(a, true);
        check(c.ok, "a complete accounting closes");

        // the reused prefix longer than the matched prefix: impossible
        TokenAccounting bad = a;
        bad.reused = 80; bad.matched = 40;
        check(!check_accounting(bad, true).ok, "the reused prefix cannot exceed the matched prefix");

        // the matched prefix longer than the submitted prompt: impossible
        TokenAccounting over = a;
        over.matched = 200;
        check(!check_accounting(over, true).ok, "the matched prefix cannot exceed the submitted prompt");

        // more replayed positions than evaluated positions: impossible
        TokenAccounting rep = a;
        rep.replayed = 100; rep.evaluated = 60;
        check(!check_accounting(rep, true).ok, "the replayed positions cannot exceed the evaluated ones");

        // less work than evaluated positions: impossible
        TokenAccounting work = a;
        work.work = 10; work.evaluated = 60;
        check(!check_accounting(work, true).ok, "the work cannot be less than the evaluated positions");

        // the sum identity: it holds only for a COMPLETE accounting
        TokenAccounting gap = a;
        gap.evaluated = 50;
        check(!check_accounting(gap, true).ok, "the submitted prompt must be the reused prefix plus the evaluated");
        check(check_accounting(gap, false).ok, "an incomplete accounting does not claim a broken identity");

        // a matched prefix deeper than the reused one is ALLOWED (the state was not usable)
        TokenAccounting mismatch_state = a;
        mismatch_state.matched = 80; mismatch_state.reused = 40; mismatch_state.evaluated = 60;
        check(check_accounting(mismatch_state, true).ok, "a match deeper than the reuse is legal");
    }

    if (failures == 0) {
        std::printf("reqtelemetry_test: all checks passed\n");
        return 0;
    }
    std::printf("reqtelemetry_test: %d check(s) failed\n", failures);
    return 1;
}
