#include "text_clean/pinyin_dict.h"

#include <algorithm>
#include <fstream>
#include <iterator>

#include "text_clean/edit_distance.h"
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

bool set_error(std::string* error, std::size_t line, std::string_view message) {
    if (error != nullptr) {
        *error = "line " + std::to_string(line) + ": " + std::string(message);
    }
    return false;
}

int tone_number(char32_t ch) {
    switch (ch) {
        // first tone
        case 0x0101: case 0x0113: case 0x012B: case 0x014D: case 0x016B:
        case 0x01D6:
            return 1;
        // second tone
        case 0x00E1: case 0x00E9: case 0x00ED: case 0x00F3: case 0x00FA:
        case 0x01D8:
            return 2;
        // third tone
        case 0x01CE: case 0x011B: case 0x01D0: case 0x01D2: case 0x01D4:
        case 0x01DA:
            return 3;
        // fourth tone
        case 0x00E0: case 0x00E8: case 0x00EC: case 0x00F2: case 0x00F9:
        case 0x01DC:
            return 4;
        default:
            return 0;
    }
}

char32_t tone_base(char32_t ch) {
    switch (ch) {
        // a
        case 0x0101: case 0x00E1: case 0x01CE: case 0x00E0:
            return U'a';
        // e / ê
        case 0x0113: case 0x00E9: case 0x011B: case 0x00E8: case 0x00EA:
            return U'e';
        // i
        case 0x012B: case 0x00ED: case 0x01D0: case 0x00EC:
            return U'i';
        // o
        case 0x014D: case 0x00F3: case 0x01D2: case 0x00F2:
            return U'o';
        // u
        case 0x016B: case 0x00FA: case 0x01D4: case 0x00F9:
            return U'u';
        // ü / ǖ ǘ ǚ ǜ
        case 0x00FC: case 0x01D6: case 0x01D8: case 0x01DA: case 0x01DC:
            return U'v';
        default:
            return ch;
    }
}

bool parse_codepoint(std::string_view text, char32_t* out) {
    text = trim(text);
    if (text.size() >= 2 && (text[0] == 'U' || text[0] == 'u') && text[1] == '+') {
        text.remove_prefix(2);
    } else if (text.size() >= 2 && text[0] == '0' && (text[1] == 'x' || text[1] == 'X')) {
        text.remove_prefix(2);
    }
    if (text.empty()) return false;

    std::uint32_t value = 0;
    for (const char ch : text) {
        std::uint32_t digit = 0;
        if (ch >= '0' && ch <= '9') {
            digit = static_cast<std::uint32_t>(ch - '0');
        } else if (ch >= 'a' && ch <= 'f') {
            digit = static_cast<std::uint32_t>(ch - 'a' + 10);
        } else if (ch >= 'A' && ch <= 'F') {
            digit = static_cast<std::uint32_t>(ch - 'A' + 10);
        } else {
            return false;
        }
        value = (value << 4) | digit;
        if (value > 0x10FFFF) return false;
    }
    if (value >= 0xD800 && value <= 0xDFFF) return false;
    *out = static_cast<char32_t>(value);
    return true;
}

bool parse_toned_reading(std::string_view reading, PinyinDict::TonedReading* out) {
    const std::string base = PinyinDict::normalize_reading(reading);
    if (base.empty()) return false;

    int tone = 0;
    const std::string_view trimmed = trim(reading);
    if (!trimmed.empty() && trimmed.back() >= '1' && trimmed.back() <= '5') {
        tone = trimmed.back() - '0';
    } else {
        for (char32_t ch : utf8::decode(reading)) {
            const int detected = tone_number(ch);
            if (detected != 0) {
                tone = detected;
                break;
            }
        }
    }
    *out = PinyinDict::TonedReading{base, tone};
    return true;
}

}  // namespace

