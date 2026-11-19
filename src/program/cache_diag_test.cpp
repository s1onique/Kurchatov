// src/program/cache_diag_test.cpp - the conversation cache's decision observability (STRATA_CACHE_DIAG).
//
// The diagnostics answer one question: WHY did this request reuse what it reused?  The engine has several
// sources (the live session, the active checkpoint chain, a parked conversation, a batch slot) and several ways
// to refuse one (the tokens differ, the picture is not the same, the steering mode is another, the candidate was
// never there, the candidate was evicted).  This test drives the REAL cache (ConversationCache, the same class
// the engine uses) through the real decision rules and checks that:
//
//   1. every reported selection agrees with the checkpoint the engine actually used;
//   2. the reported longest common prefix is the ACTUAL token comparison, never a checkpoint's length;
//   3. a partial common prefix is never reported as a usable prefix;
//   4. the diagnostics carry no user data (no token ids, no prompt text, no image content);
//   5. the diagnostic mode does not change the cache's behaviour: the same selection, the same counters, the
//      same state hashes, with the switch on and with it off.
//
// The scenarios are the ones the mission names: an append-only continuation with deep reuse, a mutation near the
// beginning, a mutation between two checkpoints, an image identity mismatch, an incompatible steering mode,
// alternating conversations with a parked-state restoration, an eviction and a memory-budget refusal, and the
// disabled/enabled parity.
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

/// A sentinel token id that must never appear in the diagnostic's output: the events carry counts and
/// positions, never the tokens themselves.  The check below looks for it by name, so the id is spelled out here.
constexpr int32_t kSentinel = 987654;
constexpr const char* kSentinelText = "987654";

using Ids = std::vector<int32_t>;

