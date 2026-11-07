#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <string>
#include <string_view>
#include <vector>

namespace text_clean {

enum class Action {
    Replace,  // rewrite the matched span with the canonical form
    Mask,     // mask the matched span character by character
    Keep,     // lock the matched span and leave it byte-for-byte unchanged
};

struct LexiconEntry {
    std::uint32_t id = 0;
    std::u32string canonical;
    std::vector<std::u32string> aliases;
    std::vector<std::string> pinyin;  // tone-less syllables, may be empty
    Action action = Action::Replace;
    // Complete, tone-bearing word pronunciations from the new TSV sources.
    std::vector<std::vector<std::string>> pronunciations;
    std::vector<std::string> sources;
};

// Tab-separated lexicon:
//
//   <canonical><TAB><pinyin|-><TAB><aliases|-><TAB><replace|mask|keep>
//
// Trailing columns may be omitted. "-" or an empty pinyin column means
// "derive from the canonical form" using the supplied callback; "none" means
// "exact matching only". Aliases are comma separated.
class Lexicon {
public:
    using PinyinDeriver = std::function<std::vector<std::string>(const std::u32string&)>;

    static bool load_file(const std::string& path, const PinyinDeriver& derive,
                          Lexicon& out, std::string* error = nullptr);
    static bool parse(std::string_view utf8_content, const PinyinDeriver& derive,
                      Lexicon& out, std::string* error = nullptr);

    void add_entry(LexiconEntry entry);
    const std::vector<LexiconEntry>& entries() const { return entries_; }
    bool empty() const { return entries_.empty(); }
    std::size_t size() const { return entries_.size(); }
    void clear() { entries_.clear(); }

private:
    std::vector<LexiconEntry> entries_;
};

}  // namespace text_clean
