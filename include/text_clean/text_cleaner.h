#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "text_clean/char_frequency.h"
#include "text_clean/lexicon.h"
#include "text_clean/video_context.h"
#include "text_clean/domain_evidence.h"
#include "text_clean/vocabulary.h"
#include "text_clean/word_frequency.h"

namespace text_clean {

class PinyinDict;

struct CleanerConfig {
    bool enable_pinyin = true;
    std::string index_cache_path; // optional generated cache; never a candidate source

    // Maximum aligned tone-aware substitution distance accepted for a pinyin candidate. Tone-only
    // differences cost 1 and are searched by default; base differences cost 2.
    std::size_t max_pinyin_distance = 2;

    // Entries shorter than this may only match through exact pinyin
    // (distance 0). Two-syllable tone differences are evaluated because the
    // differential score is the final gate.
    std::size_t min_syllables_for_fuzzy = 2;

    // Entries shorter than this are not searched by pinyin at all.
    std::size_t min_syllables_for_exact_pinyin = 2;
    // 单字目标词缺词级证据时，是否允许改用单字频率表作证据（--target-char-freq，默认关）。
    bool target_char_frequency = false;

    // 枚举窗口的最短长度；默认 2。--min-window 1 用来试单字窗口。
    std::size_t min_window_syllables = 2;

    // Fuzzy matches must keep the first syllable base identical. This blocks
    // unrelated words that happen to share a later syllable.
    bool require_first_syllable_match = true;

    // E030 可选领域证据（默认全关，生产行为逐字节不变）。
    bool use_domain_frequency = false;   // 频率来源换成历史语料 n-gram
    double domain_unknown_gap = 1.5;     // 原文在历史语料查不到时记 ZipfC-gap
    // 2026-11-09 起默认开启，且默认单边（上下文只扣分，不许把候选抬过门槛）。
    bool use_context_evidence = true;    // 加入邻接上下文证据（条件在邻字上）
    double context_weight = 1.0;
    // 上下文锚点跨度：1=单个邻字（E030），2=两个邻字（E031，需 ngrams.tsv）。
    std::size_t context_span = 2;
    std::uint64_t context_min_anchor = 3;  // 锚点在语料里少于该次数就弃权，不硬猜
    // 单边上下文：上下文只允许扣分（否决），不允许把候选抬过门槛。
    bool context_one_sided = true;

    // 原文缺词级证据时的三种处理策略（E024 消融；默认 Veto = 现基线行为）。
    enum class MissingEvidence {
        Veto,         // 弃权：原文没有词级 Zipf 证据就不改（当前基线）
        CharEstimate, // M1：用字频独立估计补原文档，ZipfO = ΣZipf(字) - 9*(n-1)
        FixedCap,     // M2：不查字频，直接给原文 ZipfO = ZipfC - missing_cap
    };

    // Differential score:
    //   Zipf mode: ΔS = 2.302585*(ZipfC-ZipfO) - λ*D(O,C) - μ
    //   Legacy counts: ΔS = ln((1+f(C))/(1+f(O))) - λ*D(O,C) - μ
    // A candidate needs ΔS > 0; overlapping alternatives also require a
    // margin > modification_threshold. AC-locked characters are protected.
    // f(C) is the candidate's raw table frequency; f(O) is the original's raw
    // frequency when attested, otherwise its chance frequency under character
    // independence (see CharFrequency). Neither side is floored.
    double distance_penalty = 0.65;        // λ
    double modification_threshold = 0.70;  // μ

    // 2026-11-09 起生产默认 = M1+M2（园长批准）。旧基线用 Veto + cap 0 复现。
    MissingEvidence missing_evidence = MissingEvidence::CharEstimate;
    // E021 保护规则：原文是合法词且静态分≤0 时，不得只靠标题/简介加分获得修改许可。
    // E025 消融可关闭；默认 true = 保持该保护。
    bool enable_admission_guard = true;
    // CharEstimate 模式下 >0 时再把原文档位限制在 ZipfC-missing_cap 以下（M1+M2）；
    // FixedCap 模式下必填 >0。0 表示不设上限。
    double missing_cap = 0.6;

    std::size_t max_candidates_per_window = 64;
    char32_t mask_char = U'*';
};

enum class MatchKind {
    Exact,   // explicit protection found by the Aho-Corasick automaton
    Pinyin,  // same pinyin as a dictionary entry (distance 0)
    Fuzzy,   // close pinyin accepted by the edit distance fallback
};

// AC hits preserve their original characters, which remain usable as context.
enum class MatchStatus : std::uint32_t {
    None = 0,
    LockedByAc = 1u << 0,
};

struct MatchRecord {
    MatchKind kind;
    MatchStatus status = MatchStatus::None;
    std::size_t begin;  // code point offsets in the original text
    std::size_t end;
    std::uint32_t entry_id;
    std::size_t distance;  // aligned tone-aware pinyin distance
    double score = 0.0;    // ΔS for pinyin/fuzzy; 0 for exact AC hits
    double log_ratio = 0.0;
    double context_bonus = 0.0;
    std::optional<double> candidate_zipf = std::nullopt, original_zipf = std::nullopt;
    std::size_t candidate_frequency = 0;
    std::size_t original_frequency = 0;
    std::u32string matched;
    std::u32string replacement;
    Action action;
};

struct CleanResult {
    std::string text;
    std::vector<MatchRecord> matches;
};

// AC only locks original characters. Candidate windows may include locks,
// but every changed position must be unlocked. Only Replace candidates enter
// pronunciation/scoring; legacy Mask actions have no execution permission.
// Vocabulary provides segmentation/reference, not an unconditional veto.
// With no count-frequency table, no replacements are proposed.
class TextCleaner {
public:
    // Vocabulary supplies segmentation/reference only; AC words alone lock.
    TextCleaner(Lexicon lexicon, const PinyinDict& dict, CleanerConfig config = {},
                std::optional<std::vector<std::u32string>> ac_words = std::nullopt,
                WordFrequency frequencies = {}, Vocabulary vocabulary = {},
                CharFrequency char_frequency = {}, DomainEvidence domain = {});
    ~TextCleaner();

    TextCleaner(TextCleaner&&) noexcept;
    TextCleaner& operator=(TextCleaner&&) noexcept;
    TextCleaner(const TextCleaner&) = delete;
    TextCleaner& operator=(const TextCleaner&) = delete;

    const CleanerConfig& config() const;
    CleanResult clean(std::string_view utf8_text) const;
    CleanResult clean(const std::u32string& text) const;
    // Reuse one context across all subtitle cues; destroy it after the video.
    VideoContext prepare_context(std::string_view title, std::string_view description,
                                 std::string_view raw_asr) const;
    CleanResult clean(std::string_view text, const VideoContext& context) const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace text_clean