/// A saved conversation with a live state and a checkpoint chain.
SavedConversation image(Ids live, std::vector<Ids> chain = {}, bool cvec = true,
                         std::vector<ConversationImageKey> imgs = {}) {
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

/// The engine's own rule for a live state or a checkpoint matching a prompt: the tokens must be exactly the
/// prompt's start (at least one token, and never the last prompt token) and the pictures below the length must
/// be the same.  This is the rule the engine applies; the test applies the SAME one, so "the reported selection
/// agrees with the checkpoint the engine used" is a real check and not a tautology.
bool starts_with(const Ids& pre, const std::vector<ConversationImageKey>& pre_imgs, const Ids& prompt,
                 const std::vector<ConversationImageKey>& prompt_imgs) {
    const int64_t L = (int64_t) pre.size();
    const int64_t n = (int64_t) prompt.size();
    if (L < 1 || L > n - 1) return false;
    for (int64_t i = 0; i < L; ++i)
        if (prompt[(size_t) i] != pre[(size_t) i]) return false;
    std::vector<ConversationImageKey> below;
    for (const auto& k : prompt_imgs)
        if (k.start < L) below.push_back(k);
    return below == pre_imgs;
}

/// What the engine would do with a prompt, given the live state, the active chain and the parked cache.  This
/// mirrors generate.cpp's order: the live state and the active chain first, then the parked cache (which wins
/// when it is deeper), then a borrow.
struct Decision {
    Source source = Source::none;
    int64_t tokens = 0;
    uint64_t serial = 0;
    bool borrowed = false;
};

Decision decide(const Ids& prompt, const std::vector<ConversationImageKey>& prompt_imgs, const Ids& live,
                const std::vector<ConversationImageKey>& live_imgs, const std::vector<Ids>& chain,
                const std::vector<std::vector<ConversationImageKey>>& chain_imgs, ConversationCache& cache,
                bool cvec = true) {
    Decision d;
    int64_t resume = 0;
    bool from_live = false;
    if (!live.empty() && starts_with(live, live_imgs, prompt, prompt_imgs)) {
        resume = (int64_t) live.size();
        from_live = true;
    }
    for (size_t i = 0; i < chain.size(); ++i)
        if ((int64_t) chain[i].size() > resume &&
            starts_with(chain[i], chain_imgs.empty() ? std::vector<ConversationImageKey>() : chain_imgs[i], prompt,
                        prompt_imgs)) {
            resume = (int64_t) chain[i].size();
            from_live = false;
        }
    const auto parked = cache.best(prompt, prompt_imgs, cvec);
    const bool borrow = parked.tokens > resume && cache.borrows(parked);
    if (parked.tokens > resume) {
        d.source = parked.live ? Source::parked_live : Source::parked_checkpoint;
        d.tokens = parked.tokens;
        d.serial = parked.serial;
        d.borrowed = borrow;
        return d;
    }
    if (resume > 0) {
        d.source = from_live ? Source::live : Source::active_checkpoint;
        d.tokens = resume;
    }
    return d;
}

/// The diagnostic's view of the same decision, built the way the engine builds it: the live state and the
/// active chain through cache_diag::analyse(), the parked side through ConversationCache::candidates().
struct Reported {
    Source source = Source::none;
    int64_t prefix = 0;
    int64_t candidate_count = 0;
    int64_t max_candidate = 0;
    int64_t lcp = 0;
    int64_t mismatch = -1;
    Reason reason = Reason::unknown;
    // the DEEPER candidate that was refused: the longest one that was not usable
    int64_t deeper_tokens = 0;
    Reason deeper_reason = Reason::unknown;
};

Reported report(const Ids& prompt, const std::vector<ConversationImageKey>& prompt_imgs, const Ids& live,
                const std::vector<ConversationImageKey>& live_imgs, const std::vector<Ids>& chain,
                const std::vector<std::vector<ConversationImageKey>>& chain_imgs, ConversationCache& cache,
                bool cvec = true) {
    Reported r;
    auto consider = [&](Source src, const Ids& pre, const std::vector<ConversationImageKey>& pre_imgs) {
        strata::program::cache_diag::Candidate c;
        c.source = src;
        c.ids = pre.data();
        c.n_ids = pre.size();
        c.imgs = &pre_imgs;
        c.steering_matches = true;
        const auto a = strata::program::cache_diag::analyse(
            c, prompt, [&](int64_t L) {
                std::vector<ConversationImageKey> below;
                for (const auto& k : prompt_imgs)
                    if (k.start < L) below.push_back(k);
                return below;
            }, [](const std::vector<ConversationImageKey>& below, const void* own) {
                return own != nullptr && below == *static_cast<const std::vector<ConversationImageKey>*>(own);
            });
        const bool usable = starts_with(pre, pre_imgs, prompt, prompt_imgs);
        ++r.candidate_count;
        r.max_candidate = std::max<int64_t>(r.max_candidate, (int64_t) pre.size());
        if (a.lcp > r.lcp) { r.lcp = a.lcp; r.mismatch = a.mismatch; }
        // the DEEPER candidate that was refused: the longest one that was not usable
        if (!usable && (int64_t) pre.size() > r.deeper_tokens) {
            r.deeper_tokens = (int64_t) pre.size();
            r.deeper_reason = a.reason;
        }
        if (usable) {
            r.reason = Reason::exact_match;
            r.source = src;
            r.prefix = (int64_t) pre.size();
        } else if (r.reason == Reason::unknown) {
            r.reason = a.reason;
        }
    };
    if (!live.empty()) consider(Source::live, live, live_imgs);
    for (size_t i = 0; i < chain.size(); ++i)
        consider(Source::active_checkpoint, chain[i],
                 chain_imgs.empty() ? std::vector<ConversationImageKey>() : chain_imgs[i]);
    // the parked side
    std::vector<ConversationCache::Candidate> cands;
    cache.candidates(prompt, prompt_imgs, cvec, cands);
    for (const auto& c : cands) {
        const Source src = c.live ? Source::parked_live : Source::parked_checkpoint;
        ++r.candidate_count;
        r.max_candidate = std::max<int64_t>(r.max_candidate, c.tokens);
        int64_t lcp = 0, mismatch = -1;
        if (c.ids != nullptr)
            lcp = strata::program::cache_diag::common_prefix(c.ids, (size_t) c.tokens, prompt.data(), prompt.size(),
                                                             &mismatch);
        if (lcp > r.lcp) { r.lcp = lcp; r.mismatch = mismatch; }
        if (c.prefix > 0) {
            r.reason = Reason::exact_match;
            r.source = src;
            r.prefix = c.prefix;
        } else if (r.reason == Reason::unknown) {
            r.reason = c.cvec_mismatch ? Reason::steering_mismatch
                                       : (c.image_mismatch ? Reason::image_mismatch : Reason::token_mismatch);
        }
        // the DEEPER parked candidate that was refused
        if (c.prefix <= 0 && c.tokens > r.deeper_tokens) {
            r.deeper_tokens = c.tokens;
            r.deeper_reason = c.cvec_mismatch ? Reason::steering_mismatch
                                              : (c.image_mismatch ? Reason::image_mismatch : Reason::token_mismatch);
        }
    }
    return r;
}

/// The event the engine would write, rendered as text.  The PRODUCTION writer does the rendering (the same
/// Writer the engine uses), so this test cannot drift from the engine's own format.
std::string render(const strata::program::cache_diag::CacheDiagEvent& e) {
    FILE* f = std::tmpfile();
    if (f == nullptr) return std::string();
    strata::program::cache_diag::Writer w(f);
    w.write(e);
    std::fflush(f);
    std::rewind(f);
    char buf[4096] = {};
    const size_t n = std::fread(buf, 1, sizeof buf - 1, f);
    std::fclose(f);
    return std::string(buf, n);
}

}  // namespace

