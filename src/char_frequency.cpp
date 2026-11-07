#include "text_clean/char_frequency.h"

#include <cctype>
#include <fstream>
#include <iterator>

#include "text_clean/utf8.h"

namespace text_clean {
namespace {

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

std::string_view next_field(std::string_view line, std::size_t* position) {
    const std::size_t n = line.size();
    while (*position < n && (line[*position] == ' ' || line[*position] == '\t' ||
                             line[*position] == '\r')) {
        ++*position;
    }
    const std::size_t begin = *position;
    while (*position < n && line[*position] != ' ' && line[*position] != '\t' &&
           line[*position] != '\r') {
        ++*position;
    }
    return line.substr(begin, *position - begin);
}

}  // namespace

void CharFrequency::add(char32_t ch, std::uint64_t count) {
    if (ch == 0 || !utf8::is_han(ch) || count == 0) return;
    auto it = counts_.find(ch);
    if (it == counts_.end()) {
        counts_.emplace(ch, count);
        total_ += static_cast<double>(count);
    } else {
        total_ += static_cast<double>(count);
        it->second += count;
    }
}

std::uint64_t CharFrequency::count(char32_t ch) const {
    const auto it = counts_.find(ch);
    return it == counts_.end() ? 0 : it->second;
}

double CharFrequency::probability(char32_t ch) const {
    if (total_ <= 0.0) return 0.0;
    return (static_cast<double>(count(ch)) + 0.5) / (total_ + 0.5);
}

double CharFrequency::expected_count(const std::u32string& span) const {
    if (span.empty() || counts_.empty() || total_ <= 0.0) return 0.0;
    double p = 1.0;
    for (const char32_t ch : span) {
        p *= probability(ch);
        if (p <= 0.0) return 0.0;
    }
    return total_ * p;
}

bool CharFrequency::load_string(std::string_view content, std::string* error) {
    if (error != nullptr) error->clear();
    if (content.size() >= 3 && static_cast<unsigned char>(content[0]) == 0xEF &&
        static_cast<unsigned char>(content[1]) == 0xBB &&
        static_cast<unsigned char>(content[2]) == 0xBF) {
        content.remove_prefix(3);
    }

    CharFrequency parsed;
    std::size_t position = 0;
    while (position < content.size()) {
        const std::size_t newline = content.find('\n', position);
        const std::string_view line = content.substr(
            position, newline == std::string_view::npos ? std::string_view::npos
                                                        : newline - position);
        position = newline == std::string_view::npos ? content.size() : newline + 1;
        if (line.empty() || line.front() == '#') continue;

        std::size_t cursor = 0;
        const std::string_view word = next_field(line, &cursor);
        // A single Han character is 3 UTF-8 bytes (4 for extension B); checking
        // the length first avoids decoding the ~340k multi-character rows.
        if (word.size() != 3 && word.size() != 4) continue;
        const std::string_view count_text = next_field(line, &cursor);
        std::uint64_t count = 0;
        if (!parse_count(count_text, &count)) continue;

        const std::u32string points = utf8::decode(word);
        if (points.size() != 1) continue;
        parsed.add(points.front(), count);
    }

    if (parsed.empty()) {
        if (error != nullptr) {
            *error = "no single-character frequencies found";
        }
        return false;
    }
    *this = std::move(parsed);
    return true;
}

bool CharFrequency::load_file(const std::string& path, std::string* error) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        if (error != nullptr) *error = "cannot open character frequency file: " + path;
        return false;
    }
    const std::string content((std::istreambuf_iterator<char>(input)),
                              std::istreambuf_iterator<char>());
    return load_string(content, error);
}

}  // namespace text_clean
