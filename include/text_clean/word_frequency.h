#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <unordered_map>

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

    std::size_t size() const { return counts_.size(); }
    bool empty() const { return counts_.empty(); }
    void clear() { counts_.clear(); }

    const std::unordered_map<std::u32string, std::uint64_t>& entries() const {
        return counts_;
    }

private:
    std::unordered_map<std::u32string, std::uint64_t> counts_;
};

}  // namespace text_clean