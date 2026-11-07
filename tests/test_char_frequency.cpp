#include "test_framework.h"

#include <cstdint>
#include <string>

#include "text_clean/char_frequency.h"
#include "text_clean/utf8.h"

namespace {

using text_clean::CharFrequency;
using text_clean::utf8::decode;

std::u32string U(const char* text) {
    return decode(text);
}

void test_keeps_single_han_only() {
    CharFrequency freq;
    std::string error;
    // jieba layout: word, count, tag. Only single Han characters are kept, and
    // later rows accumulate into the same character.
    const std::string content =
        "\xEF\xBB\xBF# comment\r\n"
        "的\t300\tuj\r\n"
        "一\t200\tm\r\n"
        "的确\t50\td\r\n"
        "A\t999\tnz\r\n"
        "的\t100\tuj\r\n"
        "\r\n";
    CHECK(freq.load_string(content, &error));
    CHECK(error.empty());
    CHECK_EQ(freq.size(), std::size_t{2});
    CHECK_EQ(freq.count(U'的'), std::uint64_t{400});
    CHECK_EQ(freq.count(U'一'), std::uint64_t{200});
    CHECK_EQ(freq.count(U'确'), std::uint64_t{0});
    CHECK_EQ(freq.total(), 600.0);
}

void test_space_and_tab_separators() {
    CharFrequency freq;
    std::string error;
    CHECK(freq.load_string("的 500\n是\t700\n", &error));
    CHECK_EQ(freq.count(U'的'), std::uint64_t{500});
    CHECK_EQ(freq.count(U'是'), std::uint64_t{700});
}

void test_expected_count_is_independence_baseline() {
    CharFrequency freq;
    std::string error;
    CHECK(freq.load_string("的\t300\n一\t200\n颈\t2\n锥\t1\n", &error));
    const double common = freq.expected_count(U("的一"));
    const double rare = freq.expected_count(U("颈锥"));
    // 的一 is an ordinary character sequence; 颈锥 is nearly impossible.
    CHECK(common > 100.0);
    CHECK(rare < 0.05);
    CHECK(common > rare * 1000);
    // Longer spans are less likely under the same model.
    CHECK(freq.expected_count(U("的一的")) < common);
}

void test_empty_and_invalid_inputs() {
    CharFrequency freq;
    std::string error;
    CHECK(!freq.load_string("", &error));
    CHECK(!error.empty());
    CHECK(freq.empty());
    CHECK_EQ(freq.expected_count(U("的一")), 0.0);

    // An empty table never changes the score: expected_count stays 0.
    CHECK(!freq.load_string("的确\t10\n", &error));
    CHECK(freq.empty());
}

void test_smoothing_keeps_unseen_character_positive() {
    CharFrequency freq;
    std::string error;
    CHECK(freq.load_string("的\t300\n一\t200\n", &error));
    CHECK(freq.probability(U'龘') > 0.0);
    CHECK(freq.expected_count(U("的龘")) > 0.0);
}

void test_missing_file() {
    CharFrequency freq;
    std::string error;
    CHECK(!freq.load_file("definitely-missing-char-frequency.txt", &error));
    CHECK(error.find("cannot open") != std::string::npos);
}

}  // namespace

int main() {
    test_keeps_single_han_only();
    test_space_and_tab_separators();
    test_expected_count_is_independence_baseline();
    test_empty_and_invalid_inputs();
    test_smoothing_keeps_unseen_character_positive();
    test_missing_file();
    return test::finish("test_char_frequency");
}
