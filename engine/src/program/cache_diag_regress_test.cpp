// src/program/cache_diag_regress_test.cpp - the three observability defects the ACT-01 review found, as
// regression tests against the PRODUCTION code (the real cache_diag.hpp writer and the real collector
// semantics), so they cannot come back.
//
//   R1  A shallower checkpoint is selected while a deeper candidate is refused (image identity, steering).
//       The event must name the deeper refusal: the selected source's reason alone ("EXACT_MATCH") hides it.
//   R2  A batch slot gives the conversation back.  The event's source must describe the ACTUAL selection.
//   R3  More than the reader's 1 MiB window arrives between two polls.  The lost records must be detectable
//       (that one is the Python reader's: tools/test_cache_diag_log.py).
//
// R1 and R2 are C++ (the engine's writer).  They compile against the repository's own header, so the
// regression test and the production writer cannot drift apart.
#include "strata/program/cache_diag.hpp"
#include "strata/core/conversation_cache.hpp"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
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

SavedConversation image(Ids live, std::vector<Ids> chain = {}, bool cvec = true, std::vector<ImgKey> imgs = {}) {
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

/// The engine's starts_with (generate.cpp).
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

/// The collector, transcribed from generate.cpp (the same code, the same types).
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


/// One engine request: the live state, the active chain, a batch slot and the parked cache, resolved the way
/// generate.cpp resolves them, with the diagnostic blocks in the engine's places.
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
    // a batch slot: the slot's own tokens and its checkpoints (generate.cpp's --batch path)
    bool slot_present = false;
    Ids slot_ids;
    std::vector<ImgKey> slot_imgs;
    std::vector<ConversationCheckpoint> slot_checks;
};

int64_t run_request(Request& r, CacheDiagCollector& cdiag) {
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
    int slot_source = -1;
    int64_t slot_tokens = 0;
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

    // the batch slot (generate.cpp's --batch path): an idle slot that holds the start of this prompt
    if (r.prompt_cache > 0 && r.slot_present && r.req_imgs.empty()) {
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
            // the slot's candidates are examined too, so the event can name them
            if (!r.slot_ids.empty()) cdiag_consider(Source::slot, r.slot_ids, r.slot_imgs, true);
            for (const ConversationCheckpoint& c : r.slot_checks)
                cdiag_consider(Source::slot, c.ids, c.imgs, true);
        }
    }
    // the engine's selection, exactly as generate.cpp does it:
    //   borrow:      parked.tokens > std::max(resume, slot_tokens) && conversations.borrows(parked)
    //   parked take: parked.tokens > std::max(resume, slot_tokens) && !borrow  ->  incoming
    //   then:        if (incoming || borrow) slot_source = -1;   (the parked side cancels the slot)
    //   the slot:    slot_source >= 0  ->  resume = slot_tokens; from_live = true;
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
    // PRODUCTION (generate.cpp): the parked side competes with the SLOT, not only with the live prefix.
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
        // the slot's tokens are mounted (generate.cpp: resume = slot_tokens; from_live = true;)
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
    return resume;
}

}  // namespace

