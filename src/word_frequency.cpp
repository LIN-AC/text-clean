#include "text_clean/word_frequency.h"

#include <algorithm>
#include <fstream>
#include <iterator>
#include <cmath>
#include <stdexcept>

#include "text_clean/utf8.h"

namespace text_clean {
namespace {

std::string_view trim(std::string_view value) {
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

bool parse_count(std::string_view text, std::uint64_t* out) {
    if (text.empty()) return false;
    std::uint64_t value = 0;
    for (const char ch : text) {
        if (ch < '0' || ch > '9') return false;
        const std::uint64_t digit = static_cast<std::uint64_t>(ch - '0');
        if (value > (UINT64_MAX - digit) / 10) return false;
        value = value * 10 + digit;
    }
    *out = value;
    return true;
}

bool fail(std::string* error, std::size_t line, std::string_view message) {
    if (error != nullptr) {
        *error = "line " + std::to_string(line) + ": " + std::string(message);
    }
    return false;
}

}  // namespace

bool WordFrequency::load_string(std::string_view content, std::string* error) {
    if (error != nullptr) error->clear();
    if (content.size() >= 3 &&
        static_cast<unsigned char>(content[0]) == 0xEF &&
        static_cast<unsigned char>(content[1]) == 0xBB &&
        static_cast<unsigned char>(content[2]) == 0xBF) {
        content.remove_prefix(3);
    }

    WordFrequency parsed;
    std::size_t line_number = 0;
    std::size_t position = 0;

    while (position < content.size()) {
        const std::size_t newline = content.find('\n', position);
        std::string_view line = content.substr(
            position, newline == std::string_view::npos ? std::string_view::npos
                                                        : newline - position);
        position = newline == std::string_view::npos ? content.size() : newline + 1;
        ++line_number;

        if (!line.empty() && line.back() == '\r') line.remove_suffix(1);
        line = trim(line);
        if (line.empty() || line.front() == '#') continue;

        const std::size_t separator = line.find_last_of(" \t");
        if (separator == std::string_view::npos) {
            return fail(error, line_number, "missing frequency");
        }
        const std::string_view word = trim(line.substr(0, separator));
        const std::string_view count_text = trim(line.substr(separator + 1));
        if (word.empty()) {
            return fail(error, line_number, "empty word");
        }
        std::uint64_t count = 0;
        if (!parse_count(count_text, &count)) {
            return fail(error, line_number, "invalid frequency");
        }

        parsed.add_word(utf8::decode(word), count);
    }

    *this = std::move(parsed);
    return true;
}

bool WordFrequency::load_file(const std::string& path, std::string* error) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        if (error != nullptr) *error = "cannot open word frequency file: " + path;
        return false;
    }
    const std::string content((std::istreambuf_iterator<char>(input)),
                              std::istreambuf_iterator<char>());
    return load_string(content, error);
}

bool WordFrequency::add_word(std::u32string word, std::uint64_t frequency) {
    if(zipf_mode_) throw std::logic_error("cannot mix counts and Zipf frequencies");
    word = trim_word(std::move(word));
    if (word.empty()) return false;
    auto& stored = counts_[word];
    stored = std::max(stored, frequency);
    return true;
}

bool WordFrequency::add_word_utf8(std::string_view word, std::uint64_t frequency) {
    return add_word(utf8::decode(word), frequency);
}

std::uint64_t WordFrequency::count(const std::u32string& word) const {
    const auto it = counts_.find(word);
    return it == counts_.end() ? 0 : it->second;
}

std::uint64_t WordFrequency::count_utf8(std::string_view word) const {
    return count(utf8::decode(word));
}

void WordFrequency::add_zipf(std::u32string word, double value) {
    if(!zipf_mode_) throw std::logic_error("select Zipf mode before adding evidence");
    if(word.empty() || !std::isfinite(value) || value<=0 || value>10)
        throw std::invalid_argument("Zipf evidence must be finite and positive; absent evidence is not zero");
    zipfs_[std::move(word)]=value;
}
std::optional<double> WordFrequency::zipf(const std::u32string& word) const {
    auto it=zipfs_.find(word);
    return it==zipfs_.end()?std::nullopt:std::optional<double>(it->second);
}
void WordFrequency::add_char_zipf(char32_t ch, double value) {
    if(!zipf_mode_) throw std::logic_error("select Zipf mode before adding evidence");
    if(ch == 0 || !std::isfinite(value) || value<=0 || value>10)
        throw std::invalid_argument("character Zipf evidence must be finite and positive");
    char_zipfs_[ch]=value;
}
std::optional<double> WordFrequency::char_zipf(char32_t ch) const {
    auto it=char_zipfs_.find(ch);
    return it==char_zipfs_.end()?std::nullopt:std::optional<double>(it->second);
}
}  // namespace text_clean
