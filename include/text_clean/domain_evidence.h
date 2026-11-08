#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <unordered_map>

#include "text_clean/utf8.h"

namespace text_clean {

// 可选的领域证据（E030 实验）：历史语料 n-gram 词频 + 相邻字共现计数。
//
// 两块数据都来自公开历史文本，不来自本项目真值：
//   words.tsv   : <文本><TAB><zipf>          （1~6 字串，zipf 与 wordfreq 同尺度）
//   pairs.tsv   : <前字><TAB><后字><TAB><次数>
//   unis.tsv    : <字><TAB><次数>
// 邻接证据只回答"在这个邻居后面/前面出现谁更自然"，条件在邻字上，
// 因此待纠错片段自身无法证明自己正确（分母只数邻字，不数片段本身）。
class DomainEvidence {
public:
    bool load(const std::string& dir, std::string* error = nullptr);

    std::optional<double> zipf(const std::u32string& text) const;

    // log P(next | prev)，采用 +0.5 平滑；prev 未见于语料时返回空=弃权。
    std::optional<double> log_prob_next(char32_t prev, char32_t next) const;

    // 跨度 2 的邻接证据：log P(follow | anchor) = log((count(anchor+follow)+0.5)/(count(anchor)+0.5))。
    // anchor 未见于语料（或次数不足 min_anchor_count）时返回空=弃权。
    std::optional<double> log_prob_follow(const std::u32string& anchor, const std::u32string& follow) const;
    bool has_ngrams() const { return !ngrams_.empty(); }
    void set_min_anchor_count(std::uint64_t n) { min_anchor_count_ = n; }

    std::size_t word_rows() const { return zipfs_.size(); }
    std::size_t pair_rows() const { return pairs_.size(); }
    std::size_t ngram_rows() const { return ngrams_.size(); }
    bool empty() const { return zipfs_.empty() && pairs_.empty(); }

private:
    static std::uint64_t pair_key(char32_t a, char32_t b) {
        return (static_cast<std::uint64_t>(a) << 32) | static_cast<std::uint64_t>(b);
    }

    std::unordered_map<std::u32string, double> zipfs_;
    std::unordered_map<std::uint64_t, std::uint64_t> pairs_;
    std::unordered_map<char32_t, std::uint64_t> unis_;
    std::unordered_map<std::u32string, std::uint64_t> ngrams_;   // 1~8 字串 → 次数
    std::uint64_t min_anchor_count_ = 3;
};

}  // namespace text_clean
