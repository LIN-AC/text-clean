#include "text_clean/word_maintaining.h"

#include <algorithm>
#include <fstream>
#include <iterator>

#include "text_clean/utf8.h"

namespace text_clean {
namespace {

std::string_view trim_ascii(std::string_view value) {
    while (!value.empty() &&
           (value.front() == ' ' || value.front() == '\t' || value.front() == '\r')) {
        value.remove_prefix(1);
    }
    while (!value.empty() &&
           (value.back() == ' ' || value.back() == '\t' || value.back() == '\r')) {
        value.remove_suffix(1);
    }
    return value;
}

std::u32string trim_word(std::u32string word) {
    std::size_t begin = 0;
    std::size_t end = word.size();
    while (begin < end &&
           (word[begin] == U' ' || word[begin] == U'\t' || word[begin] == U'\r')) {
        ++begin;
    }
    while (end > begin &&
           (word[end - 1] == U' ' || word[end - 1] == U'\t' || word[end - 1] == U'\r')) {
        --end;
    }
    if (begin == 0 && end == word.size()) return word;
    return word.substr(begin, end - begin);
}

bool file_needs_newline(const std::string& path) {
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input) return false;
    const std::streamoff size = input.tellg();
    if (size <= 0) return false;
    input.seekg(-1, std::ios::end);
    char last = '\0';
    input.get(last);
    return last != '\n';
}

}  // namespace

bool WordMaintainer::load_string(std::string_view content, std::string* error) {
    if (error != nullptr) error->clear();
    if (content.size() >= 3 &&
        static_cast<unsigned char>(content[0]) == 0xEF &&
        static_cast<unsigned char>(content[1]) == 0xBB &&
        static_cast<unsigned char>(content[2]) == 0xBF) {
        content.remove_prefix(3);
    }

    WordMaintainer parsed;
    std::size_t position = 0;
    while (position < content.size()) {
        const std::size_t newline = content.find('\n', position);
        std::string_view line = content.substr(
            position, newline == std::string_view::npos ? std::string_view::npos
                                                        : newline - position);
        position = newline == std::string_view::npos ? content.size() : newline + 1;

        line = trim_ascii(line);
        if (line.empty() || line.front() == '#') continue;
        parsed.add_word(utf8::decode(line));
    }

    *this = std::move(parsed);
    return true;
}

bool WordMaintainer::load_file(const std::string& path, std::string* error) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        if (error != nullptr) *error = "cannot open word file: " + path;
        return false;
    }
    const std::string content((std::istreambuf_iterator<char>(input)),
                              std::istreambuf_iterator<char>());
    return load_string(content, error);
}

bool WordMaintainer::add_word(std::u32string word) {
    word = trim_word(std::move(word));
    if (word.empty()) return false;
    if (!set_.insert(word).second) return false;
    max_length_ = std::max(max_length_, word.size());
    words_.push_back(std::move(word));
    return true;
}

bool WordMaintainer::add_word_utf8(std::string_view word) {
    return add_word(utf8::decode(word));
}

bool WordMaintainer::append_words(const std::string& path,
                                  const std::vector<std::u32string>& candidates,
                                  std::size_t* added, std::string* error) {
    if (error != nullptr) error->clear();
    if (added != nullptr) *added = 0;
    if (path.empty()) {
        if (error != nullptr) *error = "word file path is empty";
        return false;
    }

    std::vector<std::u32string> pending;
    std::unordered_set<std::u32string> pending_set;
    for (auto word : candidates) {
        word = trim_word(std::move(word));
        if (word.empty() || set_.count(word) != 0) continue;
        if (!pending_set.insert(word).second) continue;
        pending.push_back(std::move(word));
    }
    if (pending.empty()) return true;

    std::ofstream output(path, std::ios::binary | std::ios::app);
    if (!output) {
        if (error != nullptr) *error = "cannot open word file for append: " + path;
        return false;
    }
    if (file_needs_newline(path)) output.put('\n');
    for (const auto& word : pending) {
        output << utf8::encode(word) << '\n';
    }
    output.flush();
    if (!output.good()) {
        if (error != nullptr) *error = "failed to write word file: " + path;
        return false;
    }

    for (auto& word : pending) {
        set_.insert(word);
        max_length_ = std::max(max_length_, word.size());
        words_.push_back(std::move(word));
    }
    if (added != nullptr) *added = pending.size();
    return true;
}

bool WordMaintainer::append_words_utf8(const std::string& path,
                                       const std::vector<std::string>& candidates,
                                       std::size_t* added, std::string* error) {
    std::vector<std::u32string> decoded;
    decoded.reserve(candidates.size());
    for (const auto& candidate : candidates) {
        decoded.push_back(utf8::decode(candidate));
    }
    return append_words(path, decoded, added, error);
}

bool WordMaintainer::contains(const std::u32string& word) const {
    return set_.find(word) != set_.end();
}

bool WordMaintainer::contains_utf8(std::string_view word) const {
    return contains(utf8::decode(word));
}

void WordMaintainer::clear() {
    set_.clear();
    words_.clear();
    max_length_ = 0;
}

std::size_t WordMaintainer::longest_match(const std::u32string& text,
                                          std::size_t start,
                                          std::size_t limit) const {
    if (max_length_ == 0) return 0;
    const std::size_t max_length = std::min(max_length_, limit - start);
    for (std::size_t length = max_length; length >= 1; --length) {
        if (set_.find(text.substr(start, length)) != set_.end()) return length;
    }
    return 0;
}

std::vector<WordMaintainer::Token> WordMaintainer::segment(
    const std::u32string& text) const {
    std::vector<Token> tokens;
    std::size_t i = 0;
    while (i < text.size()) {
        if (!utf8::is_han(text[i])) {
            const std::size_t begin = i;
            while (i < text.size() && !utf8::is_han(text[i])) ++i;
            tokens.push_back(Token{text.substr(begin, i - begin), begin, i, true});
            continue;
        }

        std::size_t run_end = i;
        while (run_end < text.size() && utf8::is_han(text[run_end])) ++run_end;

        while (i < run_end) {
            const std::size_t length = longest_match(text, i, run_end);
            if (length != 0) {
                tokens.push_back(Token{text.substr(i, length), i, i + length, true});
                i += length;
                continue;
            }

            const std::size_t begin = i;
            ++i;
            while (i < run_end && longest_match(text, i, run_end) == 0) ++i;
            tokens.push_back(Token{text.substr(begin, i - begin), begin, i, false});
        }
    }
    return tokens;
}

std::vector<WordMaintainer::UnknownSpan> WordMaintainer::unknown_spans(
    const std::u32string& text, std::size_t min_length) const {
    std::vector<UnknownSpan> spans;
    for (const auto& token : segment(text)) {
        if (token.known) continue;
        if (token.text.size() < min_length) continue;
        spans.push_back(UnknownSpan{token.text, token.begin, token.end});
    }
    return spans;
}

}  // namespace text_clean