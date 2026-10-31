#include "test_framework.h"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#include "text_clean/lexicon.h"
#include "text_clean/utf8.h"

namespace {

using text_clean::Action;
using text_clean::Lexicon;
using text_clean::LexiconEntry;
using text_clean::utf8::decode;

std::u32string U(const char* text) {
    return decode(text);
}

Lexicon::PinyinDeriver make_deriver() {
    return [](const std::u32string& word) -> std::vector<std::string> {
        if (word == U("敏感词")) return {"min", "gan", "ci"};
        if (word == U("抖音")) return {"dou", "yin"};
        if (word == U("字节跳动")) return {"zi", "jie", "tiao", "dong"};
        return std::vector<std::string>(word.size(), std::string());
    };
}

void test_parse_full() {
    const std::string content =
        "# ASR lexicon\r\n"
        "微信\twei xin\t威信,薇信\treplace\r\n"
        "敏感词\t-\t\tmask\r\n"
        "字节跳动\tzi jie tiao dong\t\treplace\r\n"
        "支付宝\tzhi fu bao\t支富宝，知付宝\n"
        "抖音\n";

    Lexicon lexicon;
    std::string error;
    CHECK(Lexicon::parse(content, make_deriver(), lexicon, &error));
    CHECK(error.empty());
    CHECK_EQ(lexicon.size(), std::size_t{5});

    const auto& entries = lexicon.entries();
    CHECK_EQ(entries[0].id, std::uint32_t{0});
    CHECK_EQ(entries[0].canonical, U("微信"));
    CHECK_EQ(entries[0].pinyin,
             std::vector<std::string>({std::string("wei"), std::string("xin")}));
    CHECK_EQ(entries[0].aliases.size(), std::size_t{2});
    CHECK_EQ(entries[0].aliases[0], U("威信"));
    CHECK_EQ(entries[0].aliases[1], U("薇信"));
    CHECK(entries[0].action == Action::Replace);

    CHECK_EQ(entries[1].canonical, U("敏感词"));
    CHECK_EQ(entries[1].pinyin.size(), std::size_t{3});
    CHECK(entries[1].aliases.empty());
    CHECK(entries[1].action == Action::Mask);

    CHECK_EQ(entries[2].pinyin.size(), std::size_t{4});
    CHECK(entries[2].aliases.empty());
    CHECK(entries[2].action == Action::Replace);

    CHECK_EQ(entries[3].aliases.size(), std::size_t{2});
    CHECK_EQ(entries[3].aliases[0], U("支富宝"));
    CHECK_EQ(entries[3].aliases[1], U("知付宝"));

    CHECK_EQ(entries[4].pinyin,
             std::vector<std::string>({std::string("dou"), std::string("yin")}));
}

void test_none_pinyin_and_actions() {
    const std::string content =
        "iPhone\tnone\t\t\n"
        "银行卡\t-\t\tMASK\n";
    const auto derive = [](const std::u32string& word) -> std::vector<std::string> {
        if (word == U("银行卡")) return {"yin", "hang", "ka"};
        return {};
    };

    Lexicon lexicon;
    std::string error;
    CHECK(Lexicon::parse(content, derive, lexicon, &error));
    CHECK_EQ(lexicon.size(), std::size_t{2});
    CHECK(lexicon.entries()[0].pinyin.empty());
    CHECK(lexicon.entries()[0].action == Action::Replace);
    CHECK_EQ(lexicon.entries()[1].pinyin.size(), std::size_t{3});
    CHECK(lexicon.entries()[1].action == Action::Mask);
}

void test_keep_action() {
    Lexicon lexicon;
    std::string error;
    CHECK(Lexicon::parse("抖音\tdou yin\t\tkeep\n", nullptr, lexicon, &error));
    CHECK_EQ(lexicon.size(), std::size_t{1});
    CHECK(lexicon.entries()[0].action == Action::Keep);

    CHECK(Lexicon::parse("微信\twei xin\t\tKEEP\n", nullptr, lexicon, &error));
    CHECK_EQ(lexicon.size(), std::size_t{1});
    CHECK(lexicon.entries()[0].action == Action::Keep);
}

void test_parse_errors() {
    struct Case {
        std::string line;
        const char* needle;
    };
    const Case cases[] = {
        {"微信\t-\t\t\n", "derive"},
        {"微信\t-\t\t\treplace\n", "too many columns"},
        {"\twei xin\n", "empty canonical"},
        {"微信\twei2 xin\n", "tone-less"},
        {"微信\twēi xin\n", "tone-less"},
        {"微信\twei xin\t\tdelete\n", "unknown action"},
        {"微信\twei xin\t\tmask\textra\n", "too many columns"},
    };

    for (const auto& item : cases) {
        Lexicon lexicon;
        std::string error;
        const bool ok = Lexicon::parse(item.line, make_deriver(), lexicon, &error);
        CHECK(!ok);
        CHECK(error.find(item.needle) != std::string::npos);
        CHECK(lexicon.empty());
    }

    Lexicon lexicon;
    std::string error;
    CHECK(!Lexicon::parse("微信\t-\n", nullptr, lexicon, &error));
    CHECK(error.find("derivation callback") != std::string::npos);
}

void test_derivation_validation() {
    const auto short_derive = [](const std::u32string&) {
        return std::vector<std::string>{"wei"};
    };
    const auto empty_syllable = [](const std::u32string&) {
        return std::vector<std::string>{"wei", ""};
    };

    Lexicon lexicon;
    std::string error;
    CHECK(!Lexicon::parse("微信\t-\n", short_derive, lexicon, &error));
    CHECK(error.find("cannot derive") != std::string::npos);

    error.clear();
    CHECK(!Lexicon::parse("微信\t-\n", empty_syllable, lexicon, &error));
    CHECK(error.find("cannot derive") != std::string::npos);
}

void test_parse_is_atomic() {
    Lexicon lexicon;
    std::string error;
    CHECK(Lexicon::parse("微信\twei xin\n", make_deriver(), lexicon, &error));
    CHECK_EQ(lexicon.size(), std::size_t{1});

    CHECK(!Lexicon::parse("坏行\t-\n", make_deriver(), lexicon, &error));
    CHECK_EQ(lexicon.size(), std::size_t{1});
    CHECK_EQ(lexicon.entries()[0].canonical, U("微信"));
}

void test_empty_content() {
    Lexicon lexicon;
    std::string error;
    CHECK(Lexicon::parse("", make_deriver(), lexicon, &error));
    CHECK(lexicon.empty());
    CHECK(Lexicon::parse("# only a comment\n\n", make_deriver(), lexicon, &error));
    CHECK(lexicon.empty());
}

void test_add_entry_ids() {
    Lexicon lexicon;
    LexiconEntry first;
    first.canonical = U("微信");
    LexiconEntry second;
    second.canonical = U("支付宝");
    lexicon.add_entry(std::move(first));
    lexicon.add_entry(std::move(second));
    CHECK_EQ(lexicon.entries()[0].id, std::uint32_t{0});
    CHECK_EQ(lexicon.entries()[1].id, std::uint32_t{1});
    lexicon.clear();
    CHECK(lexicon.empty());
}

void test_load_file() {
    const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto path = std::filesystem::temp_directory_path() /
                      ("text_clean_lexicon_" + std::to_string(stamp) + ".txt");
    {
        std::ofstream out(path, std::ios::binary);
        out << "\xEF\xBB\xBF微信\twei xin\t薇信\n";
    }

    Lexicon lexicon;
    std::string error;
    CHECK(Lexicon::load_file(path.string(), make_deriver(), lexicon, &error));
    CHECK_EQ(lexicon.size(), std::size_t{1});
    CHECK_EQ(lexicon.entries()[0].aliases.size(), std::size_t{1});
    std::filesystem::remove(path);

    error.clear();
    CHECK(!Lexicon::load_file("definitely-missing-lexicon.txt", make_deriver(), lexicon,
                              &error));
    CHECK(error.find("cannot open") != std::string::npos);
}

}  // namespace

int main() {
    test_parse_full();
    test_none_pinyin_and_actions();
    test_keep_action();
    test_parse_errors();
    test_derivation_validation();
    test_parse_is_atomic();
    test_empty_content();
    test_add_entry_ids();
    test_load_file();
    return test::finish("test_lexicon");
}
