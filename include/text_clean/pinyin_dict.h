#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace text_clean {

// Character-level pinyin table. Loads lines of the form:
//
//   # comment
//   4e00<TAB>yi1
//   957f<TAB>zhang3,chang2
//
// Base syllables are lowercase ASCII without tone marks ("ü"/"u:" become "v").
// Tone numbers are 1-4 and 5 for the neutral tone. A tone-marked reading
// without a digit (e.g. "wēi") keeps its tone; a completely tone-less reading
// has tone 0 (unknown, treated as a wildcard when comparing tones). The first
// reading of a character is its primary reading.
class PinyinDict {
public:
    struct Token {
        char32_t ch;
        std::string syllable;  // primary reading, empty when unavailable
        bool is_han;
        bool known;
    };

    struct TonedReading {
        std::string base;
        int tone = 0;  // 1-4, 5 = neutral, 0 = unknown

        friend bool operator==(const TonedReading& a, const TonedReading& b) {
            return a.base == b.base && a.tone == b.tone;
        }
    };

    struct TonedSyllable {
        std::vector<TonedReading> readings;
        bool known = false;
    };

    bool add_char(char32_t ch, std::vector<std::string> readings);
    bool load_file(const std::string& path, std::string* error = nullptr);
    bool load_string(std::string_view content, std::string* error = nullptr);

    std::size_t size() const { return readings_.size(); }

    const std::vector<std::string>* readings(char32_t ch) const;
    const std::vector<TonedReading>* toned_readings(char32_t ch) const;
    std::string primary_reading(char32_t ch) const;

    // One token per code point, preserving alignment with the input.
    std::vector<Token> analyze(const std::u32string& text) const;

    // One syllable per code point, empty for non-Han or unknown characters.
    std::vector<std::string> to_pinyin(const std::u32string& text) const;

    // One syllable entry per code point, with every tone-bearing reading.
    std::vector<TonedSyllable> to_toned_syllables(const std::u32string& text) const;

    // Two syllables match when any reading pair has the same base and tone.
    // Tone 0 is unknown and acts as a wildcard; neutral tone 5 is a real tone.
    static bool toned_syllable_equal(const TonedSyllable& a, const TonedSyllable& b);

    // Tone-aware Levenshtein distance over syllable sequences. Substitution
    // costs are fixed: same base+tone 0, tone-only difference 1, different
    // base 2; insertion/deletion costs 1. Returns max_distance+1 when exceeded.
    static std::size_t toned_distance(const std::vector<TonedSyllable>& a,
                                      const std::vector<TonedSyllable>& b,
                                      std::size_t max_distance);

    // Equal-length substitution-only distance; no shifted insert/delete path.
    static std::size_t aligned_distance(const std::vector<TonedSyllable>& a,
                                        const std::vector<TonedSyllable>& b,
                                        std::size_t max_distance);
    static std::string normalize_reading(std::string_view reading);

private:
    std::unordered_map<char32_t, std::vector<std::string>> readings_;
    std::unordered_map<char32_t, std::vector<TonedReading>> toned_readings_;
};

}  // namespace text_clean
