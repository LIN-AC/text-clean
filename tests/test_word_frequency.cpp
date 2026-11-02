#include "test_framework.h"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <string>

#include "text_clean/utf8.h"
#include "text_clean/word_frequency.h"

namespace {

using text_clean::WordFrequency;
using text_clean::utf8::decode;

std::u32string U(const char* text) {
    return decode(text);
}

void test_load_string() {
    WordFrequency freq;
    std::string error;
    const std::string content =
        "\xEF\xBB\xBF# comment\r\n"
        "微信\t100\r\n"
        "支付宝\t50\r\n"
        "微信\t80\r\n"
        "Xiaomi Book\t20\r\n"
        "\r\n";
    CHECK(freq.load_string(content, &error));
    CHECK(error.empty());
    CHECK_EQ(freq.size(), std::size_t{3});
    CHECK_EQ(freq.count_utf8("微信"), std::uint64_t{100});
    CHECK_EQ(freq.count(U("支付宝")), std::uint64_t{50});
    CHECK_EQ(freq.count_utf8("Xiaomi Book"), std::uint64_t{20});
    CHECK_EQ(freq.count_utf8("抖音"), std::uint64_t{0});
}

void test_add_word() {
    WordFrequency freq;
    CHECK(freq.add_word_utf8("微信", 10));
    CHECK(freq.add_word(U("微信"), 20));
    CHECK(freq.add_word_utf8("微信", 5));
    CHECK_EQ(freq.count_utf8("微信"), std::uint64_t{20});
    CHECK(!freq.add_word_utf8("", 1));
    CHECK(!freq.add_word_utf8("   ", 1));
    CHECK_EQ(freq.size(), std::size_t{1});
    freq.clear();
    CHECK(freq.empty());
}

void test_separator_and_zero() {
    WordFrequency freq;
    std::string error;
    CHECK(freq.load_string("微信 10\n支付宝\t0\n", &error));
    CHECK_EQ(freq.count_utf8("微信"), std::uint64_t{10});
    CHECK_EQ(freq.count_utf8("支付宝"), std::uint64_t{0});
    CHECK_EQ(freq.size(), std::size_t{2});
}

void test_errors_are_atomic() {
    WordFrequency freq;
    std::string error;
    CHECK(freq.load_string("微信\t100\n", &error));
    CHECK_EQ(freq.size(), std::size_t{1});

    const std::vector<std::string> bad = {
        "微信\n",
        "微信\tabc\n",
        "\t10\n",
        "微信\t\n",
        "微信\t-1\n",
    };
    for (const auto& content : bad) {
        error.clear();
        CHECK(!freq.load_string(content, &error));
        CHECK(!error.empty());
        CHECK_EQ(freq.size(), std::size_t{1});
        CHECK_EQ(freq.count_utf8("微信"), std::uint64_t{100});
    }
}

void test_load_file() {
    const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto path = std::filesystem::temp_directory_path() /
                      ("text_clean_freq_" + std::to_string(stamp) + ".txt");
    {
        std::ofstream output(path, std::ios::binary);
        output << "华为\t373\n字节跳动\t3\n";
    }

    WordFrequency freq;
    std::string error;
    CHECK(freq.load_file(path.string(), &error));
    CHECK_EQ(freq.size(), std::size_t{2});
    CHECK_EQ(freq.count_utf8("华为"), std::uint64_t{373});
    std::filesystem::remove(path);

    error.clear();
    CHECK(!freq.load_file("definitely-missing-frequency-file.txt", &error));
    CHECK(error.find("cannot open") != std::string::npos);
}

}  // namespace

int main() {
    test_load_string();
    test_add_word();
    test_separator_and_zero();
    test_errors_are_atomic();
    test_load_file();
    return test::finish("test_word_frequency");
}