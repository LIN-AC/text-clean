#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "text_clean/lexicon.h"
#include "text_clean/video_context.h"
#include "text_clean/vocabulary.h"
#include "text_clean/word_frequency.h"

namespace text_clean {

class PinyinDict;

struct CleanerConfig {
    bool enable_pinyin = true;

    // Maximum aligned tone-aware substitution distance accepted for a pinyin candidate. Tone-only
    // differences cost 1 and are searched by default; base differences cost 2.
    std::size_t max_pinyin_distance = 2;

    // Entries shorter than this may only match through exact pinyin
    // (distance 0). Two-syllable tone differences are evaluated because the
    // differential score is the final gate.
    std::size_t min_syllables_for_fuzzy = 2;

    // Entries shorter than this are not searched by pinyin at all.
    std::size_t min_syllables_for_exact_pinyin = 2;

    // Fuzzy matches must keep the first syllable base identical. This blocks
    // unrelated words that happen to share a later syllable.
    bool require_first_syllable_match = true;

    // Differential score:
    //   ΔS = ln((1+f(C))/(1+f(O))) - λ*D(O,C) - μ
    // A candidate needs ΔS > 0; overlapping alternatives also require a
    // margin > modification_threshold. Recognized original words are protected.
    double distance_penalty = 0.65;        // λ
    double modification_threshold = 0.70;  // μ

    std::size_t max_candidates_per_window = 64;
    char32_t mask_char = U'*';
};

enum class MatchKind {
    Exact,   // canonical form or alias found by the Aho-Corasick automaton
    Pinyin,  // same pinyin as a dictionary entry (distance 0)
    Fuzzy,   // close pinyin accepted by the edit distance fallback
};

// Status attached to a match. An exact AC hit is LockedByAc: its span is
// authoritative and the pinyin/edit-distance stages must not inspect or
// modify it again.
enum class MatchStatus : std::uint32_t {
    None = 0,
    LockedByAc = 1u << 0,
};

struct MatchRecord {
    MatchKind kind;
    MatchStatus status = MatchStatus::None;
    std::size_t begin;  // code point offsets in the original text
    std::size_t end;
    std::uint32_t entry_id;
    std::size_t distance;  // aligned tone-aware pinyin distance
    double score = 0.0;    // ΔS for pinyin/fuzzy; 0 for exact AC hits
    double log_ratio = 0.0;
    double context_bonus = 0.0;
    std::size_t candidate_frequency = 0;
    std::size_t original_frequency = 0;
    std::u32string matched;
    std::u32string replacement;
    Action action;
};

struct CleanResult {
    std::string text;
    std::vector<MatchRecord> matches;
};

// Orchestrates the cleaning modules:
//   1. exact word matching with the Aho-Corasick automaton; every hit carries
//      MatchStatus::LockedByAc
//   2. locked spans are excluded from all later stages
//   3. pinyin lookup + tone-aware edit distance only run on the remaining
//      text; candidate windows follow static-dictionary segmentation, with
//      limited cross-word windows around unknown spans; each candidate is
//      scored with word-frequency evidence and the highest score above zero
//      wins
//   4. locked hits apply their dictionary action (replace/mask/keep); pinyin
//      and fuzzy hits can never overlap them
//
// When ac_words is provided (even as an empty list), the automaton is built
// exclusively from those words. Words that are a canonical form or alias of a
// lexicon entry reuse that entry's action; all other words become Keep entries
// and are locked without being rewritten. When ac_words is omitted, patterns
// are gathered from the lexicon for backwards compatibility.
//
// Pinyin scoring requires a WordFrequency table. With an empty table the
// pinyin/fuzzy stage is skipped; AC locking still works.
class TextCleaner {
public:
    // Vocabulary is independent of priors/segmentation. Supply it explicitly
    // for low-frequency word protection (CLI loads data/dict.txt by default).
    TextCleaner(Lexicon lexicon, const PinyinDict& dict, CleanerConfig config = {},
                std::optional<std::vector<std::u32string>> ac_words = std::nullopt,
                WordFrequency frequencies = {}, Vocabulary vocabulary = {});
    ~TextCleaner();

    TextCleaner(TextCleaner&&) noexcept;
    TextCleaner& operator=(TextCleaner&&) noexcept;
    TextCleaner(const TextCleaner&) = delete;
    TextCleaner& operator=(const TextCleaner&) = delete;

    const CleanerConfig& config() const;
    CleanResult clean(std::string_view utf8_text) const;
    CleanResult clean(const std::u32string& text) const;
    // Reuse one context across all subtitle cues; destroy it after the video.
    VideoContext prepare_context(std::string_view title, std::string_view description,
                                 std::string_view raw_asr) const;
    CleanResult clean(std::string_view text, const VideoContext& context) const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace text_clean
