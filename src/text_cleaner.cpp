#include "text_clean/text_cleaner.h"

#include <algorithm>
#include <optional>
#include <unordered_map>
#include <unordered_set>
#include <utility>

#include "text_clean/ac_automaton.h"
#include "text_clean/edit_distance.h"
#include "text_clean/pinyin_dict.h"
#include "text_clean/pinyin_index.h"
#include "text_clean/utf8.h"

namespace text_clean {
namespace {

bool is_valid_mask(char32_t ch) {
    return ch != 0 && ch <= 0x10FFFF && !(ch >= 0xD800 && ch <= 0xDFFF);
}

}  // namespace

struct TextCleaner::Impl {
    struct Selected {
        std::size_t begin;
        std::size_t end;
        std::uint32_t entry;
        MatchKind kind;
        std::size_t distance;
        MatchStatus status;
    };

    static constexpr std::uint32_t kAcLockedTag =
        static_cast<std::uint32_t>(MatchStatus::LockedByAc);

    Lexicon lexicon;
    const PinyinDict* dict;
    CleanerConfig config;
    AcAutomaton ac;
    PinyinInvertedIndex index;
    std::vector<std::uint32_t> pattern_entry;
    std::size_t max_syllables = 0;

    Impl(Lexicon source, const PinyinDict& dictionary, CleanerConfig settings,
         std::optional<std::vector<std::u32string>> ac_words)
        : lexicon(std::move(source)), dict(&dictionary), config(settings) {
        std::vector<std::u32string> words;
        if (ac_words.has_value()) {
            words = std::move(*ac_words);
        } else {
            for (const auto& entry : lexicon.entries()) {
                if (!entry.canonical.empty()) words.push_back(entry.canonical);
                for (const auto& alias : entry.aliases) {
                    if (!alias.empty()) words.push_back(alias);
                }
            }
        }
        build(words);
    }

    void build(const std::vector<std::u32string>& words) {
        std::unordered_map<std::u32string, std::uint32_t> owner;
        for (const auto& entry : lexicon.entries()) {
            if (!entry.canonical.empty()) owner.emplace(entry.canonical, entry.id);
        }
        // Canonical forms win over aliases when the same text is registered
        // more than once.
        for (const auto& entry : lexicon.entries()) {
            for (const auto& alias : entry.aliases) {
                if (!alias.empty()) owner.emplace(alias, entry.id);
            }
        }

        std::unordered_set<std::u32string> seen;
        seen.reserve(words.size());
        for (const auto& word : words) {
            if (word.empty() || !seen.insert(word).second) continue;

            std::uint32_t entry_id = 0;
            const auto it = owner.find(word);
            if (it != owner.end()) {
                entry_id = it->second;
            } else {
                LexiconEntry synthetic;
                synthetic.canonical = word;
                synthetic.action = Action::Keep;
                lexicon.add_entry(std::move(synthetic));
                entry_id = lexicon.entries().back().id;
                owner.emplace(word, entry_id);
            }

            ac.add_pattern(word, kAcLockedTag);
            pattern_entry.push_back(entry_id);
        }

        for (const auto& entry : lexicon.entries()) {
            if (entry.pinyin.empty()) continue;
            index.add(entry.id, entry.pinyin);
            max_syllables = std::max(max_syllables, entry.pinyin.size());
        }

        ac.build();
        index.build();
    }

    bool eligible(char32_t ch) const {
        if (!utf8::is_han(ch)) return false;
        const auto* values = dict->readings(ch);
        return values != nullptr && !values->empty();
    }

    std::vector<Selected> select_exact(const std::u32string& text) const {
        std::vector<Selected> selected;
        std::size_t last_end = 0;
        for (const auto& match : ac.find_all(text)) {
            if (match.begin < last_end) continue;
            const auto& entry = lexicon.entries()[pattern_entry[match.pattern]];
            selected.push_back(Selected{match.begin, match.end, entry.id,
                                        MatchKind::Exact, 0,
                                        static_cast<MatchStatus>(match.tag)});
            last_end = match.end;
        }
        return selected;
    }

    static std::vector<bool> build_lock_mask(std::size_t size,
                                             const std::vector<Selected>& exact) {
        std::vector<bool> locked(size, false);
        for (const auto& match : exact) {
            for (std::size_t i = match.begin; i < match.end && i < size; ++i) {
                locked[i] = true;
            }
        }
        return locked;
    }

    static bool overlaps_locked(const std::vector<bool>& locked, std::size_t begin,
                                std::size_t end) {
        for (std::size_t i = begin; i < end && i < locked.size(); ++i) {
            if (locked[i]) return true;
        }
        return false;
    }

    static bool before(const Selected& a, const Selected& b) {
        if (a.begin != b.begin) return a.begin < b.begin;
        if (a.distance != b.distance) return a.distance < b.distance;
        const std::size_t a_len = a.end - a.begin;
        const std::size_t b_len = b.end - b.begin;
        if (a_len != b_len) return a_len > b_len;
        return a.entry < b.entry;
    }

