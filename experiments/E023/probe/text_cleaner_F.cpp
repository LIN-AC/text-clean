#include "text_clean/text_cleaner.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <optional>
#include <unordered_map>
#include <unordered_set>
#include <utility>

#include "text_clean/ac_automaton.h"
#include "text_clean/edit_distance.h"
#include "text_clean/pinyin_dict.h"
#include "text_clean/pinyin_index.h"
#include "text_clean/utf8.h"
#include "text_clean/word_maintaining.h"

namespace text_clean {
namespace {
struct Funnel {
    long windows = 0, first_gate = 0, no_candidate = 0, missing_orig = 0, missing_cand = 0,
         action_rej = 0, protected_rej = 0, edge_rej = 0, dist_rej = 0, score_rej = 0,
         accepted = 0, singleton = 0, margin_win = 0, group_veto = 0, keep_win = 0;
    ~Funnel() {
        if (getenv("TC_FUNNEL"))
            fprintf(stderr,
                    "#FUNNEL windows=%ld first_gate=%ld no_candidate=%ld missing_orig=%ld "
                    "missing_cand=%ld action_rej=%ld protected_rej=%ld edge_rej=%ld dist_rej=%ld "
                    "score_rej=%ld accepted=%ld singleton=%ld margin_win=%ld group_veto=%ld "
                    "keep_win=%ld\n",
                    windows, first_gate, no_candidate, missing_orig, missing_cand, action_rej,
                    protected_rej, edge_rej, dist_rej, score_rej, accepted, singleton, margin_win,
                    group_veto, keep_win);
    }
} funnel;
}  // namespace

namespace {

bool numeric_character(char32_t ch) {
    const std::u32string digits=U"0123456789０１２３４５６７８９零〇一二两三四五六七八九十百千万亿";
    return digits.find(ch)!=std::u32string::npos;
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
        double score = 0.0;
        double log_ratio = 0.0;
        std::size_t candidate_frequency = 0;
        std::size_t original_frequency = 0;
        double context_bonus = 0.0;
        std::optional<double> candidate_zipf = std::nullopt, original_zipf = std::nullopt;
    };

    static constexpr std::uint32_t kAcLockedTag =
        static_cast<std::uint32_t>(MatchStatus::LockedByAc);

    struct Window {
        std::size_t begin;
        std::size_t end;
        bool edge = false;
    };

    static constexpr std::size_t kMaxCrossTokens = 4;

    Lexicon lexicon;
    const PinyinDict* dict;
    CleanerConfig config;
    WordFrequency frequencies;
    CharFrequency char_frequency;
    Vocabulary vocabulary;
    WordMaintainer segmenter;
    AcAutomaton ac;
    PinyinInvertedIndex index;
    std::vector<std::uint32_t> pattern_entry;
    std::vector<std::vector<PinyinDict::TonedSyllable>> entry_toned;
    std::vector<std::vector<std::vector<PinyinDict::TonedSyllable>>> word_variants;
    std::size_t max_syllables = 0;
    std::unordered_set<std::string> first_bases;

    Impl(Lexicon source, const PinyinDict& dictionary, CleanerConfig settings,
         std::optional<std::vector<std::u32string>> ac_words,
         WordFrequency frequency_table, Vocabulary recognized,
         CharFrequency character_frequency)
        : lexicon(std::move(source)),
          dict(&dictionary),
          config(settings),
          frequencies(std::move(frequency_table)),
          char_frequency(std::move(character_frequency)),
          vocabulary(std::move(recognized)) {
        std::vector<std::u32string> words;
        if (ac_words.has_value()) {
            words = std::move(*ac_words);
        } else {
            // Legacy Keep entries are protection requests; aliases and targets
            // never gain locking or replacement authority through AC.
            for (const auto& entry : lexicon.entries())
                if(entry.action==Action::Keep) words.push_back(entry.canonical);
        }
        build(words);
        build_segmenter(words);
    }

    void build_segmenter(const std::vector<std::u32string>& ac_words) {
        auto add_if_han = [this](const std::u32string& word) {
            if (word.empty()) return;
            for (const char32_t ch : word) {
                if (!utf8::is_han(ch)) return;
            }
            segmenter.add_word(word);
        };
        for (const auto& word : vocabulary.words()) {
            add_if_han(word);
        }
        // word.txt may have been extended after word_freq.txt was generated.
        for (const auto& word : ac_words) {
            add_if_han(word);
        }
    }

