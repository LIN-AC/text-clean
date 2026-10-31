#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "text_clean/lexicon.h"

namespace text_clean {

class PinyinDict;

struct CleanerConfig {
    bool enable_pinyin = true;

    // Maximum syllable-level Levenshtein distance accepted for a fuzzy match.
    std::size_t max_pinyin_distance = 1;

    // Entries shorter than this may only match through exact pinyin
    // (distance 0). Short fuzzy matches are very prone to false positives.
    std::size_t min_syllables_for_fuzzy = 3;

    // Entries shorter than this are not searched by pinyin at all.
    std::size_t min_syllables_for_exact_pinyin = 2;

    // Fuzzy matches must keep the first syllable identical. This blocks
    // unrelated words that happen to share a later syllable.
    bool require_first_syllable_match = true;

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
    std::size_t distance;
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
//   3. pinyin lookup + edit distance only run on the remaining text
//   4. locked hits apply their dictionary action (replace/mask/keep); pinyin
//      and fuzzy hits can never overlap them
//
// When ac_words is provided (even as an empty list), the automaton is built
// exclusively from those words. Words that are a canonical form or alias of a
// lexicon entry reuse that entry's action; all other words become Keep entries
// and are locked without being rewritten. When ac_words is omitted, patterns
// are gathered from the lexicon for backwards compatibility.
class TextCleaner {
public:
    TextCleaner(Lexicon lexicon, const PinyinDict& dict, CleanerConfig config = {},
                std::optional<std::vector<std::u32string>> ac_words = std::nullopt);
    ~TextCleaner();

    TextCleaner(TextCleaner&&) noexcept;
    TextCleaner& operator=(TextCleaner&&) noexcept;
    TextCleaner(const TextCleaner&) = delete;
    TextCleaner& operator=(const TextCleaner&) = delete;

    const CleanerConfig& config() const;
    CleanResult clean(std::string_view utf8_text) const;
    CleanResult clean(const std::u32string& text) const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace text_clean
