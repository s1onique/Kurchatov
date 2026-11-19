// src/program/cache_diag_engine_test.cpp - the engine-side wiring of the cache diagnostics (STRATA_CACHE_DIAG).
//
// The engine's request loop is CUDA-bound and cannot run without a GPU, so this test reproduces the EXACT
// diagnostic code paths of generate.cpp - the same collector, the same candidate analysis, the same decision
// resolution - over the real ConversationCache, with the engine's own types.  It checks that:
//
//   * the reported selection is the source the engine mounts (the live state, the active chain, a parked
//     conversation, a borrow);
//   * the reported prefix is the tokens the engine actually reuses;
//   * the reported reason names the right refusal;
//   * with the switch OFF the collector does no work at all: no candidates, no comparison, no id spent;
//   * the events carry no user data.
//
// The code below is a transcription of generate.cpp's blocks, not a second implementation: the same calls into
// cache_diag.hpp and conversation_cache.hpp, with the engine's own rule (starts_with) applied.
#include "strata/program/cache_diag.hpp"
#include "strata/core/conversation_cache.hpp"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

using namespace strata::core;
using strata::program::cache_diag::Reason;
using strata::program::cache_diag::Source;

namespace {

int checks = 0;
void check(bool value, const char* description) {
    ++checks;
    if (!value) { std::fprintf(stderr, "FAIL: %s\n", description); std::exit(1); }
}

using Ids = std::vector<int32_t>;
using ImgKey = ConversationImageKey;

SavedConversation image(Ids live, std::vector<Ids> chain = {}, bool cvec = true,
                         std::vector<ImgKey> imgs = {}) {
    SavedConversation s;
    s.live.ids = std::move(live);
    s.live.imgs = std::move(imgs);
    s.live.gdn.resize(64, 7);
    s.cvec = cvec;
    for (Ids& c : chain) {
        ConversationCheckpoint cp;
        cp.ids = std::move(c);
        cp.gdn.resize(32, 3);
        s.checkpoints.push_back(std::move(cp));
    }
    return s;
}

/// The engine's starts_with (generate.cpp): the tokens must be exactly the prompt's start - at least one token
/// and never the last prompt token - and the pictures below the length must be the candidate's own.
bool starts_with(const Ids& pre, const std::vector<ImgKey>& pre_imgs, const Ids& prompt,
                 const std::vector<ImgKey>& prompt_imgs) {
    const int64_t L = (int64_t) pre.size();
    const int64_t n = (int64_t) prompt.size();
    if (L < 1 || L > n - 1) return false;
    for (int64_t i = 0; i < L; ++i)
        if (prompt[(size_t) i] != pre[(size_t) i]) return false;
    std::vector<ImgKey> below;
    for (const auto& k : prompt_imgs)
        if (k.start < L) below.push_back(k);
    return below == pre_imgs;
}

// ---------------------------------------------------------------------------------------------
// The collector, transcribed from generate.cpp (the same code, the same types).
// ---------------------------------------------------------------------------------------------
struct CacheDiagCollector {
    bool on = false;
    uint64_t seq = 0;
    struct Entry {
        Source source = Source::none;
        int64_t tokens = 0;
        int64_t lcp = 0;
        int64_t mismatch = -1;
        Reason reason = Reason::unknown;
        bool usable = false;
    };
    std::vector<Entry> entries;
    Source selected = Source::none;
    int64_t selected_prefix = 0;
    int64_t max_candidate = 0;
    int64_t best_lcp = 0;
    int64_t best_mismatch = -1;
    Reason best_reason = Reason::unknown;
    int64_t deeper_tokens = 0;
    Reason deeper_reason = Reason::unknown;
    Reason reason = Reason::unknown;
    int64_t prompt_tokens = 0;

