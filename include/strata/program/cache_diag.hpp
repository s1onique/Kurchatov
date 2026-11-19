// include/strata/program/cache_diag.hpp - the conversation cache's decision observability: WHY a request reused
// a deep checkpoint, fell back to a shallow one, or reread most of its prompt.
//
// The engine's cache has three sources a request can resume from, and each of them is chosen in a different place:
//
//   * the LIVE session (the running state of the last request) and the ACTIVE checkpoint chain (the chain of
//     checkpoints the session holds) - both are picked in generate.cpp's request loop, in one block, by comparing
//     the prompt's tokens and pictures with the live state's and the chain's;
//   * a PARKED conversation (one the engine put aside to make room for another) and a checkpoint inside one - the
//     parked side is picked by ConversationCache::best() (include/strata/core/conversation_cache.hpp), which walks
//     the parked conversations and their checkpoints;
//   * a batch SLOT's conversation - the slot side, in the same request loop.
//
// The log already says what happened ("conversation cache: restored N tokens (live|checkpoint) in X ms",
// "RESUME N", "REUSED N", "the state at N tokens has this prompt's tokens but picture K is not the same"), but it
// does not say WHY a candidate was rejected: a token mismatch at position N, an image that is not the same, a
// steering mode that does not match, a checkpoint that was never there, one that was dropped by the retention
// policy.  This header is the missing half: one structured event per request, at the decision boundary, naming
// the source that was used and the reason the others were not.
//
// STRATA_CACHE_DIAG=1 turns it on; the default (unset, or 0) is off.  With it off, the engine's behaviour is
// byte-identical to the release: no extra token comparisons, no diagnostic records, no work in the per-token fast
// path.  The gate is one static bool, read once.
//
// NOTHING HERE CARRIES USER DATA: no prompt text, no token ids, no image content, no tool schemas, no keys.  The
// fields are counts, positions and fixed words.
//
// The event's fields (see CacheDiagEvent):
//
//   request_seq                  opaque, process-local correlation id (a counter)
//   prompt_tokens                the request's input token count
//   selected_source              live | active_checkpoint | parked_live | parked_checkpoint | none
//   selected_prefix_tokens       the reusable prefix the engine actually used (0 when none)
//   candidate_count              how many candidates were examined
//   max_candidate_prefix_tokens  the longest candidate's length
//   longest_common_prefix_tokens the ACTUAL matching token prefix with the prompt (not a checkpoint's length)
//   first_mismatch_position      where the tokens first differ (-1 when they do not differ)
//   rejection_reason             a typed reason, or UNKNOWN
//   cache_parked_entries         the parked conversations
//   cache_parked_bytes           their retained footprint
//   cache_evictions_total        the observed eviction counter
//
// `longest_common_prefix_tokens` and `first_mismatch_position` are the ACTUAL token comparison, not a checkpoint's
// length: a candidate whose tokens match for 100 tokens and then differ reports 100 and 100, even though its
// checkpoint is 5000 tokens long and none of it is restorable.  A partial longest common prefix is never reported
// as a usable prefix.
#pragma once

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