    void build(const std::vector<std::u32string>& words) {
        std::unordered_set<std::u32string> seen;
        for(const auto& word:words) {
            if(word.empty() || !seen.insert(word).second) continue;
            LexiconEntry lock; lock.canonical=word; lock.action=Action::Keep;
            lexicon.add_entry(std::move(lock));
            ac.add_pattern(word,kAcLockedTag);
            pattern_entry.push_back(lexicon.entries().back().id);
        }
        entry_toned.assign(lexicon.entries().size(), {});
        word_variants.resize(lexicon.entries().size());
        for (const auto& entry : lexicon.entries()) {
            if (entry.action != Action::Replace || entry.pinyin.empty()) continue;

            std::vector<PinyinDict::TonedSyllable> toned =
                dict->to_toned_syllables(entry.canonical);
            // The lexicon supplies the pronunciation of this WORD. A character's
            // other bases (including historical/rare readings) are not alternative
            // pronunciations of every word containing it. Reuse this constrained
            // sequence for indexing, distance and the near-sound gate alike.
            toned.resize(entry.pinyin.size());
            for (std::size_t k = 0; k < entry.pinyin.size(); ++k) {
                auto& syllable = toned[k];
                auto& readings = syllable.readings;
                readings.erase(std::remove_if(readings.begin(), readings.end(),
                    [&](const PinyinDict::TonedReading& r) {
                        return r.base != entry.pinyin[k];
                    }), readings.end());
                // Explicit lexicon bases remain authoritative even if the char
                // table lacks that reading. Tone 0 records missing tone evidence.
                if (readings.empty()) readings.push_back({entry.pinyin[k], 0});
                syllable.known = true;
            }
            auto& variants=word_variants[entry.id];
            for(const auto& pronunciation:entry.pronunciations) {
                if(pronunciation.size()!=entry.canonical.size()) continue;
                PinyinDict word;
                // Use distinct synthetic character keys to preserve repeated
                // characters having different readings at different positions.
                std::u32string keys;
                for(std::size_t k=0;k<pronunciation.size();++k) {
                    auto key=static_cast<char32_t>(0x4e00+k); keys+=key;
                    word.add_char(key,{pronunciation[k]});
                }
                variants.push_back(word.to_toned_syllables(keys));
            }
            if(variants.empty()) variants.push_back(toned);
            else {
                toned=variants.front();
                for(std::size_t v=1;v<variants.size();++v)
                    for(std::size_t k=0;k<toned.size();++k)
                        for(const auto& r:variants[v][k].readings)
                            if(std::find(toned[k].readings.begin(),toned[k].readings.end(),r)==toned[k].readings.end()) toned[k].readings.push_back(r);
            }
            entry_toned[entry.id] = std::move(toned);

            PinyinInvertedIndex::Readings bases;
            for (const auto& syllable : entry_toned[entry.id]) {
                bases.emplace_back();
                for (const auto& reading : syllable.readings) bases.back().push_back(reading.base);
            }
            index.add_readings(entry.id, std::move(bases));
            for (const auto& r : entry_toned[entry.id].front().readings) first_bases.insert(r.base);
            max_syllables = std::max(max_syllables, entry.pinyin.size());
        }

        ac.build();
        std::string identity;
        for(const auto& entry:lexicon.entries()) if(entry.action==Action::Replace) {
            identity+=utf8::encode(entry.canonical)+"\n";
            for(const auto& alias:entry.aliases) identity+=utf8::encode(alias)+"\t";
            for(const auto& source:entry.sources) identity+=source+"\t";
            for(const auto& variant:entry.pronunciations) for(const auto& syllable:variant) identity+=syllable+" ";
            identity+="\n";
        }
        index.build_cached(config.index_cache_path,identity);
    }

    bool has_base(char32_t ch, const std::unordered_set<std::string>& bases) const {
        const auto* readings = dict->readings(ch);
        if (readings) for (const auto& base : *readings) if (bases.count(base)) return true;
        return false;
    }
    bool eligible(char32_t ch) const {
        if (!utf8::is_han(ch)) return false;
        const auto* values = dict->readings(ch);
        return values != nullptr && !values->empty();
    }

