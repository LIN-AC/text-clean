#include "test_framework.h"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#include "text_clean/pinyin_dict.h"
#include "text_clean/utf8.h"

namespace {

using text_clean::PinyinDict;
using text_clean::utf8::decode;

void test_normalization() {
    CHECK_EQ(PinyinDict::normalize_reading("wēi"), std::string("wei"));
    CHECK_EQ(PinyinDict::normalize_reading("lǜ"), std::string("lv"));
    CHECK_EQ(PinyinDict::normalize_reading("nǚ"), std::string("nv"));
    CHECK_EQ(PinyinDict::normalize_reading("zhī4"), std::string("zhi"));
    CHECK_EQ(PinyinDict::normalize_reading(" Wēi "), std::string("wei"));
    CHECK_EQ(PinyinDict::normalize_reading("nu:"), std::string("nv"));
    CHECK_EQ(PinyinDict::normalize_reading("wEI"), std::string("wei"));
    CHECK_EQ(PinyinDict::normalize_reading("ê"), std::string("e"));
    CHECK_EQ(PinyinDict::normalize_reading(""), std::string(""));
    CHECK_EQ(PinyinDict::normalize_reading("123"), std::string(""));
}

void test_add_and_analyze() {
    PinyinDict dict;
    CHECK(dict.add_char(U'微', {"wēi"}));
    CHECK(dict.add_char(U'信', {"xin", "shēn"}));
    CHECK(!dict.add_char(U'?', {"", "123"}));
    CHECK_EQ(dict.size(), std::size_t{2});

    const auto tokens = dict.analyze(decode(u8"微信A1，"));
    CHECK_EQ(tokens.size(), std::size_t{5});
    CHECK_EQ(tokens[0].ch, char32_t{U'微'});
    CHECK_EQ(tokens[0].syllable, std::string("wei"));
    CHECK(tokens[0].is_han);
    CHECK(tokens[0].known);
    CHECK_EQ(tokens[1].syllable, std::string("xin"));
    CHECK(!tokens[2].is_han);
    CHECK(!tokens[2].known);
    CHECK(tokens[2].syllable.empty());
    CHECK_EQ(tokens[3].ch, char32_t{U'1'});
    CHECK_EQ(tokens[4].ch, char32_t{0xFF0C});

    CHECK_EQ(dict.primary_reading(U'信'), std::string("xin"));
    CHECK_EQ(dict.primary_reading(U'龙'), std::string(""));
    CHECK(dict.readings(U'龙') == nullptr);

    const auto syllables = dict.to_pinyin(decode(u8"微信A"));
    CHECK_EQ(syllables,
             std::vector<std::string>({std::string("wei"), std::string("xin"),
                                       std::string("")}));
}

void test_load_string() {
    PinyinDict dict;
    const std::string content =
        "\xEF\xBB\xBF# generated\r\n"
        "4e00\twēi\r\n"
        "U+4FE1\txin,shen\r\n"
        "4fe1\tshēn\r\n"
        "957F\tzhang,chang\r\n";
    std::string error;
    CHECK(dict.load_string(content, &error));
    CHECK(error.empty());
    CHECK_EQ(dict.size(), std::size_t{3});
    CHECK_EQ(dict.primary_reading(U'信'), std::string("xin"));
    CHECK_EQ(dict.readings(U'信')->size(), std::size_t{2});
    CHECK_EQ(dict.primary_reading(U'长'), std::string("zhang"));
    CHECK_EQ(dict.readings(U'长')->back(), std::string("chang"));
}

void test_load_errors_are_atomic() {
    PinyinDict dict;
    std::string error;
    CHECK(dict.load_string("4e00\twei\n", &error));
    CHECK_EQ(dict.size(), std::size_t{1});

    const std::vector<std::string> bad_inputs = {
        "4e00\n",
        "4e00\t\n",
        "ZZZZ\twei\n",
        "110000\twei\n",
        "D800\twei\n",
        "4e00\twei xin\n",
        "4e00\t,\n",
    };
    for (const auto& input : bad_inputs) {
        error.clear();
        CHECK(!dict.load_string(input, &error));
        CHECK(!error.empty());
        CHECK_EQ(dict.size(), std::size_t{1});
        CHECK_EQ(dict.primary_reading(U'一'), std::string("wei"));
    }
}

void test_load_file() {
    const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto path = std::filesystem::temp_directory_path() /
                      ("text_clean_pinyin_" + std::to_string(stamp) + ".txt");
    {
        std::ofstream out(path, std::ios::binary);
        out << "4f60\tni\n4eec\tmen\n";
    }

    PinyinDict dict;
    std::string error;
    CHECK(dict.load_file(path.string(), &error));
    CHECK_EQ(dict.size(), std::size_t{2});
    CHECK_EQ(dict.primary_reading(U'们'), std::string("men"));
    std::filesystem::remove(path);

    error.clear();
    CHECK(!dict.load_file("definitely-missing-pinyin-file.txt", &error));
    CHECK(error.find("cannot open") != std::string::npos);
}

void test_real_data() {
    PinyinDict dict;
    std::string error;
    const std::string path = std::string(TC_DATA_DIR) + "/pinyin_dict.txt";
    CHECK(dict.load_file(path, &error));
    if (!error.empty()) std::cerr << "  " << error << "\n";
    CHECK(dict.size() > 40000);

    const auto tokens = dict.analyze(decode(u8"微信支付宝"));
    CHECK_EQ(tokens.size(), std::size_t{5});
    CHECK_EQ(tokens[0].syllable, std::string("wei"));
    CHECK_EQ(tokens[1].syllable, std::string("xin"));
    CHECK_EQ(tokens[2].syllable, std::string("zhi"));
    CHECK_EQ(tokens[3].syllable, std::string("fu"));
    CHECK_EQ(tokens[4].syllable, std::string("bao"));

    CHECK_EQ(dict.primary_reading(U'长'), std::string("zhang"));
    CHECK_EQ(dict.primary_reading(U'绿'), std::string("lv"));
    CHECK_EQ(dict.primary_reading(U'女'), std::string("nv"));
}

}  // namespace

int main() {
    test_normalization();
    test_add_and_analyze();
    test_load_string();
    test_load_errors_are_atomic();
    test_load_file();
    test_real_data();
    return test::finish("test_pinyin_dict");
}
