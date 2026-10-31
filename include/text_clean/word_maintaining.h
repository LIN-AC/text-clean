#pragma once

#include <cstddef>
#include <string>
#include <string_view>
#include <unordered_set>
#include <vector>

namespace text_clean {

// wordmaintaining: maintains word.txt (one word per line) as a hash table.
//
// The same table is used for:
//   * exact AC locking (the caller feeds words() into TextCleaner)
//   * longest-match segmentation of title/intro/body sections
//   * reporting unknown words for manual review and appending them back
//
// Lines are UTF-8. Blank lines and lines starting with '#' are ignored.
// Non-Han characters (punctuation, Latin letters, digits) act as token
// boundaries and are never reported as unknown words.
class WordMaintainer {
public:
    struct Token {
        std::u32string text;
        std::size_t begin = 0;  // code point offsets
        std::size_t end = 0;
        bool known = false;
    };

    struct UnknownSpan {
        std::u32string text;
        std::size_t begin = 0;
        std::size_t end = 0;
    };

    bool load_file(const std::string& path, std::string* error = nullptr);
    bool load_string(std::string_view content, std::string* error = nullptr);

    // Returns true when the word was new. Empty or duplicate words return
    // false and leave the table unchanged.
    bool add_word(std::u32string word);
    bool add_word_utf8(std::string_view word);

    // Appends only new words to path, flushing immediately, then updates the
    // in-memory table. The file is created when missing.
    bool append_words(const std::string& path,
                      const std::vector<std::u32string>& candidates,
                      std::size_t* added = nullptr, std::string* error = nullptr);
    bool append_words_utf8(const std::string& path,
                           const std::vector<std::string>& candidates,
                           std::size_t* added = nullptr, std::string* error = nullptr);

    bool contains(const std::u32string& word) const;
    bool contains_utf8(std::string_view word) const;

    std::size_t size() const { return words_.size(); }
    bool empty() const { return words_.empty(); }
    std::size_t max_word_length() const { return max_length_; }
    const std::vector<std::u32string>& words() const { return words_; }
    void clear();

    // Greedy forward maximum matching over contiguous Han runs.
    std::vector<Token> segment(const std::u32string& text) const;

    // Maximal runs of Han characters for which no dictionary word starts.
    // Spans shorter than min_length (code points) are omitted.
    std::vector<UnknownSpan> unknown_spans(const std::u32string& text,
                                           std::size_t min_length = 1) const;

private:
    std::size_t longest_match(const std::u32string& text, std::size_t start,
                              std::size_t limit) const;

    std::unordered_set<std::u32string> set_;
    std::vector<std::u32string> words_;
    std::size_t max_length_ = 0;
};

}  // namespace text_clean