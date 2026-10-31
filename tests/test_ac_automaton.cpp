#include "test_framework.h"

#include <algorithm>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

#include "text_clean/ac_automaton.h"
#include "text_clean/utf8.h"

namespace {

using text_clean::AcAutomaton;

std::u32string U(const char* text) {
    return text_clean::utf8::decode(text);
}

void test_ascii_matches() {
    AcAutomaton ac;
    const auto he = ac.add_pattern(U("he"));
    const auto she = ac.add_pattern(U("she"));
    ac.add_pattern(U("his"));
    const auto hers = ac.add_pattern(U("hers"));
    ac.build();

    const auto matches = ac.find_all(U("ushers"));
    CHECK_EQ(matches.size(), std::size_t{3});
    CHECK(matches[0] == (AcAutomaton::Match{1, 4, she}));
    CHECK(matches[1] == (AcAutomaton::Match{2, 6, hers}));
    CHECK(matches[2] == (AcAutomaton::Match{2, 4, he}));

    const auto longest = ac.find_longest_at_each_end(U("ushers"));
    CHECK_EQ(longest.size(), std::size_t{2});
    CHECK(longest[0] == (AcAutomaton::Match{1, 4, she}));
    CHECK(longest[1] == (AcAutomaton::Match{2, 6, hers}));

    const auto non_overlapping = ac.find_non_overlapping(U("ushers"));
    CHECK_EQ(non_overlapping.size(), std::size_t{1});
    CHECK(non_overlapping[0] == (AcAutomaton::Match{1, 4, she}));
}

void test_suffix_chain() {
    AcAutomaton ac;
    const auto a = ac.add_pattern(U("a"));
    const auto ba = ac.add_pattern(U("ba"));
    const auto cba = ac.add_pattern(U("cba"));
    ac.build();

    const auto matches = ac.find_all(U("cba"));
    CHECK_EQ(matches.size(), std::size_t{3});
    CHECK(matches[0] == (AcAutomaton::Match{0, 3, cba}));
    CHECK(matches[1] == (AcAutomaton::Match{1, 3, ba}));
    CHECK(matches[2] == (AcAutomaton::Match{2, 3, a}));

    const auto longest = ac.find_longest_at_each_end(U("cba"));
    CHECK_EQ(longest.size(), std::size_t{1});
    CHECK(longest[0] == (AcAutomaton::Match{0, 3, cba}));
}

void test_repeating_pattern() {
    AcAutomaton ac;
    const auto aa = ac.add_pattern(U("aa"));
    ac.build();

    const auto matches = ac.find_all(U("aaa"));
    CHECK_EQ(matches.size(), std::size_t{2});
    CHECK(matches[0] == (AcAutomaton::Match{0, 2, aa}));
    CHECK(matches[1] == (AcAutomaton::Match{1, 3, aa}));
}

void test_overlap_selection() {
    AcAutomaton ac;
    const auto abc = ac.add_pattern(U("abc"));
    ac.add_pattern(U("bcd"));
    ac.build();

    CHECK_EQ(ac.find_all(U("abcd")).size(), std::size_t{2});
    const auto selected = ac.find_non_overlapping(U("abcd"));
    CHECK_EQ(selected.size(), std::size_t{1});
    CHECK(selected[0] == (AcAutomaton::Match{0, 3, abc}));
}

void test_chinese() {
    AcAutomaton ac;
    const auto wechat = ac.add_pattern(U("微信"));
    const auto alipay = ac.add_pattern(U("支付宝"));
    ac.build();

    const auto matches = ac.find_all(U("我用微信和支付宝"));
    CHECK_EQ(matches.size(), std::size_t{2});
    CHECK(matches[0] == (AcAutomaton::Match{2, 4, wechat}));
    CHECK(matches[1] == (AcAutomaton::Match{5, 8, alipay}));

    const auto longest = ac.find_longest_at_each_end(U("微信支付宝"));
    CHECK_EQ(longest.size(), std::size_t{2});
    CHECK(longest[0] == (AcAutomaton::Match{0, 2, wechat}));
    CHECK(longest[1] == (AcAutomaton::Match{2, 5, alipay}));
}

void test_duplicate_patterns() {
    AcAutomaton ac;
    const auto first = ac.add_pattern(U("he"));
    const auto second = ac.add_pattern(U("he"));
    ac.build();

    const auto matches = ac.find_all(U("he"));
    CHECK_EQ(matches.size(), std::size_t{2});
    CHECK(matches[0] == (AcAutomaton::Match{0, 2, first}));
    CHECK(matches[1] == (AcAutomaton::Match{0, 2, second}));
    CHECK_EQ(ac.find_non_overlapping(U("he")).size(), std::size_t{1});
}

void test_empty_and_invalid() {
    AcAutomaton ac;
    CHECK_EQ(ac.add_pattern(U("")), AcAutomaton::kInvalidPattern);
    CHECK(ac.empty());
    ac.build();
    CHECK_EQ(ac.node_count(), std::size_t{1});
    CHECK(ac.find_all(U("")).empty());
    CHECK(ac.find_all(U("anything")).empty());
    CHECK(ac.find_longest_at_each_end(U("anything")).empty());
    CHECK(ac.find_non_overlapping(U("anything")).empty());
    CHECK(ac.pattern(123).empty());
}

void test_rebuild_after_add() {
    AcAutomaton ac;
    const auto he = ac.add_pattern(U("he"));
    ac.build();
    CHECK(ac.is_built());
    CHECK_EQ(ac.find_all(U("she")).size(), std::size_t{1});

    const auto she = ac.add_pattern(U("she"));
    CHECK(!ac.is_built());
    ac.build();
    CHECK(ac.is_built());

    const auto matches = ac.find_all(U("she"));
    CHECK_EQ(matches.size(), std::size_t{2});
    CHECK(matches[0] == (AcAutomaton::Match{0, 3, she}));
    CHECK(matches[1] == (AcAutomaton::Match{1, 3, he}));
}

void test_pattern_tags() {
    AcAutomaton ac;
    const auto he = ac.add_pattern(U("he"), 11);
    const auto she = ac.add_pattern(U("she"), 22);
    ac.build();

    const auto all = ac.find_all(U("she"));
    CHECK_EQ(all.size(), std::size_t{2});
    CHECK(all[0] == (AcAutomaton::Match{0, 3, she, 22}));
    CHECK(all[1] == (AcAutomaton::Match{1, 3, he, 11}));

    const auto longest = ac.find_longest_at_each_end(U("she"));
    CHECK_EQ(longest.size(), std::size_t{1});
    CHECK_EQ(longest[0].tag, std::uint32_t{22});

    const auto selected = ac.find_non_overlapping(U("she"));
    CHECK_EQ(selected.size(), std::size_t{1});
    CHECK_EQ(selected[0].tag, std::uint32_t{22});

    ac.add_pattern(U("x"));
    ac.build();
    const auto untagged = ac.find_all(U("x"));
    CHECK_EQ(untagged.size(), std::size_t{1});
    CHECK_EQ(untagged[0].tag, std::uint32_t{0});
}

void test_against_naive_search() {
    std::mt19937 rng(20261031u);
    const char alphabet[] = {'a', 'b', 'c'};

    for (int round = 0; round < 100; ++round) {
        AcAutomaton ac;
        std::vector<std::u32string> patterns;
        const int pattern_count = 1 + static_cast<int>(rng() % 6);

        for (int p = 0; p < pattern_count; ++p) {
            const int length = 1 + static_cast<int>(rng() % 4);
            std::u32string pattern;
            for (int i = 0; i < length; ++i) {
                pattern.push_back(static_cast<char32_t>(alphabet[rng() % 3]));
            }
            patterns.push_back(pattern);
            ac.add_pattern(pattern);
        }
        ac.build();

        std::u32string text;
        const int text_length = static_cast<int>(rng() % 13);
        for (int i = 0; i < text_length; ++i) {
            text.push_back(static_cast<char32_t>(alphabet[rng() % 3]));
        }

        std::vector<AcAutomaton::Match> expected;
        for (std::size_t id = 0; id < patterns.size(); ++id) {
            const auto& pattern = patterns[id];
            if (pattern.size() > text.size()) continue;
            for (std::size_t start = 0; start + pattern.size() <= text.size(); ++start) {
                if (text.compare(start, pattern.size(), pattern) == 0) {
                    expected.push_back(AcAutomaton::Match{
                        start, start + pattern.size(),
                        static_cast<AcAutomaton::PatternId>(id)});
                }
            }
        }
        std::sort(expected.begin(), expected.end(),
                  [](const AcAutomaton::Match& a, const AcAutomaton::Match& b) {
                      if (a.begin != b.begin) return a.begin < b.begin;
                      if (a.end != b.end) return a.end > b.end;
                      return a.pattern < b.pattern;
                  });

        const auto actual = ac.find_all(text);
        const bool same_size = actual.size() == expected.size();
        CHECK(same_size);
        if (!same_size) {
            std::cerr << "  round " << round << ": expected " << expected.size()
                      << " matches, got " << actual.size() << "\n";
            continue;
        }
        for (std::size_t i = 0; i < actual.size(); ++i) {
            if (!(actual[i] == expected[i])) {
                CHECK(false);
                std::cerr << "  round " << round << ": match " << i
                          << " expected " << expected[i].begin << ".." << expected[i].end
                          << " pattern " << expected[i].pattern << ", got "
                          << actual[i].begin << ".." << actual[i].end << " pattern "
                          << actual[i].pattern << "\n";
                break;
            }
        }
    }
}

void test_requires_build() {
    AcAutomaton ac;
    ac.add_pattern(U("x"));
    bool threw = false;
    try {
        ac.find_all(U("x"));
    } catch (const std::logic_error&) {
        threw = true;
    }
    CHECK(threw);
}

void test_pattern_accessor() {
    AcAutomaton ac;
    const auto id = ac.add_pattern(U("微信"));
    CHECK_EQ(std::u32string(ac.pattern(id)), U("微信"));
    CHECK_EQ(ac.pattern_count(), std::size_t{1});
}

}  // namespace

int main() {
    test_ascii_matches();
    test_suffix_chain();
    test_repeating_pattern();
    test_overlap_selection();
    test_chinese();
    test_duplicate_patterns();
    test_empty_and_invalid();
    test_rebuild_after_add();
    test_pattern_tags();
    test_against_naive_search();
    test_requires_build();
    test_pattern_accessor();
    return test::finish("test_ac_automaton");
}