std::string PinyinDict::normalize_reading(std::string_view reading) {
    std::string out;
    out.reserve(reading.size());
    for (char32_t ch : utf8::decode(reading)) {
        if (ch >= U'a' && ch <= U'z') {
            out.push_back(static_cast<char>(ch));
        } else if (ch >= U'A' && ch <= U'Z') {
            out.push_back(static_cast<char>(ch - U'A' + U'a'));
        } else if (ch >= U'0' && ch <= U'9') {
            continue;  // tone number
        } else if (ch == U':') {
            if (!out.empty() && out.back() == 'u') out.back() = 'v';  // u: -> v
        } else {
            const char32_t base = tone_base(ch);
            if (base >= U'a' && base <= U'z') {
                out.push_back(static_cast<char>(base));
            }
        }
    }
    return out;
}

bool PinyinDict::add_char(char32_t ch, std::vector<std::string> readings) {
    std::vector<TonedReading> parsed;
    for (const auto& reading : readings) {
        TonedReading toned;
        if (!parse_toned_reading(reading, &toned)) continue;
        if (std::find(parsed.begin(), parsed.end(), toned) == parsed.end()) {
            parsed.push_back(std::move(toned));
        }
    }
    if (parsed.empty()) return false;

    auto& bases = readings_[ch];
    auto& tones = toned_readings_[ch];
    for (const auto& reading : parsed) {
        if (std::find(bases.begin(), bases.end(), reading.base) == bases.end()) {
            bases.push_back(reading.base);
        }
        if (std::find(tones.begin(), tones.end(), reading) == tones.end()) {
            tones.push_back(reading);
        }
    }
    return true;
}

const std::vector<std::string>* PinyinDict::readings(char32_t ch) const {
    const auto it = readings_.find(ch);
    return it == readings_.end() ? nullptr : &it->second;
}

const std::vector<PinyinDict::TonedReading>* PinyinDict::toned_readings(
    char32_t ch) const {
    const auto it = toned_readings_.find(ch);
    return it == toned_readings_.end() ? nullptr : &it->second;
}

std::string PinyinDict::primary_reading(char32_t ch) const {
    const auto* values = readings(ch);
    return (values == nullptr || values->empty()) ? std::string() : values->front();
}

std::vector<PinyinDict::Token> PinyinDict::analyze(const std::u32string& text) const {
    std::vector<Token> tokens;
    tokens.reserve(text.size());
    for (const char32_t ch : text) {
        Token token{ch, std::string(), utf8::is_han(ch), false};
        if (token.is_han) {
            const auto* values = readings(ch);
            if (values != nullptr && !values->empty()) {
                token.syllable = values->front();
                token.known = true;
            }
        }
        tokens.push_back(std::move(token));
    }
    return tokens;
}

std::vector<std::string> PinyinDict::to_pinyin(const std::u32string& text) const {
    std::vector<std::string> syllables;
    syllables.reserve(text.size());
    for (const char32_t ch : text) {
        syllables.push_back(primary_reading(ch));
    }
    return syllables;
}

std::vector<PinyinDict::TonedSyllable> PinyinDict::to_toned_syllables(
    const std::u32string& text) const {
    std::vector<TonedSyllable> syllables;
    syllables.reserve(text.size());
    for (const char32_t ch : text) {
        TonedSyllable syllable;
        const auto* values = toned_readings(ch);
        if (values != nullptr && !values->empty()) {
            syllable.readings = *values;
            syllable.known = true;
        }
        syllables.push_back(std::move(syllable));
    }
    return syllables;
}

bool PinyinDict::toned_syllable_equal(const TonedSyllable& a,
                                      const TonedSyllable& b) {
    for (const auto& left : a.readings) {
        for (const auto& right : b.readings) {
            if (left.base != right.base) continue;
            if (left.tone == right.tone || left.tone == 0 || right.tone == 0) {
                return true;
            }
        }
    }
    return false;
}

