// src/program/reqtelemetry_roundtrip.cpp - the engine's telemetry writer, on its own: what the engine puts on a
// request's DONE line (ACT-STRATA-REQUEST-CAUSAL-TELEMETRY-01).
//
// The server reads those key=value pairs (serve/server.py's _parse_done).  This program writes one DONE line
// with the repository's own writer (include/strata/program/reqtelemetry.hpp), so the reader and the writer are
// checked against each other and cannot drift apart.
//
// With the switch off it writes the DONE line WITHOUT the telemetry (the default path: byte-identical to the
// release's); with STRATA_TELEMETRY=1 it writes the telemetry too.
#include "strata/program/reqtelemetry.hpp"

#include <cstdio>
#include <string>

int main() {
    using namespace strata::program::reqtelemetry;
    RequestTelemetry t;
    t.request_id = "abc123";
    t.matched_prefix = 60;
    t.reused_prefix = 60;
    t.evaluated = 40;
    t.replayed = 0;
    t.work = 40;
    t.first_divergent = -1;
    t.slot = 2;
    t.restore_attempted = true;
    t.restore_succeeded = true;
    t.restore_ms = 3.5;
    t.lookup_ms = 1.25;
    t.source = "live";
    t.reason = "EXACT_MATCH";
    std::printf("enabled=%d\n", enabled() ? 1 : 0);
    std::printf("DONE 7 100 41.5 210.0 stop 24 31 60 9 10 1 2 1.5 40 0%s\n", encode(t).c_str());
    return 0;
}
