#pragma once

#include <cstdint>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace text_clean {

// Character-level pinyin table. Loads lines of the form:
//
//   # comment
//   4e00<TAB>yi
//   957f<TAB>zhang,chang
//
// Readings are normalized to lowercase ASCII without tone marks; "ü" and
// "u:" become "v". The first reading of a character is its primary reading.
class PinyinDict {
public:
    struct Token {
        char32_t ch;
        std::string syllable;  // primary reading, empty when unavailable
        bool is_han;
        bool known;
    };

    bool add_char(char32_t ch, std::vector<std::string> readings);
    bool load_file(const std::string& path, std::string* error = nullptr);
    bool load_string(std::string_view content, std::string* error = nullptr);

    std::size_t size() const { return readings_.size(); }

    const std::vector<std::string>* readings(char32_t ch) const;
    std::string primary_reading(char32_t ch) const;

    // One token per code point, preserving alignment with the input.
    std::vector<Token> analyze(const std::u32string& text) const;

    // One syllable per code point, empty for non-Han or unknown characters.
    std::vector<std::string> to_pinyin(const std::u32string& text) const;

    static std::string normalize_reading(std::string_view reading);

private:
    std::unordered_map<char32_t, std::vector<std::string>> readings_;
};

}  // namespace text_clean