namespace strata::program::cache_diag {

/// Where the reusable prefix came from.  The order is the order the engine tries them in.
enum class Source : int {
    none = 0,          ///< nothing was reused: the prompt was read from token 0
    live,              ///< the live session (the running state of the last request)
    active_checkpoint, ///< a checkpoint of the live session's chain
    parked_live,       ///< the live state of a parked conversation
    parked_checkpoint, ///< a checkpoint inside a parked conversation
};

inline const char* source_name(Source s) {
    switch (s) {
        case Source::none: return "none";
        case Source::live: return "live";
        case Source::active_checkpoint: return "active_checkpoint";
        case Source::parked_live: return "parked_live";
        case Source::parked_checkpoint: return "parked_checkpoint";
    }
    return "none";
}

/// Why a candidate was not used.  UNKNOWN is the honest answer when the engine has no evidence.
enum class Reason : int {
    unknown = 0,          ///< no evidence for a narrower reason
    exact_match,          ///< the candidate matched the prompt exactly and was used
    token_mismatch,       ///< the candidate's tokens differ from the prompt's
    image_mismatch,       ///< the candidate's pictures are not the same as the prompt's
    steering_mismatch,    ///< the candidate was saved with another steering (control-vector) mode
    absent,               ///< there was no candidate at all
    ineligible,           ///< a candidate was there but not eligible (wrong stage set, failed validation)
    evicted,              ///< the candidate was observed to be evicted by the retention policy
    retention_removed,    ///< the candidate was removed by the checkpoint retention policy (off-path pruning)
    cache_disabled,       ///< the cache is off for this request (no checkpoint slots, or ckpt=0)
    budget_refused,       ///< a memory-budget or slot-limit admission refusal
    superseded,           ///< the candidate was dropped because this request supersedes it
    borrowed,             ///< the candidate is used through a borrow (the donor stays parked)
    slot_source,          ///< a batch slot gave back the conversation
};

inline const char* reason_name(Reason r) {
    switch (r) {
        case Reason::unknown: return "UNKNOWN";
        case Reason::exact_match: return "EXACT_MATCH";
        case Reason::token_mismatch: return "TOKEN_MISMATCH";
        case Reason::image_mismatch: return "IMAGE_MISMATCH";
        case Reason::steering_mismatch: return "STEERING_MISMATCH";
        case Reason::absent: return "ABSENT";
        case Reason::ineligible: return "INELIGIBLE";
        case Reason::evicted: return "EVICTED";
        case Reason::retention_removed: return "RETENTION_REMOVED";
        case Reason::cache_disabled: return "CACHE_DISABLED";
        case Reason::budget_refused: return "BUDGET_REFUSED";
        case Reason::superseded: return "SUPERSEDED";
        case Reason::borrowed: return "BORROWED";
        case Reason::slot_source: return "SLOT_SOURCE";
    }
    return "UNKNOWN";
}

/// The kind of a separate event: a checkpoint that went away, or a parking that was refused.
enum class EventKind : int {
    decision = 0,      ///< the per-request decision event
    checkpoint_evict,  ///< a checkpoint left the active chain
    checkpoint_super,  ///< a checkpoint left because this request supersedes it
    park_refused,      ///< a park was refused (memory budget, slot limit)
    park_evict,        ///< a parked conversation was evicted to make room
};

inline const char* event_kind_name(EventKind k) {
    switch (k) {
        case EventKind::decision: return "decision";
        case EventKind::checkpoint_evict: return "checkpoint_evict";
        case EventKind::checkpoint_super: return "checkpoint_super";
        case EventKind::park_refused: return "park_refused";
        case EventKind::park_evict: return "park_evict";
    }
    return "decision";
}

/// One structured event.  Every field is a count, a position or a fixed word: nothing here can carry user data.
struct CacheDiagEvent {
    EventKind kind = EventKind::decision;
    uint64_t request_seq = 0;
    int64_t prompt_tokens = 0;
    Source selected_source = Source::none;
    int64_t selected_prefix_tokens = 0;
    int64_t candidate_count = 0;
    int64_t max_candidate_prefix_tokens = 0;
    int64_t longest_common_prefix_tokens = 0;
    int64_t first_mismatch_position = -1;
    Reason rejection_reason = Reason::unknown;
    size_t cache_parked_entries = 0;
    size_t cache_parked_bytes = 0;
    size_t cache_evictions_total = 0;
    // the secondary event's own fields
    int64_t subject_tokens = 0;    ///< the checkpoint's or conversation's length
    int64_t subject_serial = 0;    ///< the parked conversation's identity (an opaque counter), -1: none
};

/// The switch: STRATA_CACHE_DIAG=1.  Read once, so a run's behaviour cannot change under it.
inline bool enabled() {
    static const bool on = [] {
        const char* v = std::getenv("STRATA_CACHE_DIAG");
        return v != nullptr && v[0] == '1';
    }();
    return on;
}

/// The process-local request counter.  An opaque correlation id: it says which request an event belongs to and
/// nothing else.
inline uint64_t next_seq() {
    static uint64_t seq = 0;
    return ++seq;
}

/// The ACTUAL number of leading tokens the two sequences share, and where they first differ.  `mismatch` is the
/// position of the first differing token, or -1 when one is a prefix of the other and they agree throughout.
/// This is the measurement the event reports: it is the common PREFIX, never a checkpoint's length.
inline int64_t common_prefix(const int32_t* a, size_t na, const int32_t* b, size_t nb, int64_t* mismatch) {
    const size_t n = na < nb ? na : nb;
    int64_t k = 0;
    while (k < (int64_t) n && a[k] == b[k]) ++k;
    if (mismatch != nullptr) *mismatch = (k < (int64_t) n) ? k : -1;
    return k;
}

/// A candidate the engine examined: a state (the live session's or a parked conversation's) or a checkpoint.
/// The pictures are held as a `const void*` plus a comparison callable, because the picture key's type belongs to
/// the engine's core (conversation_cache.hpp) and this header must not depend on it.
struct Candidate {
    Source source = Source::none;
    const int32_t* ids = nullptr;
    size_t n_ids = 0;
    /// The candidate's pictures (its own image keys), as the engine holds them.
    const void* imgs = nullptr;
    /// The candidate's steering (control-vector) mode.  A candidate saved with another mode is not usable.
    bool steering_matches = true;
};

/// The analysis of one candidate against the request's prompt: how far the tokens agree, and why the candidate
/// was not usable when it is not.
///
/// The picture identity check is the engine's own (a callback), not a copy of it: this header does not depend on
/// the engine's picture key type.
struct CandidateAnalysis {
    int64_t lcp = 0;              ///< the ACTUAL common token prefix with the prompt
    int64_t mismatch = -1;        ///< the first differing token's position, -1 when they agree throughout
    bool tokens_match = false;    ///< the candidate's tokens are exactly the prompt's start
    bool images_match = false;    ///< the candidate's pictures are exactly the request's pictures below its length
    Reason reason = Reason::unknown;   ///< why the candidate is not usable (exact_match when it is)
};

/// Analyse one candidate the way the engine's `starts_with` does: the tokens must be exactly the prompt's start
/// AND the pictures below the candidate's length must be exactly the candidate's pictures.  The steering mode is
/// checked by the caller (the engine's own rule).
///
/// `imgs_below` gives the request's pictures below a length (the engine's imgs_below) and `images_equal` compares
/// that with the candidate's own pictures.  Both are callables, because the picture key's type belongs to the
/// engine's core and this header must not depend on it.
template<class ImgsBelow, class ImagesEqual>
inline CandidateAnalysis analyse(const Candidate& c, const std::vector<int32_t>& prompt, ImgsBelow imgs_below,
                                  ImagesEqual images_equal) {
    CandidateAnalysis a;
    // The engine's starts_with: a candidate of L tokens matches when L >= 1, L <= n - 1 (the last prompt token
    // always starts the next verify window) and every token agrees.
    const int64_t n = (int64_t) prompt.size();
    const int64_t L = (int64_t) c.n_ids;
    a.lcp = common_prefix(c.ids, c.n_ids, prompt.data(), prompt.size(), &a.mismatch);
    if (L < 1 || L > n - 1) {
        a.tokens_match = false;
        a.reason = Reason::token_mismatch;
        if (a.lcp == L && L >= 1) {
            // the candidate's tokens ARE the prompt's start, but the engine will not use it: the last prompt token
            // is never consumed by a checkpoint, so the candidate is ineligible for this request.
            a.reason = Reason::ineligible;
        }
        return a;
    }
    a.tokens_match = (a.lcp == L);
    if (!a.tokens_match) {
        a.reason = Reason::token_mismatch;
        return a;
    }
    // the tokens agree; now the pictures.  The engine compares the request's pictures below the candidate's
    // length with the candidate's own.
    a.images_match = images_equal(imgs_below(L), c.imgs);
    if (!a.images_match) {
        a.reason = Reason::image_mismatch;
        return a;
    }
    if (!c.steering_matches) {
        a.reason = Reason::steering_mismatch;
        return a;
    }
    a.reason = Reason::exact_match;
    return a;
}

/// The writer.  It writes one line per event to stderr, in a fixed key=value form that a log reader can parse
/// without a schema.  The output is bounded: one line per event, and the engine emits at most one decision event
/// per request plus one line per checkpoint that leaves or park that is refused.
class Writer {
public:
    /// The stream the events go to.  stderr by default (the engine's log), so the server's log reader sees them.
    explicit Writer(std::FILE* out = nullptr) : out_(out != nullptr ? out : stderr) {}

