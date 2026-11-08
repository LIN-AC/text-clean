#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <unordered_map>
#include <optional>

namespace text_clean {

// Word frequency evidence for the differential score.
//
// File format: one <word><TAB><frequency> pair per line. Blank lines and lines
// starting with '#' are ignored. Duplicate words keep the largest count.
class WordFrequency {
public:
    bool load_file(const std::string& path, std::string* error = nullptr);
    bool load_string(std::string_view content, std::string* error = nullptr);

    // Inserts or raises the count for word. Returns false for an empty word.
    bool add_word(std::u32string word, std::uint64_t frequency);
    bool add_word_utf8(std::string_view word, std::uint64_t frequency);

    std::uint64_t count(const std::u32string& word) const;
    std::uint64_t count_utf8(std::string_view word) const;

    std::size_t size() const { return zipf_mode_ ? zipfs_.size() : counts_.size(); }
    bool empty() const { return zipf_mode_ ? zipfs_.empty() : counts_.empty(); }
    void clear() { counts_.clear(); zipfs_.clear(); char_zipfs_.clear(); zipf_mode_=false; }
    // Zipf=log10(occurrences per billion tokens). Missing is not zero.
    // This mode does not consume domain counts or character-independence counts.
    void use_zipf() { clear(); zipf_mode_=true; }
    bool is_zipf() const { return zipf_mode_; }
    void add_zipf(std::u32string word, double value);
    std::optional<double> zipf(const std::u32string& word) const;

    // 单字 Zipf 证据：只在 MissingEvidence::CharEstimate 下用来补原文缺口。
    // 与词级证据同尺度（每十亿词次的 log10），不参与旧次数口径。
    void add_char_zipf(char32_t ch, double value);
    std::optional<double> char_zipf(char32_t ch) const;
    std::size_t char_size() const { return char_zipfs_.size(); }

    const std::unordered_map<std::u32string, std::uint64_t>& entries() const {
        return counts_;
    }

private:
    std::unordered_map<std::u32string, std::uint64_t> counts_;
    std::unordered_map<std::u32string, double> zipfs_;
    std::unordered_map<char32_t, double> char_zipfs_;
    bool zipf_mode_ = false;
};

}  // namespace text_clean
