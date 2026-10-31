#include "test_framework.h"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>

#include "text_clean/utf8.h"
#include "text_clean/word_maintaining.h"

namespace {

using text_clean::WordMaintainer;
using text_clean::utf8::decode;

std::u32string U(const char* text) {
    return decode(text);
}

std::string read_file(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    return std::string((std::istreambuf_iterator<char>(input)),
                       std::istreambuf_iterator<char>());
}

void test_load_string() {
    WordMaintainer table;
    std::string error;
    const std::string content =
        "\xEF\xBB\xBF# comment\r\n"
        "微信\r\n"
        " 支付宝 \r\n"
        "\r\n"
        "微信\r\n"
        "字节跳动\n";
    CHECK(table.load_string(content, &error));
    CHECK(error.empty());
    CHECK_EQ(table.size(), std::size_t{3});
    CHECK_EQ(table.max_word_length(), std::size_t{4});
    CHECK(table.contains_utf8("微信"));
    CHECK(table.contains(U("支付宝")));
    CHECK(table.contains_utf8("字节跳动"));
    CHECK(!table.contains_utf8("抖音"));
    CHECK_EQ(table.words()[0], U("微信"));
    CHECK_EQ(table.words()[1], U("支付宝"));
    CHECK_EQ(table.words()[2], U("字节跳动"));
}

void test_add_word() {
    WordMaintainer table;
    CHECK(table.add_word_utf8(" 微信 "));
    CHECK(!table.add_word(U("微信")));
    CHECK(!table.add_word_utf8(""));
    CHECK(!table.add_word_utf8("   "));
    CHECK_EQ(table.size(), std::size_t{1});
    CHECK_EQ(table.words()[0], U("微信"));
    CHECK_EQ(table.max_word_length(), std::size_t{2});

    table.clear();
    CHECK(table.empty());
    CHECK_EQ(table.max_word_length(), std::size_t{0});
}

void test_segmentation() {
    WordMaintainer table;
    for (const char* word : {"我", "用", "微信", "支付宝", "字节", "字节跳动"}) {
        CHECK(table.add_word_utf8(word));
    }

    const auto text = U("我用微信，字节跳动和支付宝");
    const auto tokens = table.segment(text);
    CHECK_EQ(tokens.size(), std::size_t{7});
    CHECK_EQ(tokens[0].text, U("我"));
    CHECK(tokens[0].known);
    CHECK_EQ(tokens[1].text, U("用"));
    CHECK(tokens[1].known);
    CHECK_EQ(tokens[2].text, U("微信"));
    CHECK(tokens[2].known);
    CHECK_EQ(tokens[3].text, U("，"));
    CHECK(tokens[3].known);
    CHECK_EQ(tokens[4].text, U("字节跳动"));
    CHECK(tokens[4].known);
    CHECK_EQ(tokens[4].begin, std::size_t{5});
    CHECK_EQ(tokens[4].end, std::size_t{9});
    CHECK_EQ(tokens[5].text, U("和"));
    CHECK(!tokens[5].known);
    CHECK_EQ(tokens[6].text, U("支付宝"));
    CHECK(tokens[6].known);

    const auto all_unknowns = table.unknown_spans(text, 1);
    CHECK_EQ(all_unknowns.size(), std::size_t{1});
    CHECK_EQ(all_unknowns[0].text, U("和"));
    CHECK_EQ(all_unknowns[0].begin, std::size_t{9});
    CHECK_EQ(all_unknowns[0].end, std::size_t{10});
    CHECK(table.unknown_spans(text, 2).empty());
}

void test_unknown_spans() {
    WordMaintainer table;
    for (const char* word : {"我", "用", "微信", "支付宝"}) {
        CHECK(table.add_word_utf8(word));
    }

    const auto spans = table.unknown_spans(U("我用微支付"), 1);
    CHECK_EQ(spans.size(), std::size_t{1});
    CHECK_EQ(spans[0].text, U("微支付"));
    CHECK_EQ(spans[0].begin, std::size_t{2});
    CHECK_EQ(spans[0].end, std::size_t{5});

    const auto repeated = table.unknown_spans(U("微支付，微支付"), 2);
    CHECK_EQ(repeated.size(), std::size_t{2});
    CHECK_EQ(repeated[0].text, U("微支付"));
    CHECK_EQ(repeated[0].begin, std::size_t{0});
    CHECK_EQ(repeated[1].text, U("微支付"));
    CHECK_EQ(repeated[1].begin, std::size_t{4});
    CHECK_EQ(repeated[1].end, std::size_t{7});
    CHECK_EQ(table.unknown_spans(U("微支付，微支付"), 1).size(), std::size_t{2});
}

void test_empty_table_and_non_han() {
    WordMaintainer table;
    CHECK(table.unknown_spans(U("微"), 2).empty());
    CHECK_EQ(table.unknown_spans(U("微"), 1).size(), std::size_t{1});
    CHECK_EQ(table.unknown_spans(U("微信A1"), 2).size(), std::size_t{1});
    CHECK_EQ(table.unknown_spans(U("微信A1"), 2)[0].text, U("微信"));

    CHECK(table.add_word_utf8("微信"));
    CHECK(table.unknown_spans(U("微信123abc"), 1).empty());
}

void test_append_words() {
    const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto path = std::filesystem::temp_directory_path() /
                      ("text_clean_words_" + std::to_string(stamp) + ".txt");
    {
        std::ofstream output(path, std::ios::binary);
        output << "微信";  // deliberately no trailing newline
    }

    WordMaintainer table;
    std::string error;
    CHECK(table.load_file(path.string(), &error));
    CHECK_EQ(table.size(), std::size_t{1});

    std::size_t added = 0;
    CHECK(table.append_words_utf8(path.string(),
                                  {"支付宝", "微信", "字节跳动", ""}, &added, &error));
    CHECK_EQ(added, std::size_t{2});
    CHECK_EQ(table.size(), std::size_t{3});
    CHECK_EQ(table.words()[0], U("微信"));
    CHECK_EQ(table.words()[1], U("支付宝"));
    CHECK_EQ(table.words()[2], U("字节跳动"));
    CHECK_EQ(table.max_word_length(), std::size_t{4});

    CHECK_EQ(read_file(path), std::string("微信\n支付宝\n字节跳动\n"));

    WordMaintainer reloaded;
    CHECK(reloaded.load_file(path.string(), &error));
    CHECK_EQ(reloaded.size(), std::size_t{3});
    CHECK(reloaded.contains_utf8("字节跳动"));

    CHECK(table.append_words_utf8(path.string(), {"微信", "支付宝"}, &added, &error));
    CHECK_EQ(added, std::size_t{0});
    CHECK(table.append_words(path.string(), {}, &added, &error));
    CHECK_EQ(added, std::size_t{0});

    std::filesystem::remove(path);
}

void test_append_failure_is_atomic() {
    WordMaintainer table;
    CHECK(table.add_word_utf8("微信"));

    const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto path = std::filesystem::temp_directory_path() /
                      ("text_clean_missing_" + std::to_string(stamp)) / "word.txt";
    std::size_t added = 42;
    std::string error;
    CHECK(!table.append_words_utf8(path.string(), {"支付宝"}, &added, &error));
    CHECK(!error.empty());
    CHECK_EQ(added, std::size_t{0});
    CHECK_EQ(table.size(), std::size_t{1});
    CHECK(!table.contains_utf8("支付宝"));
}

void test_missing_file() {
    WordMaintainer table;
    std::string error;
    CHECK(!table.load_file("definitely-missing-word-file.txt", &error));
    CHECK(error.find("cannot open") != std::string::npos);
}

}  // namespace

int main() {
    test_load_string();
    test_add_word();
    test_segmentation();
    test_unknown_spans();
    test_empty_table_and_non_han();
    test_append_words();
    test_append_failure_is_atomic();
    test_missing_file();
    return test::finish("test_word_maintaining");
}