int main() {
    using namespace strata::program::cache_diag;
    std::printf("cache_diag_test\n");

    {   // 1. append-only continuation with deep reuse
        ConversationCache cache(1 << 20, 4);
        const Ids prompt = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12};
        const Ids live = {1, 2, 3, 4};
        const std::vector<Ids> chain = {{1, 2, 3, 4}, {1, 2, 3, 4, 5, 6}};
        const auto d = decide(prompt, {}, live, {}, chain, {}, cache);
        const auto r = report(prompt, {}, live, {}, chain, {}, cache);
        check(d.source == Source::active_checkpoint && d.tokens == 6,
              "an append-only continuation reuses the deepest active checkpoint");
        check(r.source == d.source && r.prefix == d.tokens,
              "the diagnostic reports the checkpoint the engine used");
        check(r.reason == Reason::exact_match, "an exact prefix match is reported as such");
        check(r.lcp == 6 && r.mismatch == -1, "the common prefix is the ACTUAL match, with no mismatch");
        check(r.max_candidate == 6 && r.candidate_count == 3,
              "the candidates are the live state and the two checkpoints");
    }
    {   // 2. a mutation near the beginning of the prompt
        ConversationCache cache(1 << 20, 4);
        const Ids prompt = {1, 2, 99, 4, 5, 6, 7, 8};     // token 2 changed
        const Ids live = {1, 2, 3, 4};
        const std::vector<Ids> chain = {{1, 2, 3, 4}};
        const auto d = decide(prompt, {}, live, {}, chain, {}, cache);
        const auto r = report(prompt, {}, live, {}, chain, {}, cache);
        check(d.source == Source::none && d.tokens == 0, "a mutation near the beginning reuses nothing");
        check(r.source == Source::none && r.prefix == 0, "the diagnostic reports no reusable prefix");
        check(r.lcp == 2 && r.mismatch == 2, "the mismatch is at the changed token, not at the checkpoint's length");
        check(r.reason == Reason::token_mismatch, "the reason is a token mismatch");
        check(r.max_candidate == 4, "the longest candidate's length is reported separately from the common prefix");
        check(r.lcp < r.max_candidate, "a partial common prefix is never reported as a usable prefix");
    }
    {   // 3. a mutation between two existing checkpoints
        ConversationCache cache(1 << 20, 4);
        const Ids prompt = {1, 2, 3, 4, 5, 99, 7, 8, 9, 10};   // token 5 changed, past the first checkpoint
        const std::vector<Ids> chain = {{1, 2, 3, 4}, {1, 2, 3, 4, 5, 6}};
        const auto d = decide(prompt, {}, {}, {}, chain, {}, cache);
        const auto r = report(prompt, {}, {}, {}, chain, {}, cache);
        check(d.source == Source::active_checkpoint && d.tokens == 4,
              "a mutation between two checkpoints falls back to the shallower one");
        check(r.source == d.source && r.prefix == 4, "the diagnostic reports the shallower checkpoint");
        check(r.lcp == 5 && r.mismatch == 5, "the common prefix stops at the changed token");
        check(r.max_candidate == 6, "the deeper candidate's length is reported, but it is not the selection");
    }
    {   // 3b. a shallower checkpoint is selected while a DEEPER one is refused for its picture
        ConversationCache cache(1 << 20, 4);
        // the picture sits at token 6: below a 6-token candidate, above a 4-token one
        const Ids prompt = {1, 2, 3, 4, 5, 6, 7, 8};
        const std::vector<ConversationImageKey> img_prompt = {{6, 222}};
        const std::vector<Ids> chain = {{1, 2, 3, 4}, {1, 2, 3, 4, 5, 6}};
        const std::vector<std::vector<ConversationImageKey>> chain_imgs = {{}, {{6, 111}}};
        const auto d = decide(prompt, img_prompt, {}, {}, chain, chain_imgs, cache);
        const auto r = report(prompt, img_prompt, {}, {}, chain, chain_imgs, cache);
        check(d.source == Source::active_checkpoint && d.tokens == 4,
              "the engine falls back to the shallower checkpoint");
        check(r.source == d.source && r.prefix == 4, "the diagnostic reports the shallower checkpoint");
        check(r.reason == Reason::exact_match, "the selected source's own reason is reported");
        check(r.deeper_tokens == 6, "the DEEPER refused candidate's length is reported");
        check(r.deeper_reason == Reason::image_mismatch,
              "the DEEPER refused candidate's reason is reported: a successful shallow reuse does not hide it");
    }
    {   // 4. an image identity mismatch
        ConversationCache cache(1 << 20, 4);
        // the picture sits at token 2, so it is BELOW a 4-token candidate and ABOVE a 2-token one
        const std::vector<ConversationImageKey> img_a = {{2, 111}};
        const std::vector<ConversationImageKey> img_b = {{2, 222}};
        const Ids prompt = {1, 2, 3, 4, 5, 6, 7};
        // the parked live state holds 4 tokens (so the picture is below it) with picture A
        SavedConversation s = image({1, 2, 3, 4}, {}, true, img_a);
        check(cache.put(std::move(s)), "park a conversation with a picture");
        const auto d = decide(prompt, img_b, {}, {}, {}, {}, cache);
        const auto r = report(prompt, img_b, {}, {}, {}, {}, cache);
        check(d.source == Source::none && d.tokens == 0, "a picture that is not the same refuses the reuse");
        check(r.source == Source::none && r.prefix == 0, "the diagnostic reports no reusable prefix");
        check(r.reason == Reason::image_mismatch, "the reason is an image mismatch, not a token mismatch");
        check(r.lcp == 4 && r.mismatch == -1, "the tokens agree throughout: there is no token mismatch");
        // the same picture resumes
        const auto d2 = decide(prompt, img_a, {}, {}, {}, {}, cache);
        check(d2.source == Source::parked_live && d2.tokens == 4, "the same picture resumes the parked state");
        // a candidate that ends BEFORE the picture does not care about it (the engine's own rule)
        SavedConversation t = image({1, 2, 3, 4, 5, 6}, {{1, 2}}, true, {});
        check(cache.put(std::move(t)), "park a conversation whose checkpoint ends before the picture");
        const auto d3 = decide(prompt, img_b, {}, {}, {}, {}, cache);
        check(d3.source == Source::parked_checkpoint && d3.tokens == 2,
              "a checkpoint that ends before the picture is unaffected by it");
    }
    {   // 5. an incompatible steering mode
        ConversationCache cache(1 << 20, 4);
        const Ids prompt = {1, 2, 3, 4, 5};
        check(cache.put(image({1, 2, 3}, {}, false)), "park a conversation with another steering mode");
        const auto d = decide(prompt, {}, {}, {}, {}, {}, cache, true);
        const auto r = report(prompt, {}, {}, {}, {}, {}, cache, true);
        check(d.source == Source::none && d.tokens == 0, "another steering mode refuses the reuse");
        check(r.reason == Reason::steering_mismatch, "the reason is the steering mode");
        check(r.candidate_count == 1, "the other-mode candidate is reported as a candidate");
        // the same mode resumes
        const auto d2 = decide(prompt, {}, {}, {}, {}, {}, cache, false);
        check(d2.source == Source::parked_live && d2.tokens == 3, "the same steering mode resumes");
    }
    {   // 6. alternating conversations with a parked-state restoration
        ConversationCache cache(1 << 20, 4);
        const Ids a_prompt = {1, 2, 3, 4, 5};
        const Ids b_prompt = {9, 8, 7, 6, 5};
        check(cache.put(image({1, 2, 3})), "park A");
        check(cache.put(image({9, 8, 7})), "park B");
        const auto da = decide(a_prompt, {}, {}, {}, {}, {}, cache);
        check(da.source == Source::parked_live && da.tokens == 3, "A is restored from its parked state");
        // taking A out and parking it again keeps the identity
        SavedConversation taken = cache.take(cache.best(a_prompt, {}, true).index);
        check(cache.put(std::move(taken)), "A is parked again as the newest entry");
        const auto db = decide(b_prompt, {}, {}, {}, {}, {}, cache);
        check(db.source == Source::parked_live && db.tokens == 3, "B is restored from its parked state");
        const auto da2 = decide(a_prompt, {}, {}, {}, {}, {}, cache);
        check(da2.source == Source::parked_live && da2.tokens == 3, "A is restored again after the round trip");
        check(cache.size() == 2 && cache.evictions() == 0, "no conversation was evicted by the round trip");
    }
    {   // 7. a checkpoint eviction and a memory-budget refusal
        const size_t one = image({1, 2, 3}).bytes();
        ConversationCache cache(one * 2, 8);
        check(cache.put(image({1, 2, 3})), "park A");
        check(cache.put(image({9, 8, 7})), "park B");
        check(cache.evictions() == 0, "nothing evicted yet");
        check(cache.put(image({4, 5, 6})), "park C");
        check(cache.evictions() == 1, "the oldest conversation was evicted");
        check(cache.best(std::vector<int64_t>{1, 2, 9}, {}, true).tokens == 0, "the evicted one is gone");
        // the eviction counter is what the event reports
        strata::program::cache_diag::CacheDiagEvent e;
        e.cache_evictions_total = cache.evictions();
        e.cache_parked_entries = cache.size();
        e.cache_parked_bytes = cache.bytes();
        check(e.cache_evictions_total == 1 && e.cache_parked_entries == 2,
              "the event carries the observed counters");
        // a memory-budget refusal: an image bigger than the whole budget is not admitted
        auto huge = image({1});
        huge.live.gdn.resize(one * 3);
        const size_t before = cache.size();
        check(!cache.put(std::move(huge)), "an oversized image is refused");
        check(cache.size() == before, "the refusal evicts nothing");
        check(cache.evictions() == 1, "the refusal does not count as an eviction");
    }
    {   // 8. the disabled/enabled parity: the diagnostics change nothing
        // the same conversation, the same requests, with the analysis on and off: the selection, the counters
        // and the state are the same.
        const Ids prompt = {1, 2, 3, 4, 5, 6, 7, 8};
        const Ids live = {1, 2, 3};
        const std::vector<Ids> chain = {{1, 2}, {1, 2, 3, 4}};
        ConversationCache on(1 << 20, 4), off(1 << 20, 4);
        check(on.put(image({9, 8, 7, 6}, {{9, 8}})), "park in the diagnostic-on cache");
        check(off.put(image({9, 8, 7, 6}, {{9, 8}})), "park in the diagnostic-off cache");
        const auto d_on = decide(prompt, {}, live, {}, chain, {}, on);
        const auto r_on = report(prompt, {}, live, {}, chain, {}, on);
        const auto d_off = decide(prompt, {}, live, {}, chain, {}, off);
        check(d_on.source == d_off.source && d_on.tokens == d_off.tokens,
              "the analysis does not change the selection");
        check(on.size() == off.size() && on.bytes() == off.bytes() && on.evictions() == off.evictions(),
              "the analysis does not change the cache's counters");
        check(r_on.source == d_on.source && r_on.prefix == d_on.tokens,
              "the reported selection agrees with the engine's, with the analysis on");
        // the switch itself: off by default, on with STRATA_CACHE_DIAG=1
        check(strata::program::cache_diag::enabled() == false,
              "STRATA_CACHE_DIAG unset: the diagnostics are off");
    }
    {   // the event carries no user data
        strata::program::cache_diag::CacheDiagEvent e;
        e.kind = EventKind::decision;
        e.request_seq = 42;
        e.prompt_tokens = 100;
        e.selected_source = Source::active_checkpoint;
        e.selected_prefix_tokens = 60;
        e.candidate_count = 3;
        e.max_candidate_prefix_tokens = 60;
        e.longest_common_prefix_tokens = 60;
        e.first_mismatch_position = -1;
        e.rejection_reason = Reason::exact_match;
        e.cache_parked_entries = 2;
        e.cache_parked_bytes = 4096;
        e.cache_evictions_total = 1;
        const std::string text = render(e);
        check(text.find(kSentinelText) == std::string::npos, "the event carries no token id");
        check(text.find(std::to_string(kSentinel)) == std::string::npos, "the event carries no raw token payload");
        check(text.find("selected_source=active_checkpoint") != std::string::npos, "the source is named");
        check(text.find("rejection_reason=EXACT_MATCH") != std::string::npos, "the reason is typed");
        check(text.find("request_seq=42") != std::string::npos, "the request id is there");
        check(text.find("longest_common_prefix_tokens=60") != std::string::npos, "the common prefix is there");
        check(text.find("first_mismatch_position=-1") != std::string::npos, "the mismatch position is there");
        check(text.find("cache_parked_entries=2") != std::string::npos, "the parked count is there");
        check(text.find("cache_evictions_total=1") != std::string::npos, "the eviction counter is there");
    }
    {   // the typed reasons are all distinct words, and UNKNOWN is the honest default
        check(std::strcmp(reason_name(Reason::unknown), "UNKNOWN") == 0, "the default reason is UNKNOWN");
        check(std::strcmp(reason_name(Reason::token_mismatch), "TOKEN_MISMATCH") == 0, "a token mismatch");
        check(std::strcmp(reason_name(Reason::image_mismatch), "IMAGE_MISMATCH") == 0, "an image mismatch");
        check(std::strcmp(reason_name(Reason::steering_mismatch), "STEERING_MISMATCH") == 0, "a steering mismatch");
        check(std::strcmp(reason_name(Reason::absent), "ABSENT") == 0, "an absent candidate");
        check(std::strcmp(reason_name(Reason::ineligible), "INELIGIBLE") == 0, "an ineligible candidate");
        check(std::strcmp(reason_name(Reason::evicted), "EVICTED") == 0, "an evicted candidate");
        check(std::strcmp(reason_name(Reason::budget_refused), "BUDGET_REFUSED") == 0, "a budget refusal");
        check(std::strcmp(reason_name(Reason::cache_disabled), "CACHE_DISABLED") == 0, "a disabled cache");
        check(std::strcmp(source_name(Source::none), "none") == 0, "no source");
        check(std::strcmp(source_name(Source::live), "live") == 0, "the live source");
        check(std::strcmp(source_name(Source::active_checkpoint), "active_checkpoint") == 0, "the active source");
        check(std::strcmp(source_name(Source::parked_live), "parked_live") == 0, "the parked live source");
        check(std::strcmp(source_name(Source::parked_checkpoint), "parked_checkpoint") == 0, "the parked source");
    }
    {   // the common prefix is the ACTUAL comparison
        const Ids a = {1, 2, 3, 4, 5};
        const Ids b = {1, 2, 9, 4, 5};
        int64_t mismatch = 0;
        check(common_prefix(a.data(), a.size(), b.data(), b.size(), &mismatch) == 2 && mismatch == 2,
              "the common prefix stops at the first difference");
        const Ids c = {1, 2, 3};
        check(common_prefix(c.data(), c.size(), a.data(), a.size(), &mismatch) == 3 && mismatch == -1,
              "a prefix of the prompt agrees throughout: no mismatch position");
        check(common_prefix(nullptr, 0, a.data(), a.size(), &mismatch) == 0, "an empty candidate shares nothing");
    }
    std::printf("cache_diag_test: %d checks passed\n", checks);
    return 0;
}
