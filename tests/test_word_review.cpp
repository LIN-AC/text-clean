#include "test_framework.h"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <sstream>
#include <string>
#include <vector>

#include "text_clean/text_split.h"
#include "text_clean/utf8.h"
#include "text_clean/word_maintaining.h"
#include "text_clean/word_review.h"

namespace {

using text_clean::Section;
using text_clean::SectionKind;
using text_clean::UnknownWord;
using text_clean::WordMaintainer;
using text_clean::WordReview;
using text_clean::utf8::decode;
using text_clean::utf8::encode;

std::string U8(const char* text) {
    return std::string(text);
}

std::vector<Section> make_sections(const std::string& title, const std::string& intro,
                                   const std::string& body) {
    return {
        Section{SectionKind::Title, "标题", title},
        Section{SectionKind::Intro, "简介", intro},
        Section{SectionKind::Body, "正文", body},
    };
}

const UnknownWord* find_unknown(const std::vector<UnknownWord>& words,
                                const std::u32string& text) {
    for (const auto& word : words) {
        if (word.text == text) return &word;
    }
    return nullptr;
}

std::string read_file(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    return std::string((std::istreambuf_iterator<char>(input)),
                       std::istreambuf_iterator<char>());
}

std::filesystem::path temp_path(const char* prefix) {
    const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
    return std::filesystem::temp_directory_path() /
           (std::string(prefix) + std::to_string(stamp) + ".txt");
}

void test_collect_only_title_and_intro() {
    WordMaintainer table;
    CHECK(table.add_word_utf8("微信"));
    CHECK(table.add_word_utf8("今天"));

    const auto sections = make_sections(U8(u8"微信支付"), U8(u8"今天支付"),
                                        U8(u8"微信字节调洞"));
    const auto unknown = WordReview::collect(table, sections, 2);
    CHECK_EQ(unknown.size(), std::size_t{1});

    const UnknownWord* pay = find_unknown(unknown, decode(u8"支付"));
    CHECK(pay != nullptr);
    if (pay != nullptr) {
        CHECK_EQ(pay->count, std::size_t{2});
        CHECK_EQ(pay->sections.size(), std::size_t{2});
        CHECK_EQ(pay->sections[0], std::string("标题"));
        CHECK_EQ(pay->sections[1], std::string("简介"));
    }

    // The body contains a large unknown word, but must not be tokenized.
    CHECK(find_unknown(unknown, decode(u8"字节调洞")) == nullptr);
}

void test_collect_min_length_and_other_section() {
    WordMaintainer table;
    CHECK(table.add_word_utf8("微信"));

    const auto sections = make_sections(U8(u8"微信单"), "", "");
    CHECK_EQ(WordReview::collect(table, sections, 1).size(), std::size_t{1});
    CHECK(WordReview::collect(table, sections, 2).empty());

    const std::vector<Section> other = {
        Section{SectionKind::Other, "附录", U8(u8"字节调洞")},
    };
    CHECK(WordReview::collect(table, other, 1).empty());
}

void test_run_adds_words_and_resolves() {
    const auto path = temp_path("text_clean_review_");
    {
        std::ofstream output(path, std::ios::binary);
        output << "微信\n";
    }

    WordMaintainer table;
    std::string error;
    CHECK(table.load_file(path.string(), &error));

    const auto sections = make_sections(U8(u8"微信支付"), U8(u8"支付说明"),
                                        U8(u8"字节调洞"));
    const auto initial = WordReview::collect(table, sections, 2);
    CHECK_EQ(initial.size(), std::size_t{2});

    std::istringstream input("支付\n说明\n\n");
    std::ostringstream output;
    CHECK(WordReview::run(table, sections, path.string(), 2, input, output, &error));
    CHECK(error.empty());
    CHECK_EQ(table.size(), std::size_t{3});
    CHECK(table.contains_utf8("支付"));
    CHECK(table.contains_utf8("说明"));
    CHECK_EQ(read_file(path), std::string("微信\n支付\n说明\n"));
    CHECK(output.str().find("标题/简介词表已覆盖") != std::string::npos);

    // The body-only unknown word was never offered for review.
    CHECK(output.str().find("字节调洞") == std::string::npos);

    std::filesystem::remove(path);
}

void test_run_ignores_body_only_document() {
    const auto path = temp_path("text_clean_review_body_");
    {
        std::ofstream output(path, std::ios::binary);
        output << "微信\n";
    }

    WordMaintainer table;
    std::string error;
    CHECK(table.load_file(path.string(), &error));

    const auto sections = make_sections("", "", U8(u8"字节调洞"));
    std::istringstream input;
    std::ostringstream output;
    CHECK(WordReview::run(table, sections, path.string(), 2, input, output, &error));
    CHECK(error.empty());
    CHECK(output.str().find("无需维护") != std::string::npos);
    CHECK(output.str().find("字节调洞") == std::string::npos);
    CHECK_EQ(read_file(path), std::string("微信\n"));
    CHECK_EQ(table.size(), std::size_t{1});

    std::filesystem::remove(path);
}

void test_run_empty_input_keeps_file() {
    const auto path = temp_path("text_clean_review_stop_");
    {
        std::ofstream output(path, std::ios::binary);
        output << "微信\n";
    }

    WordMaintainer table;
    std::string error;
    CHECK(table.load_file(path.string(), &error));

    const auto sections = make_sections(U8(u8"微信支付"), "", "");
    std::istringstream input;
    std::ostringstream output;
    CHECK(WordReview::run(table, sections, path.string(), 2, input, output, &error));
    CHECK(error.empty());
    CHECK(output.str().find("未新增词语") != std::string::npos);
    CHECK_EQ(read_file(path), std::string("微信\n"));
    CHECK_EQ(table.size(), std::size_t{1});

    std::filesystem::remove(path);
}

void test_run_append_failure() {
    WordMaintainer table;
    CHECK(table.add_word_utf8("微信"));

    const auto sections = make_sections(U8(u8"微信支付"), "", "");
    const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto path = std::filesystem::temp_directory_path() /
                      ("text_clean_review_missing_" + std::to_string(stamp)) /
                      "word.txt";

    std::istringstream input("支付\n\n");
    std::ostringstream output;
    std::string error;
    CHECK(!WordReview::run(table, sections, path.string(), 2, input, output, &error));
    CHECK(!error.empty());
    CHECK_EQ(table.size(), std::size_t{1});
    CHECK(!table.contains_utf8("支付"));
}

}  // namespace

int main() {
    test_collect_only_title_and_intro();
    test_collect_min_length_and_other_section();
    test_run_adds_words_and_resolves();
    test_run_ignores_body_only_document();
    test_run_empty_input_keeps_file();
    test_run_append_failure();
    return test::finish("test_word_review");
}