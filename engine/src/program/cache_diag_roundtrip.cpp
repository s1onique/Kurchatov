// tests/cache_diag_roundtrip.cpp - the engine's writer, on its own: what the engine writes for one decision.
//
// The server reads the engine's STRATA_CACHE_DIAG lines (serve/server.py's ConvCacheLog).  This program writes
// one such line with the repository's own writer (include/strata/program/cache_diag.hpp), so the reader and the
// writer are checked against each other and cannot drift apart.
//
// With the switch off it writes nothing (the default path); with STRATA_CACHE_DIAG=1 it writes the line.
#include "strata/program/cache_diag.hpp"

#include <cstdio>

int main() {
    using namespace strata::program::cache_diag;
    std::printf("enabled=%d\n", enabled() ? 1 : 0);
    if (!enabled()) return 0;
    CacheDiagEvent e;
    e.kind = EventKind::decision;
    e.request_seq = next_seq();
    e.prompt_tokens = 100;
    e.selected_source = Source::live;
    e.selected_prefix_tokens = 60;
    e.candidate_count = 2;
    e.max_candidate_prefix_tokens = 60;
    e.longest_common_prefix_tokens = 60;
    e.first_mismatch_position = -1;
    e.rejection_reason = Reason::exact_match;
    Sink::instance().record(e);
    return 0;
}