    std::vector<Selected> select_exact(const std::u32string& text) const {
        std::vector<Selected> selected;
        for (const auto& match : ac.find_all(text)) {
            const auto& entry = lexicon.entries()[pattern_entry[match.pattern]];
            selected.push_back(Selected{match.begin, match.end, entry.id,
                                        MatchKind::Exact, 0,
                                        static_cast<MatchStatus>(match.tag)});
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
        if (a.score != b.score) return a.score > b.score;
        if (a.distance != b.distance) return a.distance < b.distance;
        const std::size_t a_len = a.end - a.begin;
        const std::size_t b_len = b.end - b.begin;
        if (a_len != b_len) return a_len > b_len;
        return a.entry < b.entry;
    }

    std::vector<Window> build_windows(const std::u32string& text,
                                      std::size_t run_begin,
                                      std::size_t run_end) const {
        std::vector<Window> windows;
        if (max_syllables < 2) return windows;
        const auto run = text.substr(run_begin, run_end - run_begin);
        const auto tokens = segmenter.segment(run);
        std::vector<std::size_t> owner(run.size());
        for (std::size_t i = 0; i < tokens.size(); ++i)
            for (auto k = tokens[i].begin; k < tokens[i].end; ++k) owner[k] = i;

        // One symmetric permission check, independent of candidate generation.
        auto permit = [&](std::size_t begin, std::size_t end, bool& edge) {
            const auto li = owner[begin], ri = owner[end - 1];
            if (ri - li >= kMaxCrossTokens) {
                for(auto i=li;i<=ri;++i) if(tokens[i].known) return false;
            }
            const auto& left = tokens[li];
            const auto& right = tokens[ri];
            const bool cut_left = left.known && begin != left.begin;
            const bool cut_right = right.known && end != right.end;
            edge = cut_left || cut_right;
            if (!edge) return true;
            if (cut_left && cut_right) return false;
            if (li == ri) return false;
            // Borrow one outer character only; never cut through two words.
            if (cut_left && begin + 1 != left.end) return false;
            if (cut_right && end != right.begin + 1) return false;
            const auto rb = cut_left ? left.begin : end;
            const auto re = cut_left ? begin : right.end;
            const bool opposite_unknown = cut_left ? !right.known : !left.known;
            if (re - rb == 1 && opposite_unknown) return true;
            if (re - rb >= 2 && vocabulary.contains(run.substr(rb, re - rb))) return true;
            // Residual may join immediate outside context, equally on either side.
            for (std::size_t n = 1; n <= max_syllables; ++n) {
                if (cut_left && rb >= n && vocabulary.contains(run.substr(rb - n, re - rb + n))) return true;
                if (cut_right && re + n <= run.size() && vocabulary.contains(run.substr(rb, re - rb + n))) return true;
            }
            return false;
        };
        // Each (start,length) occurs once: no accumulated duplicates or sorting.
        for (std::size_t begin = 0; begin < run.size(); ++begin) {
            for (std::size_t length = 2; length <= max_syllables && length <= run.size() - begin; ++length) {
                bool edge = false;
                if (!permit(begin, begin + length, edge)) continue;
                if (edge && !has_base(run[begin], first_bases)) continue;
                windows.push_back({run_begin + begin, run_begin + begin + length, edge});
            }
        }
        return windows;
    }

    void scan_run(const std::u32string& text, std::size_t run_begin,
                  std::size_t run_end, const std::vector<bool>& locked,
                  std::vector<Selected>& out, const VideoContext* context) const {
        if (run_end - run_begin < 2) return;
        const std::vector<Window> windows = build_windows(text, run_begin, run_end);
        std::vector<Selected> local;

        for (const Window& window : windows) {
            ++funnel.windows;
            const std::size_t length = window.end - window.begin;
            if (length < config.min_syllables_for_exact_pinyin) continue;
            // Locks constrain changed positions, not the evidence window.


            if (config.require_first_syllable_match && !has_base(text[window.begin], first_bases)) { ++funnel.first_gate; continue; }
            const std::u32string original =
                text.substr(window.begin, length);
            // Dictionary membership is contextual evidence, never an error verdict.
            PinyinInvertedIndex::Readings query;
            for (auto ch : original) query.push_back(*dict->readings(ch));
            const auto candidates = index.find_aligned_candidates(query,
                config.max_candidates_per_window, config.require_first_syllable_match);
            if (candidates.empty()) { ++funnel.no_candidate; continue; }
            const std::size_t original_frequency = frequencies.count(original);
            // An unattested original is not evidence of an error: common
            // character sequences (的+一, 有+信) are missing from the word
            // table by construction. Estimate its chance frequency under
            // character independence so both sides of the ratio use the same
            // unit and a rewrite needs positive evidence (a candidate that is
            // more frequent than chance).
            const double original_estimate =
                original_frequency > 0
                    ? static_cast<double>(original_frequency)
                    : char_frequency.expected_count(original);
            const auto original_zipf = frequencies.zipf(original);
            if(frequencies.is_zipf() && !original_zipf) { ++funnel.missing_orig; continue; } // no fabricated evidence for KEEP
            const auto original_toned = dict->to_toned_syllables(original);

            for (const auto& candidate : candidates) {
                if (index.syllable_count(candidate.id) != length) continue;
                if (candidate.id >= entry_toned.size()) continue;
                const auto& entry = lexicon.entries()[candidate.id];
                if (entry.action != Action::Replace || entry.canonical.size()!=length) { ++funnel.action_rej; continue; }
                if (entry.canonical == original) continue; // KEEP remains the explicit zero-score option.
                bool protected_change=false;
                for(std::size_t k=0;k<length;++k)
                    if(locked[window.begin+k] && original[k]!=entry.canonical[k]) protected_change=true;
                if(protected_change) { ++funnel.protected_rej; continue; }
                if (window.edge) {
                    if(candidate.shared_syllables!=length) { ++funnel.edge_rej; continue; }
                    std::size_t changed=0;
                    for(std::size_t k=0;k<length;++k) changed+=original[k]!=entry.canonical[k];
                    if(changed!=1) { ++funnel.edge_rej; continue; }
                }
                std::size_t distance=config.max_pinyin_distance+1;
                for(const auto& candidate_toned:word_variants[candidate.id]) {
                    if(candidate_toned.size()!=length) continue;
                    bool near=true;
                    for(std::size_t k=0;k<length && near;++k) {
                        bool shared=false;
                        for(const auto& a:original_toned[k].readings)
                            for(const auto& b:candidate_toned[k].readings)
                                shared=shared || levenshtein_bounded(a.base,b.base,1)<=1;
                        near=shared;
                    }
                    if(near) distance=std::min(distance,PinyinDict::aligned_distance(original_toned,candidate_toned,config.max_pinyin_distance));
                }
                if(distance>config.max_pinyin_distance || (window.edge && distance>1)) { ++funnel.dist_rej; continue; }
                if(distance>0 && length<config.min_syllables_for_fuzzy) continue;
                const std::size_t candidate_frequency = frequencies.count(entry.canonical);
                const auto candidate_zipf=frequencies.zipf(entry.canonical);
                if(frequencies.is_zipf() && !candidate_zipf) { ++funnel.missing_cand; continue; }
                const double log_ratio = frequencies.is_zipf()
                    ? 2.302585 * (*candidate_zipf - *original_zipf)
                    : std::log((1.0 + static_cast<double>(candidate_frequency)) /
                             (1.0 + original_estimate));
                const double static_score =
                    log_ratio -
                    config.distance_penalty * static_cast<double>(distance) -
                    config.modification_threshold;
                // Context cannot overturn a static veto on an attested word.
                const double bonus = context && !frequencies.is_zipf() && original_frequency == 0
                    ? context->bonus(entry.canonical) : 0.0;
                const double score = static_score + bonus;
                if (!(score > 0.0)) { ++funnel.score_rej; continue; }
                // Membership is not a lock: static positive evidence can still
                // replace an attested word. Metadata alone must not overturn a
                // static veto on a word supported by the reference vocabulary.
                // Keep all score terms unchanged; this is decision admission.
                if (static_score <= 0.0 && vocabulary.contains(original)) continue;

                Selected selected{window.begin,
                                  window.end,
                                  entry.id,
                                  distance == 0 ? MatchKind::Pinyin
                                                : MatchKind::Fuzzy,
                                  distance,
                                  MatchStatus::None,
                                  score,
                                  log_ratio,
                                  candidate_frequency,
                                  original_frequency, bonus};
                selected.candidate_zipf=candidate_zipf; selected.original_zipf=original_zipf;
                local.push_back(selected);
            }
        }

        std::sort(local.begin(), local.end(), before);
        // Connected overlap components: evidence must clearly favor one action.
        // Ambiguous components retain the entire original span. AC is separate.
        for (std::size_t i = 0; i < local.size();) {
            auto end = local[i].end;
            std::size_t j = i + 1;
            while (j < local.size() && local[j].begin < end) {
                end = std::max(end, local[j].end);
                ++j;
            }
            auto best = i;
            const double keep_score = 0.0; // KEEP is always available, including single-candidate components.
            double runner = keep_score;
            for (auto k = i + 1; k < j; ++k) {
                if (local[k].score > local[best].score) {
                    runner = std::max(runner, local[best].score);
                    best = k;
                } else runner = std::max(runner, local[k].score);
            }
            // Reuse the modification threshold as a required evidence margin.
            if (local[best].score <= keep_score) {
                ++funnel.keep_win;
            } else if (j == i + 1) {
                ++funnel.singleton;
                ++funnel.accepted;
                out.push_back(local[best]);
            } else if (local[best].score - runner > config.modification_threshold) {
                ++funnel.margin_win;
                ++funnel.accepted;
                out.push_back(local[best]);
            } else {
                ++funnel.group_veto;
            }
            i = j;
        }
    }

    std::vector<Selected> select_approximate(const std::u32string& text,
                                             const std::vector<bool>& locked, const VideoContext* context) const {
        std::vector<Selected> selected;
        if (!config.enable_pinyin || index.empty() || max_syllables < 2 ||
            frequencies.empty()) {
            return selected;
        }

        // Only contiguous runs of pinyin-known Han characters are
        // handed to the inverted index / edit distance stages.
        std::size_t i = 0;
        while (i < text.size()) {
            while (i < text.size() && !eligible(text[i])) ++i;
            const std::size_t run_begin = i;
            while (i < text.size() && eligible(text[i])) ++i;
            if (i - run_begin >= 2) scan_run(text, run_begin, i, locked, selected, context);
        }
        return selected;
    }

    CleanResult clean_text(const std::u32string& text, const VideoContext* context = nullptr) const {
        CleanResult result;
        if (text.empty()) return result;

        auto selected=select_exact(text);
        auto locked=build_lock_mask(text.size(),selected);
        for(std::size_t i=0;i<text.size();++i) if(numeric_character(text[i])) locked[i]=true;
        auto approximate=select_approximate(text,locked,context);
        selected.insert(selected.end(),approximate.begin(),approximate.end());
        std::u32string output=text;
        for(const auto& match:selected) {
            const auto& entry=lexicon.entries()[match.entry];
            const auto original=text.substr(match.begin,match.end-match.begin);
            const bool keep=match.status==MatchStatus::LockedByAc;
            const auto replacement=keep?original:entry.canonical;
            if(!keep) {
                if(entry.action!=Action::Replace || replacement.size()!=original.size()) continue;
                bool permitted=true;
                for(std::size_t k=0;k<original.size();++k)
                    if(locked[match.begin+k] && replacement[k]!=original[k]) permitted=false;
                if(!permitted) continue;
                output.replace(match.begin,original.size(),replacement);
            }
            MatchRecord record;
            record.kind=match.kind; record.status=match.status;
            record.begin=match.begin; record.end=match.end; record.entry_id=entry.id;
            record.candidate_zipf=match.candidate_zipf; record.original_zipf=match.original_zipf;
            record.distance=match.distance; record.score=match.score;
            record.log_ratio=match.log_ratio; record.context_bonus=match.context_bonus;
            record.candidate_frequency=match.candidate_frequency; record.original_frequency=match.original_frequency;
            record.matched=original; record.replacement=replacement; record.action=keep?Action::Keep:Action::Replace;
            result.matches.push_back(std::move(record));
        }
        std::stable_sort(result.matches.begin(),result.matches.end(),[](const MatchRecord& a,const MatchRecord& b){return a.begin<b.begin;});
        result.text=utf8::encode(output);
        return result;
    }
};

TextCleaner::TextCleaner(Lexicon lexicon, const PinyinDict& dict, CleanerConfig config,
                         std::optional<std::vector<std::u32string>> ac_words,
                         WordFrequency frequencies, Vocabulary vocabulary,
                         CharFrequency char_frequency)
    : impl_(std::make_unique<Impl>(std::move(lexicon), dict, config,
                                   std::move(ac_words), std::move(frequencies),
                                   std::move(vocabulary), std::move(char_frequency))) {}

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

VideoContext TextCleaner::prepare_context(std::string_view title, std::string_view description,
                                          std::string_view raw_asr) const {
    std::vector<std::u32string> words;
    for (const auto& entry : impl_->lexicon.entries())
        if (entry.action == Action::Replace && !entry.pinyin.empty()) words.push_back(entry.canonical);
    return VideoContext::build(title, description, raw_asr, words);
}
CleanResult TextCleaner::clean(std::string_view text, const VideoContext& context) const {
    return impl_->clean_text(utf8::decode(text), &context);
}
}  // namespace text_clean