    void scan_run(const std::u32string& text, std::size_t run_begin,
                  std::size_t run_end, const std::vector<bool>& locked,
                  std::vector<Selected>& out) const {
        const std::size_t max_window = std::min(max_syllables, run_end - run_begin);
        if (max_window < 2) return;

        std::vector<Selected> local;
        for (std::size_t start = run_begin; start < run_end; ++start) {
            std::vector<std::string> query;
            query.reserve(max_window);
            const std::size_t limit = std::min(max_window, run_end - start);
            for (std::size_t length = 1; length <= limit; ++length) {
                query.push_back(dict->primary_reading(text[start + length - 1]));
                if (length < config.min_syllables_for_exact_pinyin) continue;
                // Locked spans are authoritative: never build or evaluate a
                // candidate that touches one.
                if (overlaps_locked(locked, start, start + length)) continue;

                const auto candidates =
                    index.find_candidates(query, config.max_candidates_per_window);
                for (const auto& candidate : candidates) {
                    if (index.syllable_count(candidate.id) != length) continue;
                    const auto& entry = lexicon.entries()[candidate.id];
                    const std::size_t distance = levenshtein_bounded(
                        query, entry.pinyin, config.max_pinyin_distance);
                    if (distance > config.max_pinyin_distance) continue;
                    if (distance > 0) {
                        if (length < config.min_syllables_for_fuzzy) continue;
                        if (config.require_first_syllable_match &&
                            query.front() != entry.pinyin.front()) {
                            continue;
                        }
                    }
                    local.push_back(Selected{start, start + length, entry.id,
                                             distance == 0 ? MatchKind::Pinyin
                                                           : MatchKind::Fuzzy,
                                             distance, MatchStatus::None});
                }
            }
        }

        std::sort(local.begin(), local.end(), before);
        std::size_t last_end = 0;
        bool has_selection = false;
        for (const auto& match : local) {
            if (has_selection && match.begin < last_end) continue;
            out.push_back(match);
            last_end = match.end;
            has_selection = true;
        }
    }

    std::vector<Selected> select_approximate(const std::u32string& text,
                                             const std::vector<bool>& locked) const {
        std::vector<Selected> selected;
        if (!config.enable_pinyin || index.empty() || max_syllables < 2) return selected;

        // Only contiguous runs of unlocked, pinyin-known Han characters are
        // handed to the inverted index / edit distance stages.
        std::size_t i = 0;
        while (i < text.size()) {
            while (i < text.size() && (locked[i] || !eligible(text[i]))) ++i;
            const std::size_t run_begin = i;
            while (i < text.size() && !locked[i] && eligible(text[i])) ++i;
            if (i - run_begin >= 2) scan_run(text, run_begin, i, locked, selected);
        }
        return selected;
    }

    CleanResult clean_text(const std::u32string& text) const {
        CleanResult result;
        if (text.empty()) return result;

        std::vector<Selected> selected = select_exact(text);
        const std::vector<bool> locked = build_lock_mask(text.size(), selected);
        const auto approximate = select_approximate(text, locked);
        selected.insert(selected.end(), approximate.begin(), approximate.end());
        std::sort(selected.begin(), selected.end(),
                  [](const Selected& a, const Selected& b) { return a.begin < b.begin; });

        std::u32string output;
        output.reserve(text.size());
        std::size_t cursor = 0;

        for (const auto& match : selected) {
            if (match.begin < cursor) continue;
            // Belt-and-braces enforcement: a later-stage hit may never
            // overlap an AC-locked span.
            if (match.status == MatchStatus::None &&
                overlaps_locked(locked, match.begin, match.end)) {
                continue;
            }
            output.append(text, cursor, match.begin - cursor);

            const auto& entry = lexicon.entries()[match.entry];
            MatchRecord record;
            record.kind = match.kind;
            record.status = match.status;
            record.begin = match.begin;
            record.end = match.end;
            record.entry_id = entry.id;
            record.distance = match.distance;
            record.matched = text.substr(match.begin, match.end - match.begin);
            record.action = entry.action;

            if (entry.action == Action::Mask) {
                const char32_t mask =
                    is_valid_mask(config.mask_char) ? config.mask_char : U'*';
                output.append(match.end - match.begin, mask);
                record.replacement.assign(match.end - match.begin, mask);
            } else if (entry.action == Action::Keep) {
                output += record.matched;
                record.replacement = record.matched;
            } else {
                output += entry.canonical;
                record.replacement = entry.canonical;
            }

            result.matches.push_back(std::move(record));
            cursor = match.end;
        }

        output.append(text, cursor, text.size() - cursor);
        result.text = utf8::encode(output);
        return result;
    }
};

TextCleaner::TextCleaner(Lexicon lexicon, const PinyinDict& dict, CleanerConfig config,
                         std::optional<std::vector<std::u32string>> ac_words)
    : impl_(std::make_unique<Impl>(std::move(lexicon), dict, config,
                                   std::move(ac_words))) {}

TextCleaner::~TextCleaner() = default;
TextCleaner::TextCleaner(TextCleaner&&) noexcept = default;
TextCleaner& TextCleaner::operator=(TextCleaner&&) noexcept = default;

const CleanerConfig& TextCleaner::config() const {
    return impl_->config;
}

CleanResult TextCleaner::clean(std::string_view utf8_text) const {
    return impl_->clean_text(utf8::decode(utf8_text));
}

CleanResult TextCleaner::clean(const std::u32string& text) const {
    return impl_->clean_text(text);
}

}  // namespace text_clean