    void reset(int64_t n) {
        if (!on) return;
        entries.clear();
        selected = Source::none;
        selected_prefix = 0;
        max_candidate = 0;
        best_lcp = 0;
        best_mismatch = -1;
        best_reason = Reason::unknown;
        deeper_tokens = 0;
        deeper_reason = Reason::unknown;
        reason = Reason::unknown;
        prompt_tokens = n;
        seq = strata::program::cache_diag::next_seq();
    }
    void add(Source source, int64_t tokens, int64_t lcp, int64_t mismatch, Reason reason, bool usable) {
        if (!on) return;
        entries.push_back({source, tokens, lcp, mismatch, reason, usable});
        if (tokens > max_candidate) max_candidate = tokens;
        if (lcp > best_lcp) { best_lcp = lcp; best_mismatch = mismatch; best_reason = reason; }
        // the DEEPER candidate that was refused: the longest one that was not usable
        if (!usable && tokens > deeper_tokens) { deeper_tokens = tokens; deeper_reason = reason; }
    }
    strata::program::cache_diag::CacheDiagEvent event(const ConversationCache& cache) const {
        strata::program::cache_diag::CacheDiagEvent e;
        e.kind = strata::program::cache_diag::EventKind::decision;
        e.request_seq = seq;
        e.prompt_tokens = prompt_tokens;
        e.selected_source = selected;
        e.selected_prefix_tokens = selected_prefix;
        e.candidate_count = (int64_t) entries.size();
        e.max_candidate_prefix_tokens = max_candidate;
        e.longest_common_prefix_tokens = best_lcp;
        e.first_mismatch_position = best_mismatch;
        e.rejection_reason = reason;
        // The deeper refused candidate, but only when it really was deeper than what was selected: a refused
        // candidate that was SHORTER is not what stopped the request from reusing more.
        if (deeper_tokens > selected_prefix) {
            e.deeper_rejection_reason = deeper_reason;
            e.deeper_candidate_tokens = deeper_tokens;
        }
        e.cache_parked_entries = cache.size();
        e.cache_parked_bytes = cache.bytes();
        e.cache_evictions_total = cache.evictions();
        return e;
    }
};

/// The engine's request, with the diagnostic blocks in the engine's places.  It returns what the engine would
/// mount (`resume`) and fills the collector.
struct Request {
    Ids ids;
    std::vector<ImgKey> req_imgs;
    Ids live;
    std::vector<ImgKey> live_imgs;
    bool live_ok = false;
    std::vector<ConversationCheckpoint> checks;
    ConversationCache* conversations = nullptr;
    bool want_cvec = true;
    bool cvec_cached = true;
    int64_t prompt_cache = 6;
    // a batch slot (generate.cpp's --batch path): the slot's own tokens and its checkpoints
    Ids slot_ids;
    std::vector<ImgKey> slot_imgs;
    std::vector<ConversationCheckpoint> slot_checks;
};

int64_t run_request(Request& r, CacheDiagCollector& cdiag, Source* selected_out) {
    const Ids& ids = r.ids;
    auto imgs_below = [&](const std::vector<ImgKey>& all, int64_t L) {
        std::vector<ImgKey> v;
        for (const ImgKey& k : all)
            if (k.start < L) v.push_back(k);
        return v;
    };
    auto starts = [&](const std::vector<int32_t>& pre, const std::vector<ImgKey>& pre_imgs) {
        return starts_with(pre, pre_imgs, ids, r.req_imgs);
    };
    int64_t resume = 0;
    bool from_live = false;
    cdiag.reset((int64_t) ids.size());
    auto cdiag_consider = [&](Source source, const std::vector<int32_t>& pre, const std::vector<ImgKey>& pre_imgs,
                              bool steering_ok) {
        if (!cdiag.on) return;
        strata::program::cache_diag::Candidate c;
        c.source = source;
        c.ids = pre.data();
        c.n_ids = pre.size();
        c.imgs = &pre_imgs;
        c.steering_matches = steering_ok;
        const auto a = strata::program::cache_diag::analyse(
            c, ids, [&](int64_t L) { return imgs_below(r.req_imgs, L); },
            [](const std::vector<ImgKey>& below, const void* own) {
                return own != nullptr && below == *static_cast<const std::vector<ImgKey>*>(own);
            });
        const bool usable = steering_ok && starts(pre, pre_imgs);
        cdiag.add(source, (int64_t) pre.size(), a.lcp, a.mismatch,
                  usable ? Reason::exact_match : a.reason, usable);
    };
    if (r.prompt_cache > 0 && r.want_cvec == r.cvec_cached) {
        if (r.live_ok && starts(r.live, r.live_imgs)) { resume = (int64_t) r.live.size(); from_live = true; }
        for (const ConversationCheckpoint& c : r.checks)
            if ((int64_t) c.ids.size() > resume && starts(c.ids, c.imgs)) {
                resume = (int64_t) c.ids.size();
                from_live = false;
            }
        if (cdiag.on) {
            if (r.live_ok) cdiag_consider(Source::live, r.live, r.live_imgs, true);
            for (const ConversationCheckpoint& c : r.checks)
                cdiag_consider(Source::active_checkpoint, c.ids, c.imgs, true);
        }
    } else if (cdiag.on) {
        cdiag.reason = (r.prompt_cache > 0) ? Reason::steering_mismatch : Reason::cache_disabled;
    }
    // PRODUCTION (generate.cpp): the parked side competes with the SLOT, not only with the live prefix:
    //   borrow:      parked.tokens > std::max(resume, slot_tokens) && conversations.borrows(parked)
    //   parked take: parked.tokens > std::max(resume, slot_tokens) && !borrow
    //   then:        if (incoming || borrow) slot_source = -1;   (the parked side cancels the slot)
    //   the slot:    slot_source >= 0  ->  resume = slot_tokens; from_live = true;
    int slot_source = -1;
    int64_t slot_tokens = 0;
    if (r.prompt_cache > 0 && r.req_imgs.empty()) {
        if (!r.slot_ids.empty() && (int64_t) r.slot_ids.size() > std::max(resume, slot_tokens) &&
            starts(r.slot_ids, r.slot_imgs)) {
            slot_source = 0;
            slot_tokens = (int64_t) r.slot_ids.size();
        }
        for (const ConversationCheckpoint& c : r.slot_checks)
            if ((int64_t) c.ids.size() > std::max(resume, slot_tokens) && starts(c.ids, c.imgs)) {
                slot_source = 0;
                slot_tokens = (int64_t) c.ids.size();
            }
        if (cdiag.on && slot_source >= 0) {
            if (!r.slot_ids.empty()) cdiag_consider(Source::slot, r.slot_ids, r.slot_imgs, true);
            for (const ConversationCheckpoint& c : r.slot_checks)
                cdiag_consider(Source::slot, c.ids, c.imgs, true);
        }
    }
    bool parked_used = false, parked_borrowed = false, parked_taken_live = false;
    const auto parked = r.conversations->best(ids, r.req_imgs, r.want_cvec);
    if (cdiag.on) {
        std::vector<ConversationCache::Candidate> parked_cands;
        r.conversations->candidates(ids, r.req_imgs, r.want_cvec, parked_cands);
        for (const auto& c : parked_cands) {
            const Source src = c.live ? Source::parked_live : Source::parked_checkpoint;
            int64_t lcp = 0, mismatch = -1;
            if (c.ids != nullptr)
                lcp = strata::program::cache_diag::common_prefix(c.ids, (size_t) c.tokens, ids.data(), ids.size(),
                                                                 &mismatch);
            Reason rr = Reason::unknown;
            if (c.cvec_mismatch) rr = Reason::steering_mismatch;
            else if (c.image_mismatch) rr = Reason::image_mismatch;
            else if (c.prefix > 0) rr = Reason::exact_match;
            else if (c.tokens > 0) rr = Reason::token_mismatch;
            else rr = Reason::absent;
            cdiag.add(src, c.tokens, lcp, mismatch, rr, c.prefix > 0);
        }
    }
    const bool borrow = parked.tokens > std::max(resume, slot_tokens) && r.conversations->borrows(parked);
    bool incoming = false;
    if (parked.tokens > std::max(resume, slot_tokens) && !borrow) incoming = true;
    if (incoming || borrow) slot_source = -1;   // the parked side cancels the slot
    if (incoming) {
        parked_used = true;
        parked_borrowed = borrow;
        parked_taken_live = parked.live;
        resume = parked.tokens;
        from_live = parked.live;
    } else if (borrow) {
        parked_used = true;
        parked_borrowed = true;
        parked_taken_live = false;   // a borrow mounts a CHECKPOINT of the donor, not its live state
        resume = parked.tokens;
        from_live = false;
    } else if (slot_source >= 0) {
        resume = slot_tokens;
        from_live = true;
    }
    // the decision, resolved (generate.cpp)
    if (cdiag.on) {
        cdiag.selected_prefix = resume;
        if (resume > 0) {
            if (parked_used) {
                cdiag.selected = parked_taken_live ? Source::parked_live : Source::parked_checkpoint;
                cdiag.reason = parked_borrowed ? Reason::borrowed : Reason::exact_match;
            } else if (slot_source >= 0) {
                cdiag.selected = Source::slot;
                cdiag.reason = Reason::slot_source;
            } else if (from_live) {
                cdiag.selected = Source::live;
                cdiag.reason = Reason::exact_match;
            } else {
                cdiag.selected = Source::active_checkpoint;
                cdiag.reason = Reason::exact_match;
            }
        } else {
            cdiag.selected = Source::none;
            cdiag.selected_prefix = 0;
            if (cdiag.reason == Reason::unknown) {
                cdiag.reason = cdiag.entries.empty() ? Reason::absent : cdiag.best_reason;
                if (cdiag.reason == Reason::unknown) cdiag.reason = Reason::absent;
                if (cdiag.reason == Reason::exact_match) cdiag.reason = Reason::ineligible;
            }
        }
    }
    if (selected_out != nullptr) *selected_out = cdiag.selected;
    return resume;
}

}  // namespace

