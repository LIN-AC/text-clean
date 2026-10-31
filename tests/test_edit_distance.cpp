#include "test_framework.h"

#include <string>
#include <vector>

#include "text_clean/edit_distance.h"
#include "text_clean/utf8.h"

namespace {

using text_clean::levenshtein;
using text_clean::levenshtein_bounded;

std::vector<std::string> P(std::initializer_list<const char*> syllables) {
    return std::vector<std::string>(syllables.begin(), syllables.end());
}

std::vector<std::string> all_strings(std::size_t max_length) {
    std::vector<std::string> out;
    out.push_back("");
    for (std::size_t length = 1; length <= max_length; ++length) {
        const std::size_t count = std::size_t{1} << length;
        for (std::size_t mask = 0; mask < count; ++mask) {
            std::string value;
            for (std::size_t bit = 0; bit < length; ++bit) {
                value.push_back(((mask >> bit) & 1u) ? 'b' : 'a');
            }
            out.push_back(value);
        }
    }
    return out;
}

void test_character_distance() {
    CHECK_EQ(levenshtein(std::string("kitten"), std::string("sitting")), std::size_t{3});
    CHECK_EQ(levenshtein(std::string("flaw"), std::string("lawn")), std::size_t{2});
    CHECK_EQ(levenshtein(std::string(""), std::string("abc")), std::size_t{3});
    CHECK_EQ(levenshtein(std::string("abc"), std::string("")), std::size_t{3});
    CHECK_EQ(levenshtein(std::string(""), std::string("")), std::size_t{0});
    CHECK_EQ(levenshtein(std::string("same"), std::string("same")), std::size_t{0});
}

void test_syllable_distance() {
    CHECK_EQ(levenshtein(P({"wei", "xin"}), P({"wei", "xing"})), std::size_t{1});
    CHECK_EQ(levenshtein(P({"wei", "xin"}), P({"wei", "xin"})), std::size_t{0});
    CHECK_EQ(levenshtein(P({"wei", "xin"}), P({"zhi", "fu", "bao"})), std::size_t{3});
    CHECK_EQ(levenshtein(P({"zi", "jie", "diao", "dong"}),
                         P({"zi", "jie", "tiao", "dong"})),
             std::size_t{1});
}

void test_chinese_characters() {
    const auto a = text_clean::utf8::decode(u8"微信");
    const auto b = text_clean::utf8::decode(u8"威信");
    const auto c = text_clean::utf8::decode(u8"微信支付");
    CHECK_EQ(levenshtein(a, b), std::size_t{1});
    CHECK_EQ(levenshtein(a, a), std::size_t{0});
    CHECK_EQ(levenshtein(a, c), std::size_t{2});
}

void test_bounded_matches_full() {
    const auto values = all_strings(4);
    for (const auto& a : values) {
        for (const auto& b : values) {
            const std::size_t distance = levenshtein(a, b);
            for (std::size_t limit = 0; limit <= 5; ++limit) {
                const std::size_t expected =
                    distance <= limit ? distance : limit + 1;
                const std::size_t actual = levenshtein_bounded(a, b, limit);
                if (actual != expected) {
                    CHECK_EQ(actual, expected);
                    std::cerr << "  a=\"" << a << "\" b=\"" << b
                              << "\" limit=" << limit << "\n";
                    return;
                }
            }
        }
    }
    CHECK(true);
}

void test_bounded_edge_cases() {
    CHECK_EQ(levenshtein_bounded(std::string("kitten"), std::string("sitting"), 0),
             std::size_t{1});
    CHECK_EQ(levenshtein_bounded(std::string("kitten"), std::string("sitting"), 2),
             std::size_t{3});
    CHECK_EQ(levenshtein_bounded(std::string("kitten"), std::string("sitting"), 3),
             std::size_t{3});
    CHECK_EQ(levenshtein_bounded(std::string("abc"), std::string("xyz"), 100),
             std::size_t{3});
    CHECK_EQ(levenshtein_bounded(P({"wei", "xin"}), P({"wei", "xing"}), 1),
             std::size_t{1});
    CHECK_EQ(levenshtein_bounded(P({"wei", "xin"}), P({"wei", "xing"}), 0),
             std::size_t{1});
}

}  // namespace

int main() {
    test_character_distance();
    test_syllable_distance();
    test_chinese_characters();
    test_bounded_matches_full();
    test_bounded_edge_cases();
    return test::finish("test_edit_distance");
}
