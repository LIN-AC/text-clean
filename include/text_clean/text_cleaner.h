#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "text_clean/char_frequency.h"
#include "text_clean/lexicon.h"
#include "text_clean/video_context.h"
#include "text_clean/vocabulary.h"
#include "text_clean/word_frequency.h"

namespace text_clean {

class PinyinDict;

struct CleanerConfig {
    bool enable_pinyin = true;
    std::string index_cache_path; // optional generated cache; never a candidate source

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
    //   Zipf mode: ΔS = 2.302585*(ZipfC-ZipfO) - λ*D(O,C) - μ
    //   Legacy counts: ΔS = ln((1+f(C))/(1+f(O))) - λ*D(O,C) - μ
    // A candidate needs ΔS > 0; overlapping alternatives also require a
    // margin > modification_threshold. AC-locked characters are protected.
    // f(C) is the candidate's raw table frequency; f(O) is the original's raw
    // frequency when attested, otherwise its chance frequency under character
    // independence (see CharFrequency). Neither side is floored.
    double distance_penalty = 0.65;        // λ
    double modification_threshold = 0.70;  // μ

    std::size_t max_candidates_per_window = 64;
    char32_t mask_char = U'*';
};

enum class MatchKind {
    Exact,   // explicit protection found by the Aho-Corasick automaton
    Pinyin,  // same pinyin as a dictionary entry (distance 0)
    Fuzzy,   // close pinyin accepted by the edit distance fallback
};

// AC hits preserve their original characters, which remain usable as context.
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
    std::optional<double> candidate_zipf = std::nullopt, original_zipf = std::nullopt;
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

// AC only locks original characters. Candidate windows may include locks,
// but every changed position must be unlocked. Only Replace candidates enter
// pronunciation/scoring; legacy Mask actions have no execution permission.
// Vocabulary provides segmentation/reference, not an unconditional veto.
// With no count-frequency table, no replacements are proposed.
class TextCleaner {
public:
    // Vocabulary supplies segmentation/reference only; AC words alone lock.
    TextCleaner(Lexicon lexicon, const PinyinDict& dict, CleanerConfig config = {},
                std::optional<std::vector<std::u32string>> ac_words = std::nullopt,
                WordFrequency frequencies = {}, Vocabulary vocabulary = {},
                CharFrequency char_frequency = {});
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