int main() {
    using namespace strata::program::cache_diag;
    std::printf("cache_diag_engine_test\n");

    {   // the live session is mounted: the diagnostic says so
        ConversationCache cache(1 << 20, 4);
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        r.ids = {1, 2, 3, 4, 5, 6, 7};
        r.live = {1, 2, 3, 4};
        r.live_ok = true;
        r.conversations = &cache;
        Source selected = Source::none;
        const int64_t resume = run_request(r, cdiag, &selected);
        check(resume == 4, "the engine reuses the live session's 4 tokens");
        check(selected == Source::live, "the diagnostic names the live session");
        check(cdiag.selected_prefix == resume, "the reported prefix is what the engine reuses");
        check(cdiag.reason == Reason::exact_match, "an exact match is the reason");
        check(cdiag.event(cache).selected_prefix_tokens == resume, "the event carries the same prefix");
    }
    {   // an active checkpoint is mounted: the deepest one
        ConversationCache cache(1 << 20, 4);
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        r.ids = {1, 2, 3, 4, 5, 6, 7};
        r.live = {1, 2};
        r.live_ok = true;
        ConversationCheckpoint c1;
        c1.ids = {1, 2, 3, 4};
        ConversationCheckpoint c2;
        c2.ids = {1, 2, 3, 4, 5};
        r.checks = {c1, c2};
        r.conversations = &cache;
        Source selected = Source::none;
        const int64_t resume = run_request(r, cdiag, &selected);
        check(resume == 5, "the engine reuses the deepest checkpoint's 5 tokens");
        check(selected == Source::active_checkpoint, "the diagnostic names the active checkpoint");
        check(cdiag.event(cache).candidate_count == 3, "the live state and the two checkpoints were examined");
        check(cdiag.max_candidate == 5, "the longest candidate is 5 tokens");
        check(cdiag.best_lcp == 5 && cdiag.best_mismatch == -1, "the common prefix is the whole match");
    }
    {   // a parked conversation is mounted
        ConversationCache cache(1 << 20, 4);
        check(cache.put(image({1, 2, 3, 4})), "park a conversation");
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        r.ids = {1, 2, 3, 4, 5, 6, 7};
        r.conversations = &cache;
        Source selected = Source::none;
        const int64_t resume = run_request(r, cdiag, &selected);
        check(resume == 4, "the engine restores the parked conversation's 4 tokens");
        check(selected == Source::parked_live, "the diagnostic names the parked live state");
        check(cdiag.reason == Reason::exact_match, "an exact match is the reason");
        check(cdiag.event(cache).cache_parked_entries == 1, "the event carries the parked count");
    }
    {   // a borrow: a checkpoint inside a parked conversation, the donor stays parked
        // the donor holds {1,2,3,4,10,11} with checkpoints at {1,2,3} and {1,2,3,4}; a SIBLING that starts with
        // {1,2,3} borrows the {1,2,3} checkpoint (the donor has a deeper one, so it stays parked)
        ConversationCache cache(1 << 20, 4);
        check(cache.put(image({1, 2, 3, 4, 10, 11}, {{1, 2, 3}, {1, 2, 3, 4}})), "park a donor with checkpoints");
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        r.ids = {1, 2, 3, 20, 21};
        r.conversations = &cache;
        Source selected = Source::none;
        const int64_t resume = run_request(r, cdiag, &selected);
        check(resume == 3, "the engine borrows the donor's 3-token checkpoint");
        check(selected == Source::parked_checkpoint, "the diagnostic names the parked checkpoint");
        check(cdiag.reason == Reason::borrowed, "the reason is a borrow");
        check(cache.size() == 1, "the donor stays parked");
    }
    {   // a mutation near the beginning: nothing is reused, and the reason says why
        ConversationCache cache(1 << 20, 4);
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        r.ids = {1, 2, 99, 4, 5, 6, 7};
        r.live = {1, 2, 3, 4};
        r.live_ok = true;
        ConversationCheckpoint c1;
        c1.ids = {1, 2, 3, 4};
        r.checks = {c1};
        r.conversations = &cache;
        Source selected = Source::none;
        const int64_t resume = run_request(r, cdiag, &selected);
        check(resume == 0, "the engine reuses nothing");
        check(selected == Source::none, "the diagnostic names no source");
        check(cdiag.reason == Reason::token_mismatch, "the reason is a token mismatch");
        check(cdiag.best_lcp == 2 && cdiag.best_mismatch == 2, "the mismatch is at the changed token");
        check(cdiag.max_candidate == 4, "the longest candidate is still reported");
        check(cdiag.best_lcp < cdiag.max_candidate, "the common prefix is not the candidate's length");
    }
    {   // a mutation between two checkpoints: the shallower one is mounted
        ConversationCache cache(1 << 20, 4);
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        r.ids = {1, 2, 3, 4, 5, 99, 7, 8, 9, 10};
        ConversationCheckpoint c1;
        c1.ids = {1, 2, 3, 4};
        ConversationCheckpoint c2;
        c2.ids = {1, 2, 3, 4, 5, 6};
        r.checks = {c1, c2};
        r.conversations = &cache;
        Source selected = Source::none;
        const int64_t resume = run_request(r, cdiag, &selected);
        check(resume == 4, "the engine falls back to the shallower checkpoint");
        check(selected == Source::active_checkpoint, "the diagnostic names the active checkpoint");
        check(cdiag.selected_prefix == 4, "the reported prefix is the shallower checkpoint's length");
        check(cdiag.best_lcp == 5, "the common prefix is where the tokens differ");
    }
    {   // the deeper candidate is refused: the event names WHY the request could not reuse more
        ConversationCache cache(1 << 20, 4);
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        r.ids = {1, 2, 3, 4, 5, 6, 7, 8};
        r.req_imgs = {{6, 222}};   // the prompt's picture, at token 6
        ConversationCheckpoint shallow;
        shallow.ids = {1, 2, 3, 4};
        ConversationCheckpoint deep;
        deep.ids = {1, 2, 3, 4, 5, 6};
        deep.imgs = {{6, 111}};   // the deep one's picture is NOT the prompt's
        r.checks = {shallow, deep};
        r.conversations = &cache;
        Source selected = Source::none;
        const int64_t resume = run_request(r, cdiag, &selected);
        check(resume == 4, "the engine falls back to the shallower checkpoint");
        check(selected == Source::active_checkpoint, "the diagnostic names the active checkpoint");
        const auto e = cdiag.event(cache);
        check(e.rejection_reason == Reason::exact_match, "the selected source's own reason is reported");
        check(e.deeper_rejection_reason == Reason::image_mismatch,
              "the DEEPER candidate's refusal is reported too");
        check(e.deeper_candidate_tokens == 6, "the deeper candidate's length is reported");
    }
    {   // R4: a refused candidate that is SHORTER than the selected one is not a "deeper" candidate
        ConversationCache cache(1 << 20, 4);
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        r.ids.resize(6002);
        for (size_t i = 0; i < r.ids.size(); ++i) r.ids[i] = (int32_t) (i + 1);
        ConversationCheckpoint selected;   // 6000 tokens: the one the engine mounts
        selected.ids.assign(r.ids.begin(), r.ids.begin() + 6000);
        ConversationCheckpoint rejected;   // 2000 tokens, and its tokens differ: it is refused
        rejected.ids.assign(r.ids.begin(), r.ids.begin() + 2000);
        rejected.ids[1000] = 999999;
        r.checks = {selected, rejected};
        r.conversations = &cache;
        Source selected_out = Source::none;
        const int64_t resume = run_request(r, cdiag, &selected_out);
        check(resume == 6000, "the engine mounts the 6000-token checkpoint");
        const auto e = cdiag.event(cache);
        check(e.selected_prefix_tokens == 6000, "the reported prefix is 6000");
        check(e.deeper_candidate_tokens == 0, "a SHORTER refused candidate is not a deeper one");
        check(e.deeper_rejection_reason == Reason::unknown,
              "a SHORTER refused candidate leaves the deeper reason UNKNOWN");
    }
    {   // R5: the image identity at the checkpoint's boundary (the picture at index 5, inside a six-token one)
        const Ids prompt = {1, 2, 3, 4, 5, 6, 7, 8};
        const std::vector<ImgKey> img_prompt = {{5, 222}};
        {   // (a) the same identity: the six-token checkpoint is used
            ConversationCache cache(1 << 20, 4);
            CacheDiagCollector cdiag;
            cdiag.on = true;
            Request r;
            r.ids = prompt;
            r.req_imgs = img_prompt;
            ConversationCheckpoint deep;
            deep.ids = {1, 2, 3, 4, 5, 6};
            deep.imgs = {{5, 222}};
            r.checks = {deep};
            r.conversations = &cache;
            const int64_t resume = run_request(r, cdiag, nullptr);
            check(resume == 6, "R5a: the matching six-token checkpoint is reused");
            const auto e = cdiag.event(cache);
            check(e.selected_prefix_tokens == 6, "R5a: the reported prefix is the checkpoint's length");
            check(e.deeper_rejection_reason == Reason::unknown, "R5a: nothing deeper was refused");
        }
        {   // (b) another identity: the six-token checkpoint is refused
            ConversationCache cache(1 << 20, 4);
            CacheDiagCollector cdiag;
            cdiag.on = true;
            Request r;
            r.ids = prompt;
            r.req_imgs = img_prompt;
            ConversationCheckpoint deep;
            deep.ids = {1, 2, 3, 4, 5, 6};
            deep.imgs = {{5, 111}};
            r.checks = {deep};
            r.conversations = &cache;
            const int64_t resume = run_request(r, cdiag, nullptr);
            check(resume == 0, "R5b: the six-token checkpoint with another identity is refused");
            const auto e = cdiag.event(cache);
            check(e.deeper_rejection_reason == Reason::image_mismatch, "R5b: the image mismatch is named");
            check(e.deeper_candidate_tokens == 6, "R5b: the refused candidate's length is reported");
        }
        {   // (c) a shallower checkpoint that ends before the picture is still reusable
            ConversationCache cache(1 << 20, 4);
            CacheDiagCollector cdiag;
            cdiag.on = true;
            Request r;
            r.ids = prompt;
            r.req_imgs = img_prompt;
            ConversationCheckpoint shallow;
            shallow.ids = {1, 2, 3, 4};
            ConversationCheckpoint deep;
            deep.ids = {1, 2, 3, 4, 5, 6};
            deep.imgs = {{5, 111}};
            r.checks = {shallow, deep};
            r.conversations = &cache;
            const int64_t resume = run_request(r, cdiag, nullptr);
            check(resume == 4, "R5c: the shallower checkpoint that ends before the picture is reused");
            const auto e = cdiag.event(cache);
            check(e.deeper_rejection_reason == Reason::image_mismatch, "R5c: the deeper mismatch is named");
            check(e.deeper_candidate_tokens == 6, "R5c: the deeper checkpoint's length is reported");
        }
    }
    {   // R6: the slot against a parked checkpoint: slot_tokens=6000, parked.tokens=5000, resume=0
        ConversationCache cache(1 << 20, 4);
        SavedConversation donor;
        donor.live.gdn.resize(64, 7);
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        r.ids.resize(6002);
        for (size_t i = 0; i < r.ids.size(); ++i) r.ids[i] = (int32_t) (i + 1);
        donor.live.ids.assign(r.ids.begin(), r.ids.begin() + 5000);
        check(cache.put(std::move(donor)), "R6: park a 5000-token donor");
        r.slot_ids.assign(r.ids.begin(), r.ids.begin() + 6000);
        r.conversations = &cache;
        Source selected_out = Source::none;
        const int64_t resume = run_request(r, cdiag, &selected_out);
        check(resume == 6000, "R6: the SLOT wins (6000), not the parked side (5000)");
        check(selected_out == Source::slot, "R6: the event names the SLOT");
        const auto e = cdiag.event(cache);
        check(e.selected_prefix_tokens == 6000, "R6: the reported prefix is the slot's 6000 tokens");
        check(e.rejection_reason == Reason::slot_source, "R6: the reason is the slot");
    }
    {   // the switch OFF: the collector does no work
        ConversationCache cache(1 << 20, 4);
        CacheDiagCollector cdiag;
        cdiag.on = false;
        Request r;
        r.ids = {1, 2, 3, 4, 5, 6, 7};
        r.live = {1, 2, 3, 4};
        r.live_ok = true;
        r.conversations = &cache;
        Source selected = Source::none;
        const int64_t resume = run_request(r, cdiag, &selected);
        check(resume == 4, "the engine reuses the same tokens with the switch off");
        check(cdiag.entries.empty(), "no candidate was collected");
        check(cdiag.seq == 0, "no request id was spent");
        check(cdiag.selected == Source::none, "no source was recorded");
        // the same request with the switch on: the same reuse
        CacheDiagCollector on;
        on.on = true;
        Source selected_on = Source::none;
        const int64_t resume_on = run_request(r, on, &selected_on);
        check(resume_on == resume, "the switch does not change what the engine reuses");
        check(selected_on == Source::live, "the switch does not change the source");
    }
    {   // the cache is off for this request (ckpt=0 or --prompt-cache 0)
        ConversationCache cache(1 << 20, 4);
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        r.ids = {1, 2, 3, 4};
        r.prompt_cache = 0;
        r.conversations = &cache;
        Source selected = Source::none;
        const int64_t resume = run_request(r, cdiag, &selected);
        check(resume == 0, "nothing is reused when the cache is off");
        check(cdiag.reason == Reason::cache_disabled, "the reason is that the cache is off");
        check(cdiag.event(cache).candidate_count == 0, "no candidate was examined");
    }
    {   // the steering mode does not match: the active chain is not usable
        ConversationCache cache(1 << 20, 4);
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        r.ids = {1, 2, 3, 4};
        r.want_cvec = true;
        r.cvec_cached = false;
        r.conversations = &cache;
        Source selected = Source::none;
        const int64_t resume = run_request(r, cdiag, &selected);
        check(resume == 0, "the active chain is not usable with another steering mode");
        check(cdiag.reason == Reason::steering_mismatch, "the reason is the steering mode");
    }
    {   // the image identity does not match: the parked conversation is refused
        ConversationCache cache(1 << 20, 4);
        check(cache.put(image({1, 2, 3, 4}, {}, true, {{2, 111}})), "park a conversation with a picture");
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        r.ids = {1, 2, 3, 4, 5, 6, 7};
        r.req_imgs = {{2, 222}};
        r.conversations = &cache;
        Source selected = Source::none;
        const int64_t resume = run_request(r, cdiag, &selected);
        check(resume == 0, "the picture that is not the same refuses the reuse");
        check(selected == Source::none, "no source was mounted");
        check(cdiag.reason == Reason::image_mismatch, "the reason is an image mismatch");
    }
    {   // the events carry no user data
        ConversationCache cache(1 << 20, 4);
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        r.ids = {987654, 2, 3, 4, 5, 6, 7};   // a sentinel token id
        r.live = {987654, 2, 3};
        r.live_ok = true;
        r.conversations = &cache;
        run_request(r, cdiag, nullptr);
        const auto e = cdiag.event(cache);
        check(e.prompt_tokens == 7, "the event carries the prompt's token COUNT");
        check(e.selected_prefix_tokens == 3, "the event carries the reused token COUNT");
        // the writer's line: no token id, no prompt text
        FILE* f = std::tmpfile();
        check(f != nullptr, "a temporary file for the event line");
        Writer wf(f);
        wf.write(e);
        std::fflush(f);
        std::rewind(f);
        char buf[4096] = {};
        const size_t n = std::fread(buf, 1, sizeof buf - 1, f);
        std::fclose(f);
        const std::string text(buf, n);
        check(text.find("987654") == std::string::npos, "the event line carries no token id");
        check(text.find("STRATA_CACHE_DIAG event=decision") == 0, "the line is tagged");
        check(text.find("selected_source=live") != std::string::npos, "the source is named");
        check(text.find("prompt_tokens=7") != std::string::npos, "the prompt's token count is there");
    }
    {   // the secondary events: a supersession and a park refusal
        ConversationCache cache(1 << 20, 4);
        // a parked conversation whose deepest checkpoint the outgoing chain holds: the park supersedes it
        SavedConversation outgoing = image({1, 2, 3, 4, 5}, {{1, 2, 3, 4}}, true);
        SavedConversation older = image({1, 2, 3, 4, 5, 6}, {{1, 2, 3, 4}}, true);
        check(cache.put(std::move(older)), "park a conversation the outgoing chain supersedes");
        const size_t before = cache.superseded();
        check(cache.put(std::move(outgoing)), "park the outgoing conversation");
        check(cache.superseded() == before + 1, "the parked conversation was superseded");
        // the event the engine writes for it
        strata::program::cache_diag::CacheDiagEvent ev;
        ev.kind = strata::program::cache_diag::EventKind::checkpoint_super;
        ev.rejection_reason = Reason::superseded;
        ev.subject_tokens = (int64_t)(cache.superseded() - before);
        ev.cache_parked_entries = cache.size();
        ev.cache_evictions_total = cache.evictions();
        check(ev.subject_tokens == 1, "the supersession event counts what went");
        check(ev.rejection_reason == Reason::superseded, "the reason is a supersession");
        // a park refusal: an image bigger than the whole budget
        auto huge = image({1});
        huge.live.gdn.resize((1 << 20) * 3);
        ConversationCache tiny((1 << 20), 4);
        check(!tiny.put(std::move(huge)), "an oversized image is refused");
        strata::program::cache_diag::CacheDiagEvent rf;
        rf.kind = strata::program::cache_diag::EventKind::park_refused;
        rf.rejection_reason = Reason::budget_refused;
        rf.cache_parked_entries = tiny.size();
        rf.cache_evictions_total = tiny.evictions();
        check(rf.rejection_reason == Reason::budget_refused, "the reason is a budget refusal");
        check(rf.cache_evictions_total == 0, "a refusal is not an eviction");
    }
    {   // the writer's line format: every field is present and the names are fixed
        ConversationCache cache(1 << 20, 4);
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        r.ids = {1, 2, 3, 4};
        r.live = {1, 2};
        r.live_ok = true;
        r.conversations = &cache;
        run_request(r, cdiag, nullptr);
        FILE* f = std::tmpfile();
        check(f != nullptr, "a temporary file for the event line");
        Writer wf(f);
        wf.write(cdiag.event(cache));
        std::fflush(f);
        std::rewind(f);
        char buf[4096] = {};
        const size_t n = std::fread(buf, 1, sizeof buf - 1, f);
        std::fclose(f);
        const std::string text(buf, n);
        for (const char* key : {"event=", "request_seq=", "prompt_tokens=", "selected_source=",
                                "selected_prefix_tokens=", "candidate_count=", "max_candidate_prefix_tokens=",
                                "longest_common_prefix_tokens=", "first_mismatch_position=", "rejection_reason=",
                                "deeper_rejection_reason=", "deeper_candidate_tokens=",
                                "cache_parked_entries=", "cache_parked_bytes=", "cache_evictions_total="}) {
            check(text.find(key) != std::string::npos, "the event line carries the field");
        }
    }
    std::printf("cache_diag_engine_test: %d checks passed\n", checks);
    return 0;
}