std::size_t PinyinDict::toned_distance(const std::vector<TonedSyllable>& a,
                                       const std::vector<TonedSyllable>& b,
                                       std::size_t max_distance) {
    return levenshtein_bounded_with(
        a, b, max_distance,
        [](const TonedSyllable& left, const TonedSyllable& right) {
            bool same_base = false;
            for (const auto& l : left.readings) {
                for (const auto& r : right.readings) {
                    if (l.base != r.base) continue;
                    same_base = true;
                    if (l.tone == r.tone || l.tone == 0 || r.tone == 0) return 0;
                }
            }
            return same_base ? 1 : 2;
        });
}

std::size_t PinyinDict::aligned_distance(const std::vector<TonedSyllable>& a,
                                        const std::vector<TonedSyllable>& b,
                                        std::size_t limit) {
    if (a.size() != b.size()) return limit + 1;
    std::size_t total = 0;
    for (std::size_t i = 0; i < a.size(); ++i) {
        std::size_t cost = 2;
        for (const auto& x : a[i].readings) for (const auto& y : b[i].readings) {
            if (x.base != y.base) continue;
            cost = std::min(cost, std::size_t{x.tone == y.tone || x.tone == 0 || y.tone == 0 ? 0u : 1u});
        }
        if (cost > limit - total) return limit + 1;
        total += cost;
    }
    return total;
}

bool PinyinDict::load_string(std::string_view content, std::string* error) {
    if (error != nullptr) error->clear();
    if (content.size() >= 3 &&
        static_cast<unsigned char>(content[0]) == 0xEF &&
        static_cast<unsigned char>(content[1]) == 0xBB &&
        static_cast<unsigned char>(content[2]) == 0xBF) {
        content.remove_prefix(3);
    }

    PinyinDict parsed;
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

        const std::size_t separator = line.find_first_of(" \t");
        if (separator == std::string_view::npos) {
            return set_error(error, line_number, "missing readings");
        }

        char32_t codepoint = 0;
        if (!parse_codepoint(line.substr(0, separator), &codepoint)) {
            return set_error(error, line_number, "invalid code point");
        }

        const std::string_view payload = trim(line.substr(separator + 1));
        if (payload.empty()) {
            return set_error(error, line_number, "missing readings");
        }

        std::vector<TonedReading> values;
        std::size_t start = 0;
        while (start <= payload.size()) {
            const std::size_t comma = payload.find(',', start);
            std::string_view piece = trim(payload.substr(
                start, comma == std::string_view::npos ? std::string_view::npos
                                                       : comma - start));
            if (piece.find_first_of(" \t") != std::string_view::npos) {
                return set_error(error, line_number, "whitespace inside reading");
            }
            TonedReading toned;
            if (!parse_toned_reading(piece, &toned)) {
                return set_error(error, line_number, "empty or invalid reading");
            }
            if (std::find(values.begin(), values.end(), toned) == values.end()) {
                values.push_back(std::move(toned));
            }
            if (comma == std::string_view::npos) break;
            start = comma + 1;
        }

        auto& bases = parsed.readings_[codepoint];
        auto& tones = parsed.toned_readings_[codepoint];
        for (const auto& value : values) {
            if (std::find(bases.begin(), bases.end(), value.base) == bases.end()) {
                bases.push_back(value.base);
            }
            if (std::find(tones.begin(), tones.end(), value) == tones.end()) {
                tones.push_back(value);
            }
        }
    }

    readings_ = std::move(parsed.readings_);
    toned_readings_ = std::move(parsed.toned_readings_);
    return true;
}

bool PinyinDict::load_file(const std::string& path, std::string* error) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        if (error != nullptr) *error = "cannot open pinyin dictionary: " + path;
        return false;
    }
    const std::string content((std::istreambuf_iterator<char>(input)),
                              std::istreambuf_iterator<char>());
    return load_string(content, error);
}

}  // namespace text_clean