    void write(const CacheDiagEvent& e) {
        if (out_ == nullptr) return;
        std::fprintf(out_,
                     "STRATA_CACHE_DIAG event=%s request_seq=%llu prompt_tokens=%lld selected_source=%s "
                     "selected_prefix_tokens=%lld candidate_count=%lld max_candidate_prefix_tokens=%lld "
                     "longest_common_prefix_tokens=%lld first_mismatch_position=%lld rejection_reason=%s "
                     "cache_parked_entries=%zu cache_parked_bytes=%zu cache_evictions_total=%zu "
                     "subject_tokens=%lld subject_serial=%lld\n",
                     event_kind_name(e.kind), (unsigned long long) e.request_seq, (long long) e.prompt_tokens,
                     source_name(e.selected_source), (long long) e.selected_prefix_tokens,
                     (long long) e.candidate_count, (long long) e.max_candidate_prefix_tokens,
                     (long long) e.longest_common_prefix_tokens, (long long) e.first_mismatch_position,
                     reason_name(e.rejection_reason), e.cache_parked_entries, e.cache_parked_bytes,
                     e.cache_evictions_total, (long long) e.subject_tokens, (long long) e.subject_serial);
        std::fflush(out_);
    }

    std::FILE* stream() const { return out_; }

private:
    std::FILE* out_ = nullptr;
};

/// The engine's diagnostic sink.  `on()` is the gate; when it is off, `record()` does nothing at all, so the
/// caller can call it unconditionally without adding work to the request path.
class Sink {
public:
    static Sink& instance() {
        static Sink sink;
        return sink;
    }
    /// Whether the diagnostics are on.  Read once at the start of the run.
    bool on() const { return on_; }
    /// Write an event.  A no-op when the diagnostics are off.
    void record(const CacheDiagEvent& e) {
        if (!on_) return;
        writer_.write(e);
    }
    /// The writer, for the tests (a sink with its own stream).
    Writer& writer() { return writer_; }

private:
    Sink() : on_(enabled()) {}
    bool on_ = false;
    Writer writer_;
};

}  // namespace strata::program::cache_diag
