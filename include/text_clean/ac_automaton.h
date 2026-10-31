#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace text_clean {

// Aho-Corasick automaton over Unicode code points.
//
// Patterns are added first, then build() must be called once. Query methods
// throw std::logic_error when called before build(). Adding a pattern after
// build() invalidates the automaton until build() is called again.
//
// Every pattern can carry a caller-defined uint32 tag. The tag is returned
// together with each match, so callers can attach a status code (for example
// "this span is authoritative / locked") to the hit.
class AcAutomaton {
public:
    using PatternId = std::uint32_t;
    static constexpr PatternId kInvalidPattern = static_cast<PatternId>(-1);

    struct Match {
        std::size_t begin;  // inclusive code point offset
        std::size_t end;    // exclusive code point offset
        PatternId pattern;
        std::uint32_t tag = 0;

        friend bool operator==(const Match& a, const Match& b) {
            return a.begin == b.begin && a.end == b.end && a.pattern == b.pattern &&
                   a.tag == b.tag;
        }
    };

    PatternId add_pattern(std::u32string_view pattern, std::uint32_t tag = 0);
    void build();

    bool empty() const { return patterns_.empty(); }
    bool is_built() const { return built_; }
    std::size_t pattern_count() const { return patterns_.size(); }
    std::size_t node_count() const { return nodes_.size(); }
    std::u32string_view pattern(PatternId id) const;

    // Every occurrence of every pattern, including overlaps and suffix
    // matches. Sorted by begin asc, end desc, pattern id asc.
    std::vector<Match> find_all(std::u32string_view text) const;

    // For each end position, the longest pattern ending there (ties: lowest
    // pattern id). Sorted by end asc.
    std::vector<Match> find_longest_at_each_end(std::u32string_view text) const;

    // Greedy earliest-longest selection of non-overlapping matches.
    std::vector<Match> find_non_overlapping(std::u32string_view text) const;

private:
    struct Node {
        std::unordered_map<char32_t, std::uint32_t> next;
        std::vector<PatternId> outputs;
        std::uint32_t fail = 0;
        std::uint32_t output_link = 0;  // nearest fail ancestor with outputs
    };

    void require_built() const;
    std::uint32_t step(std::uint32_t state, char32_t ch) const;

    std::vector<std::u32string> patterns_;
    std::vector<std::uint32_t> tags_;
    std::vector<Node> nodes_;
    bool built_ = false;
};

}  // namespace text_clean