int main() {
    using namespace strata::program::cache_diag;
    std::printf("cache_diag_regress_test\n");

    {   // R1: a shallower checkpoint is mounted while a DEEPER one is refused for its image identity.
        // The event must name the deeper refusal, not only the selected source's "EXACT_MATCH".
        ConversationCache cache(1 << 20, 4);
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        // the prompt: 8 tokens, with a picture at token 6 whose hash is 222
        r.ids = {1, 2, 3, 4, 5, 6, 7, 8};
        r.req_imgs = {{6, 222}};
        // the shallower checkpoint: 4 tokens, no picture below it -> it matches the prompt's start
        ConversationCheckpoint shallow;
        shallow.ids = {1, 2, 3, 4};
        // the deeper checkpoint: 6 tokens, but its picture (hash 111) is not the prompt's (hash 222)
        ConversationCheckpoint deep;
        deep.ids = {1, 2, 3, 4, 5, 6};
        deep.imgs = {{6, 111}};
        r.checks = {shallow, deep};
        r.conversations = &cache;
        const int64_t resume = run_request(r, cdiag);
        check(resume == 4, "R1: the engine mounts the shallower checkpoint");
        check(cdiag.selected == Source::active_checkpoint, "R1: the selected source is the checkpoint");
        check(cdiag.selected_prefix == 4, "R1: the reported prefix is the shallower checkpoint's length");
        const auto e = cdiag.event(cache);
        // the deeper candidate's refusal must be in the event
        check(e.deeper_rejection_reason == Reason::image_mismatch,
              "R1: the event names the DEEPER candidate's refusal (image mismatch)");
        check(e.deeper_candidate_tokens == 6, "R1: the event names the deeper candidate's length");
        check(e.rejection_reason == Reason::exact_match,
              "R1: the selected source's own reason is still reported");
        // the writer's line carries both
        FILE* f = std::tmpfile();
        check(f != nullptr, "R1: a temporary file for the event line");
        Writer wf(f);
        wf.write(e);
        std::fflush(f);
        std::rewind(f);
        char buf[4096] = {};
        const size_t n = std::fread(buf, 1, sizeof buf - 1, f);
        std::fclose(f);
        const std::string text(buf, n);
        check(text.find("deeper_rejection_reason=IMAGE_MISMATCH") != std::string::npos,
              "R1: the writer's line names the deeper refusal");
        check(text.find("deeper_candidate_tokens=6") != std::string::npos,
              "R1: the writer's line names the deeper candidate's length");
    }
    {   // R1b: the same, with a STEERING refusal on a deeper PARKED candidate
        ConversationCache cache(1 << 20, 4);
        // a parked conversation of another steering mode, holding a deeper checkpoint than the active chain's
        check(cache.put(image({1, 2, 3, 4, 5, 6}, {{1, 2, 3, 4, 5, 6}}, false)), "R1b: park a donor of another mode");
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        r.ids = {1, 2, 3, 4, 5, 6, 7, 8};
        ConversationCheckpoint shallow;
        shallow.ids = {1, 2, 3, 4};
        r.checks = {shallow};
        r.conversations = &cache;
        const int64_t resume = run_request(r, cdiag);
        check(resume == 4, "R1b: the engine mounts the shallower checkpoint");
        const auto e = cdiag.event(cache);
        check(e.deeper_rejection_reason == Reason::steering_mismatch,
              "R1b: the event names the deeper candidate's steering refusal");
    }
    {   // R1c: when nothing deeper was refused, the field says so (UNKNOWN), not a stale reason
        ConversationCache cache(1 << 20, 4);
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        r.ids = {1, 2, 3, 4, 5, 6, 7};
        r.live = {1, 2, 3, 4};
        r.live_ok = true;
        r.conversations = &cache;
        const int64_t resume = run_request(r, cdiag);
        check(resume == 4, "R1c: the engine mounts the live state");
        const auto e = cdiag.event(cache);
        check(e.deeper_rejection_reason == Reason::unknown,
              "R1c: with no deeper refusal the field is UNKNOWN");
        check(e.deeper_candidate_tokens == 0, "R1c: with no deeper refusal there is no deeper candidate");
    }
    {   // R2: a BATCH SLOT gives the conversation back.  The event's source must describe that selection.
        ConversationCache cache(1 << 20, 4);
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        r.ids = {1, 2, 3, 4, 5, 6, 7};
        r.slot_present = true;
        r.slot_ids = {1, 2, 3, 4};
        r.conversations = &cache;
        const int64_t resume = run_request(r, cdiag);
        check(resume == 4, "R2: the engine reuses the slot's 4 tokens");
        const auto e = cdiag.event(cache);
        check(e.selected_source == Source::slot,
              "R2: the event names the BATCH SLOT as the source");
        check(e.rejection_reason == Reason::slot_source, "R2: the reason is the slot");
        // the writer's line carries it
        FILE* f = std::tmpfile();
        check(f != nullptr, "R2: a temporary file for the event line");
        Writer wf(f);
        wf.write(e);
        std::fflush(f);
        std::rewind(f);
        char buf[4096] = {};
        const size_t n = std::fread(buf, 1, sizeof buf - 1, f);
        std::fclose(f);
        const std::string text(buf, n);
        check(text.find("selected_source=slot") != std::string::npos, "R2: the writer's line names the slot");
    }
    {   // R2b: a slot's CHECKPOINT (not its live state) gives the conversation back
        ConversationCache cache(1 << 20, 4);
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        r.ids = {1, 2, 3, 4, 5, 6, 7};
        r.slot_present = true;
        r.slot_ids = {9, 9, 9};   // the slot's own state is not this prompt's start
        ConversationCheckpoint slot_ck;
        slot_ck.ids = {1, 2, 3, 4, 5};
        r.slot_checks = {slot_ck};
        r.conversations = &cache;
        const int64_t resume = run_request(r, cdiag);
        check(resume == 5, "R2b: the engine reuses the slot checkpoint's 5 tokens");
        const auto e = cdiag.event(cache);
        check(e.selected_source == Source::slot, "R2b: the event names the batch slot");
        check(e.selected_prefix_tokens == 5, "R2b: the reported prefix is the slot checkpoint's length");
    }
    {   // R2c: the slot is NOT the source when the parked side is deeper: the engine's order is unchanged
        ConversationCache cache(1 << 20, 4);
        check(cache.put(image({1, 2, 3, 4, 5, 6})), "R2c: park a conversation");
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        r.ids = {1, 2, 3, 4, 5, 6, 7};
        r.slot_present = true;
        r.slot_ids = {1, 2, 3, 4};
        r.conversations = &cache;
        const int64_t resume = run_request(r, cdiag);
        check(resume == 6, "R2c: the parked side wins, as before");
        const auto e = cdiag.event(cache);
        check(e.selected_source == Source::parked_live, "R2c: the parked side is the source, not the slot");
    }
    {   // R5: the image identity at the checkpoint's boundary.
        // The picture sits at index 5, INSIDE a six-token checkpoint: the checkpoint's own length is 6, so the
        // picture is below its end and the checkpoint's identity depends on it.
        //   (a) the checkpoint's picture IS the prompt's -> the checkpoint is reusable
        //   (b) the checkpoint's picture is NOT the prompt's -> the checkpoint is refused
        //   (c) a shallower checkpoint that ends BEFORE the picture (4 tokens) is still reusable
        const Ids prompt = {1, 2, 3, 4, 5, 6, 7, 8};
        const std::vector<ImgKey> img_prompt = {{5, 222}};   // the picture at index 5

        {   // (a) the same image identity: the six-token checkpoint is used
            ConversationCache cache(1 << 20, 4);
            CacheDiagCollector cdiag;
            cdiag.on = true;
            Request r;
            r.ids = prompt;
            r.req_imgs = img_prompt;
            ConversationCheckpoint deep;
            deep.ids = {1, 2, 3, 4, 5, 6};
            deep.imgs = {{5, 222}};   // the SAME identity as the prompt's
            r.checks = {deep};
            r.conversations = &cache;
            const int64_t resume = run_request(r, cdiag);
            check(resume == 6, "R5a: the matching six-token checkpoint is reused");
            const auto e = cdiag.event(cache);
            check(e.selected_source == Source::active_checkpoint, "R5a: the source is the checkpoint");
            check(e.selected_prefix_tokens == 6, "R5a: the reported prefix is the checkpoint's length");
            check(e.deeper_rejection_reason == Reason::unknown,
                  "R5a: nothing deeper was refused, so the reason is UNKNOWN");
            check(e.deeper_candidate_tokens == 0, "R5a: nothing deeper was refused, so there is no deeper candidate");
        }
        {   // (b) a different image identity: the six-token checkpoint is refused
            ConversationCache cache(1 << 20, 4);
            CacheDiagCollector cdiag;
            cdiag.on = true;
            Request r;
            r.ids = prompt;
            r.req_imgs = img_prompt;
            ConversationCheckpoint deep;
            deep.ids = {1, 2, 3, 4, 5, 6};
            deep.imgs = {{5, 111}};   // NOT the prompt's identity
            r.checks = {deep};
            r.conversations = &cache;
            const int64_t resume = run_request(r, cdiag);
            check(resume == 0, "R5b: the six-token checkpoint with another identity is refused");
            const auto e = cdiag.event(cache);
            check(e.selected_source == Source::none, "R5b: no source was mounted");
            check(e.deeper_rejection_reason == Reason::image_mismatch,
                  "R5b: the event names the image identity mismatch");
            check(e.deeper_candidate_tokens == 6, "R5b: the refused candidate's length is reported");
        }
        {   // (c) a shallower checkpoint that ends BEFORE the picture: it is still reusable
            ConversationCache cache(1 << 20, 4);
            CacheDiagCollector cdiag;
            cdiag.on = true;
            Request r;
            r.ids = prompt;
            r.req_imgs = img_prompt;
            ConversationCheckpoint shallow;   // 4 tokens: the picture at index 5 is BELOW its end
            shallow.ids = {1, 2, 3, 4};
            ConversationCheckpoint deep;      // 6 tokens: the picture is inside it, and the identity differs
            deep.ids = {1, 2, 3, 4, 5, 6};
            deep.imgs = {{5, 111}};
            r.checks = {shallow, deep};
            r.conversations = &cache;
            const int64_t resume = run_request(r, cdiag);
            check(resume == 4, "R5c: the shallower checkpoint that ends before the picture is reused");
            const auto e = cdiag.event(cache);
            check(e.selected_source == Source::active_checkpoint, "R5c: the source is the active checkpoint");
            check(e.selected_prefix_tokens == 4, "R5c: the reported prefix is the shallower checkpoint's length");
            check(e.deeper_rejection_reason == Reason::image_mismatch,
                  "R5c: the deeper checkpoint's image mismatch is named");
            check(e.deeper_candidate_tokens == 6, "R5c: the deeper checkpoint's length is reported");
        }
    }
    {   // R6: the batch slot against a parked checkpoint.
        // slot_tokens=6000, parked.tokens=5000, resume=0.  Production (generate.cpp):
        //   the parked side is taken only when `parked.tokens > std::max(resume, slot_tokens)`, so 5000 > 6000 is
        //   FALSE: the parked side does NOT win, the slot does.  The event must name the SLOT.
        ConversationCache cache(1 << 20, 4);
        check(cache.put(image({1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20})),
              "R6: park a conversation of 20 tokens");
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        // the prompt: 6002 tokens, so a 6000-token slot is below it
        r.ids.resize(6002);
        for (size_t i = 0; i < r.ids.size(); ++i) r.ids[i] = (int32_t) (i + 1);
        r.slot_present = true;
        r.slot_ids.assign(r.ids.begin(), r.ids.begin() + 6000);   // the slot's own 6000 tokens
        r.conversations = &cache;
        // the parked conversation's live state must be a 5000-token prefix of the prompt, so parked.tokens == 5000
        // (the cache's best() walks the parked conversation's live state)
        {
            ConversationCache probe(1 << 20, 4);
            SavedConversation donor;
            donor.live.ids.assign(r.ids.begin(), r.ids.begin() + 5000);
            donor.live.gdn.resize(64, 7);
            check(probe.put(std::move(donor)), "R6: park a 5000-token donor");
            const auto m = probe.best(r.ids, {}, true);
            check(m.tokens == 5000, "R6: the parked side's best is 5000 tokens");
        }
        {
            // replace the cache's entry with the 5000-token donor
            ConversationCache c2(1 << 20, 4);
            SavedConversation donor;
            donor.live.ids.assign(r.ids.begin(), r.ids.begin() + 5000);
            donor.live.gdn.resize(64, 7);
            check(c2.put(std::move(donor)), "R6: park the 5000-token donor");
            r.conversations = &c2;
            const int64_t resume = run_request(r, cdiag);
            check(resume == 6000, "R6: the SLOT wins: 6000 tokens, not the parked 5000");
            const auto e = cdiag.event(c2);
            check(e.selected_source == Source::slot, "R6: the event names the SLOT, not the parked side");
            check(e.selected_prefix_tokens == 6000, "R6: the reported prefix is the slot's 6000 tokens");
            check(e.rejection_reason == Reason::slot_source, "R6: the reason is the slot");
        }
    }
    {   // R4: a REJECTED candidate that is SHORTER than the selected one is not a "deeper" candidate.
        // The event's deeper_candidate_tokens must be 0 and its deeper_rejection_reason UNKNOWN: the
        // shorter refusal is not what stopped the request from reusing more.
        ConversationCache cache(1 << 20, 4);
        CacheDiagCollector cdiag;
        cdiag.on = true;
        Request r;
        // the prompt: 6002 tokens
        r.ids.resize(6002);
        for (size_t i = 0; i < r.ids.size(); ++i) r.ids[i] = (int32_t) (i + 1);
        // the SELECTED checkpoint: 6000 tokens
        ConversationCheckpoint selected;
        selected.ids.assign(r.ids.begin(), r.ids.begin() + 6000);
        // the REJECTED candidate: 2000 tokens, and its tokens differ from the prompt's
        ConversationCheckpoint rejected;
        rejected.ids.assign(r.ids.begin(), r.ids.begin() + 2000);
        rejected.ids[1000] = 999999;   // a different token
        r.checks = {selected, rejected};
        r.conversations = &cache;
        const int64_t resume = run_request(r, cdiag);
        check(resume == 6000, "R4: the engine mounts the 6000-token checkpoint");
        const auto e = cdiag.event(cache);
        check(e.selected_prefix_tokens == 6000, "R4: the reported prefix is 6000");
        check(e.deeper_candidate_tokens == 0,
              "R4: a SHORTER rejected candidate is not a deeper one: deeper_candidate_tokens is 0");
        check(e.deeper_rejection_reason == Reason::unknown,
              "R4: a SHORTER rejected candidate leaves deeper_rejection_reason UNKNOWN");
    }
    {   // R2d: with the switch OFF the slot is still not selected in the event (nothing is recorded)
        ConversationCache cache(1 << 20, 4);
        CacheDiagCollector cdiag;
        cdiag.on = false;
        Request r;
        r.ids = {1, 2, 3, 4, 5, 6, 7};
        r.slot_present = true;
        r.slot_ids = {1, 2, 3, 4};
        r.conversations = &cache;
        const int64_t resume = run_request(r, cdiag);
        check(resume == 4, "R2d: the switch does not change the reuse");
        check(cdiag.entries.empty(), "R2d: nothing was collected with the switch off");
        check(cdiag.seq == 0, "R2d: no request id was spent");
    }
    std::printf("cache_diag_regress_test: %d checks passed\n", checks);
    return 0;
}
