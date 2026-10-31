#include "text_clean/ac_automaton.h"

#include <algorithm>
#include <stdexcept>

namespace text_clean {

AcAutomaton::PatternId AcAutomaton::add_pattern(std::u32string_view pattern,
                                                std::uint32_t tag) {
    if (pattern.empty()) return kInvalidPattern;
    const auto id = static_cast<PatternId>(patterns_.size());
    patterns_.emplace_back(pattern);
    tags_.push_back(tag);
    built_ = false;
    return id;
}

void AcAutomaton::build() {
    nodes_.clear();
    nodes_.emplace_back();  // root = 0

    for (PatternId id = 0; id < patterns_.size(); ++id) {
        std::uint32_t node = 0;
        for (char32_t ch : patterns_[id]) {
            const auto it = nodes_[node].next.find(ch);
            if (it != nodes_[node].next.end()) {
                node = it->second;
                continue;
            }
            const auto next = static_cast<std::uint32_t>(nodes_.size());
            nodes_.emplace_back();
            nodes_[node].next.emplace(ch, next);
            node = next;
        }
        nodes_[node].outputs.push_back(id);
    }

    // Breadth-first construction of failure and output links.
    std::vector<std::uint32_t> queue;
    queue.reserve(nodes_.size());
    for (const auto& entry : nodes_[0].next) {
        nodes_[entry.second].fail = 0;
        nodes_[entry.second].output_link = 0;
        queue.push_back(entry.second);
    }

    for (std::size_t head = 0; head < queue.size(); ++head) {
        const std::uint32_t current = queue[head];
        for (const auto& entry : nodes_[current].next) {
            const char32_t ch = entry.first;
            const std::uint32_t child = entry.second;

            std::uint32_t fail = nodes_[current].fail;
            while (fail != 0 && nodes_[fail].next.find(ch) == nodes_[fail].next.end()) {
                fail = nodes_[fail].fail;
            }
            const auto it = nodes_[fail].next.find(ch);
            if (it != nodes_[fail].next.end() && it->second != child) {
                fail = it->second;
            } else {
                fail = 0;
            }

            nodes_[child].fail = fail;
            nodes_[child].output_link =
                nodes_[fail].outputs.empty() ? nodes_[fail].output_link : fail;
            queue.push_back(child);
        }
    }

    built_ = true;
}

void AcAutomaton::require_built() const {
    if (!built_) {
        throw std::logic_error("AcAutomaton::build() must be called before searching");
    }
}

std::u32string_view AcAutomaton::pattern(PatternId id) const {
    if (id >= patterns_.size()) return {};
    return patterns_[id];
}

std::uint32_t AcAutomaton::step(std::uint32_t state, char32_t ch) const {
    while (state != 0 && nodes_[state].next.find(ch) == nodes_[state].next.end()) {
        state = nodes_[state].fail;
    }
    const auto it = nodes_[state].next.find(ch);
    return it == nodes_[state].next.end() ? 0 : it->second;
}

std::vector<AcAutomaton::Match> AcAutomaton::find_all(std::u32string_view text) const {
    require_built();
    std::vector<Match> matches;

    std::uint32_t state = 0;
    for (std::size_t i = 0; i < text.size(); ++i) {
        state = step(state, text[i]);
        const std::size_t end = i + 1;

        for (const PatternId id : nodes_[state].outputs) {
            matches.push_back(Match{end - patterns_[id].size(), end, id, tags_[id]});
        }
        for (std::uint32_t link = nodes_[state].output_link; link != 0;
             link = nodes_[link].output_link) {
            for (const PatternId id : nodes_[link].outputs) {
                matches.push_back(Match{end - patterns_[id].size(), end, id, tags_[id]});
            }
        }
    }

    std::sort(matches.begin(), matches.end(), [](const Match& a, const Match& b) {
        if (a.begin != b.begin) return a.begin < b.begin;
        if (a.end != b.end) return a.end > b.end;
        return a.pattern < b.pattern;
    });
    return matches;
}

std::vector<AcAutomaton::Match> AcAutomaton::find_longest_at_each_end(
    std::u32string_view text) const {
    require_built();
    std::vector<Match> result;

    std::uint32_t state = 0;
    for (std::size_t i = 0; i < text.size(); ++i) {
        state = step(state, text[i]);
        const std::size_t end = i + 1;

        bool found = false;
        Match best{0, 0, kInvalidPattern};
        auto consider = [&](std::uint32_t node) {
            for (const PatternId id : nodes_[node].outputs) {
                const Match candidate{end - patterns_[id].size(), end, id, tags_[id]};
                const std::size_t candidate_len = candidate.end - candidate.begin;
                const std::size_t best_len = best.end - best.begin;
                if (!found || candidate_len > best_len ||
                    (candidate_len == best_len && candidate.pattern < best.pattern)) {
                    best = candidate;
                    found = true;
                }
            }
        };

        consider(state);
        for (std::uint32_t link = nodes_[state].output_link; link != 0;
             link = nodes_[link].output_link) {
            consider(link);
        }
        if (found) result.push_back(best);
    }
    return result;
}

std::vector<AcAutomaton::Match> AcAutomaton::find_non_overlapping(
    std::u32string_view text) const {
    std::vector<Match> selected;
    std::size_t last_end = 0;
    for (const Match& match : find_all(text)) {
        if (match.begin < last_end) continue;
        selected.push_back(match);
        last_end = match.end;
    }
    return selected;
}

}  // namespace text_clean
