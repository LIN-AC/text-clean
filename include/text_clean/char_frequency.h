#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <unordered_map>

namespace text_clean {

// Character unigram frequencies, used as the baseline for spans that are absent
// from the word frequency table.
//
// The word table only lists multi-character words, so a span that is simply a
// common character sequence (的+一, 有+信, 都+是) is "unseen" exactly like a
// genuinely rare sequence. Treating both as frequency 0 makes an unattested
// original indistinguishable from an impossible one; this table supplies the
// chance frequency of an unattested span under character independence:
//
//   expected(span) = total * product(p(ch))
//
// which is the denominator the bigram PMI of the span would use.
//
// Accepted rows: "<word><whitespace><count>[<whitespace><tag>...]" (jieba dict
// layout) or "<word><TAB><count>". Only single Han characters are kept; the
// total is the sum of the kept counts.
class CharFrequency {
public:
    bool load_file(const std::string& path, std::string* error = nullptr);
    bool load_string(std::string_view content, std::string* error = nullptr);

    void add(char32_t ch, std::uint64_t count);
    std::uint64_t count(char32_t ch) const;
    // Additive-smoothing probability, so unseen characters are not zero.
    double probability(char32_t ch) const;
    double expected_count(const std::u32string& span) const;

    double total() const { return total_; }
    std::size_t size() const { return counts_.size(); }
    bool empty() const { return counts_.empty(); }
    void clear() {
        counts_.clear();
        total_ = 0.0;
    }

private:
    std::unordered_map<char32_t, std::uint64_t> counts_;
    double total_ = 0.0;
};

}  // namespace text_clean
