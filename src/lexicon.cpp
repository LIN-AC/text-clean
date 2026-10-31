#include "text_clean/lexicon.h"

#include <algorithm>
#include <fstream>
#include <iterator>

#include "text_clean/utf8.h"

namespace text_clean {
namespace {

std::string_view trim(std::string_view value) {
    // Tabs are column separators and must be preserved; only pad characters
    // and carriage returns are stripped.
    while (!value.empty() && (value.front() == ' ' || value.front() == '\r')) {
        value.remove_prefix(1);
    }
    while (!value.empty() && (value.back() == ' ' || value.back() == '\r')) {
        value.remove_suffix(1);
    }
    return value;
}

std::string ascii_lower(std::string_view value) {
    std::string out(value);
    for (char& ch : out) {
        if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch - 'A' + 'a');
    }
    return out;
}

bool fail(std::string* error, std::size_t line, std::string_view message) {
    if (error != nullptr) {
        *error = "line " + std::to_string(line) + ": " + std::string(message);
    }
    return false;
}

std::vector<std::string_view> split_tabs(std::string_view line) {
    std::vector<std::string_view> fields;
    while (true) {
        const std::size_t tab = line.find('\t');
        if (tab == std::string_view::npos) {
            fields.push_back(line);
            break;
        }
        fields.push_back(line.substr(0, tab));
        line.remove_prefix(tab + 1);
    }
    return fields;
}

std::vector<std::string_view> split_aliases(std::string_view field) {
    std::vector<std::string_view> aliases;
    std::size_t start = 0;
    std::size_t i = 0;
    while (i < field.size()) {
        if (field[i] == ',') {
            aliases.push_back(field.substr(start, i - start));
            ++i;
            start = i;
        } else if (i + 3 <= field.size() && field.substr(i, 3) == "\xEF\xBC\x8C") {
            aliases.push_back(field.substr(start, i - start));
            i += 3;
            start = i;
        } else {
            ++i;
        }
    }
    aliases.push_back(field.substr(start));
    return aliases;
}

bool parse_action(std::string_view field, Action* action, std::size_t line,
                  std::string* error) {
    const std::string value = ascii_lower(trim(field));
    if (value.empty() || value == "replace") {
        *action = Action::Replace;
        return true;
    }
    if (value == "mask") {
        *action = Action::Mask;
        return true;
    }
    if (value == "keep") {
        *action = Action::Keep;
        return true;
    }
    return fail(error, line, "unknown action '" + std::string(field) + "'");
}

bool parse_pinyin(std::string_view field, const std::u32string& canonical,
                  const Lexicon::PinyinDeriver& derive, std::vector<std::string>* out,
                  std::size_t line, std::string* error) {
    const std::string value = ascii_lower(trim(field));
    if (value.empty() || value == "-") {
        if (!derive) {
            return fail(error, line,
                        "pinyin is required (no derivation callback provided)");
        }
        std::vector<std::string> derived = derive(canonical);
        if (derived.size() != canonical.size()) {
            return fail(error, line,
                        "cannot derive pinyin for '" + utf8::encode(canonical) + "'");
        }
        for (const auto& syllable : derived) {
            if (syllable.empty()) {
                return fail(error, line,
                            "cannot derive pinyin for '" + utf8::encode(canonical) + "'");
            }
        }
        *out = std::move(derived);
        return true;
    }
    if (value == "none") {
        out->clear();
        return true;
    }

    std::vector<std::string> syllables;
    std::size_t i = 0;
    while (i < value.size()) {
        while (i < value.size() &&
               (value[i] == ' ' || value[i] == '\t')) {
            ++i;
        }
        const std::size_t start = i;
        while (i < value.size() && value[i] != ' ' && value[i] != '\t') ++i;
        if (start == i) break;
        const std::string token = value.substr(start, i - start);
        for (const char ch : token) {
            if (ch < 'a' || ch > 'z') {
                return fail(error, line,
                            "pinyin syllables must be tone-less ASCII letters: '" +
                                token + "'");
            }
        }
        syllables.push_back(token);
    }
    if (syllables.empty()) {
        return fail(error, line, "invalid pinyin");
    }
    *out = std::move(syllables);
    return true;
}

}  // namespace

void Lexicon::add_entry(LexiconEntry entry) {
    entry.id = static_cast<std::uint32_t>(entries_.size());
    entries_.push_back(std::move(entry));
}

bool Lexicon::parse(std::string_view content, const PinyinDeriver& derive, Lexicon& out,
                    std::string* error) {
    if (error != nullptr) error->clear();
    if (content.size() >= 3 &&
        static_cast<unsigned char>(content[0]) == 0xEF &&
        static_cast<unsigned char>(content[1]) == 0xBB &&
        static_cast<unsigned char>(content[2]) == 0xBF) {
        content.remove_prefix(3);
    }

    Lexicon parsed;
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

        const auto fields = split_tabs(line);
        if (fields.size() > 4) {
            return fail(error, line_number, "too many columns");
        }

        LexiconEntry entry;
        entry.canonical = utf8::decode(trim(fields[0]));
        if (entry.canonical.empty()) {
            return fail(error, line_number, "empty canonical form");
        }

        const std::string_view pinyin_field = fields.size() > 1 ? fields[1] : "-";
        if (!parse_pinyin(pinyin_field, entry.canonical, derive, &entry.pinyin,
                          line_number, error)) {
            return false;
        }

        if (fields.size() > 2) {
            const std::string_view alias_field = trim(fields[2]);
            if (!alias_field.empty() && alias_field != "-") {
                for (const auto alias : split_aliases(alias_field)) {
                    const std::u32string decoded = utf8::decode(trim(alias));
                    if (decoded.empty()) continue;
                    if (std::find(entry.aliases.begin(), entry.aliases.end(), decoded) ==
                        entry.aliases.end()) {
                        entry.aliases.push_back(decoded);
                    }
                }
            }
        }

        if (fields.size() > 3 &&
            !parse_action(fields[3], &entry.action, line_number, error)) {
            return false;
        }

        parsed.add_entry(std::move(entry));
    }

    out = std::move(parsed);
    return true;
}

bool Lexicon::load_file(const std::string& path, const PinyinDeriver& derive,
                        Lexicon& out, std::string* error) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        if (error != nullptr) *error = "cannot open lexicon: " + path;
        return false;
    }
    const std::string content((std::istreambuf_iterator<char>(input)),
                              std::istreambuf_iterator<char>());
    return parse(content, derive, out, error);
}

}  // namespace text_clean
