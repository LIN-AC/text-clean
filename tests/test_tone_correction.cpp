#include "test_framework.h"

#include <cmath>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "text_clean/lexicon.h"
#include "text_clean/pinyin_dict.h"
#include "text_clean/text_cleaner.h"
#include "text_clean/utf8.h"
#include "text_clean/word_frequency.h"

namespace {

using text_clean::Action;
using text_clean::CleanResult;
using text_clean::CleanerConfig;
using text_clean::Lexicon;
using text_clean::LexiconEntry;
using text_clean::MatchKind;
using text_clean::PinyinDict;
using text_clean::TextCleaner;
using text_clean::WordFrequency;
using text_clean::utf8::decode;

std::u32string U(const char* text) {
    return decode(text);
}

void add_entry(Lexicon& lexicon, const char* canonical,
               std::vector<std::string> pinyin) {
    LexiconEntry entry;
    entry.canonical = U(canonical);
    entry.pinyin = std::move(pinyin);
    entry.action = Action::Replace;
    lexicon.add_entry(std::move(entry));
}

Lexicon make_lexicon() {
    Lexicon lexicon;
    add_entry(lexicon, "微信", {"wei", "xin"});
    add_entry(lexicon, "支付宝", {"zhi", "fu", "bao"});
    add_entry(lexicon, "字节跳动", {"zi", "jie", "tiao", "dong"});
    add_entry(lexicon, "华为", {"hua", "wei"});
    add_entry(lexicon, "权力", {"quan", "li"});
    add_entry(lexicon, "残骸", {"can", "hai"});
    add_entry(lexicon, "银行", {"yin", "hang"});
    add_entry(lexicon, "他的", {"ta", "de"});
    return lexicon;
}

Lexicon make_boundary_lexicon() {
    Lexicon lexicon;
    add_entry(lexicon, "话盒", {"hua", "he"});
    add_entry(lexicon, "支付宝", {"zhi", "fu", "bao"});
    return lexicon;
}

WordFrequency make_boundary_frequency() {
    WordFrequency frequency;
    frequency.add_word_utf8("话盒", 1000);
    frequency.add_word_utf8("谈话", 5000);
    frequency.add_word_utf8("核实", 5000);
    frequency.add_word_utf8("支付", 5000);
    frequency.add_word_utf8("包", 5000);
    frequency.add_word_utf8("支付宝", 3);
    return frequency;
}

WordFrequency make_frequency() {
    WordFrequency frequency;
    frequency.add_word_utf8("微信", 3);
    frequency.add_word_utf8("支付宝", 3);
    frequency.add_word_utf8("字节跳动", 3);
    frequency.add_word_utf8("华为", 373);
    frequency.add_word_utf8("权力", 14581);
    frequency.add_word_utf8("权利", 7829);
    frequency.add_word_utf8("残骸", 166);
    frequency.add_word_utf8("残害", 193);
    frequency.add_word_utf8("华灯", 100);
    frequency.add_word_utf8("银行", 5000);
    frequency.add_word_utf8("他的", 100000);
    return frequency;
}

PinyinDict make_dict() {
    PinyinDict dict;
    std::string error;
    const std::string path = std::string(TC_DATA_DIR) + "/pinyin_dict.txt";
    CHECK(dict.load_file(path, &error));
    if (!error.empty()) std::cerr << "  " << error << "\n";
    return dict;
}

TextCleaner make_cleaner(const PinyinDict& dict, CleanerConfig config = {}) {
    return TextCleaner(make_lexicon(), dict, config, std::nullopt,
                       make_frequency());
}

void test_tone_distances() {
    const auto dict = make_dict();
    const auto damage = dict.to_toned_syllables(U("残害"));
    const auto remains = dict.to_toned_syllables(U("残骸"));
    CHECK_EQ(PinyinDict::toned_distance(damage, remains, 3), std::size_t{1});

    const auto right = dict.to_toned_syllables(U("权利"));
    const auto power = dict.to_toned_syllables(U("权力"));
    CHECK_EQ(PinyinDict::toned_distance(right, power, 3), std::size_t{0});

    const auto bank = dict.to_toned_syllables(U("银行"));
    const auto bank_typo = dict.to_toned_syllables(U("银航"));
    CHECK_EQ(PinyinDict::toned_distance(bank, bank_typo, 3), std::size_t{0});

    const auto his = dict.to_toned_syllables(U("他的"));
    const auto his_typo = dict.to_toned_syllables(U("他德"));
    CHECK_EQ(PinyinDict::toned_distance(his, his_typo, 3), std::size_t{1});

    // A whole-syllable mismatch is more expensive than a tone mismatch.
    const auto payment = dict.to_toned_syllables(U("支付故"));
    const auto alipay = dict.to_toned_syllables(U("支付宝"));
    CHECK_EQ(PinyinDict::toned_distance(payment, alipay, 3), std::size_t{2});
    const auto wei_xing = dict.to_toned_syllables(U("韦星"));
    const auto wechat = dict.to_toned_syllables(U("微信"));
    CHECK_EQ(PinyinDict::toned_distance(wei_xing, wechat, 3), std::size_t{3});
}

void test_correct_text_is_preserved() {
    const auto dict = make_dict();
    auto cleaner = make_cleaner(dict);

    const CleanResult damage = cleaner.clean(u8"残害");
    CHECK_EQ(damage.text, std::string(u8"残害"));
    CHECK(damage.matches.empty());

    const CleanResult right = cleaner.clean(u8"权利");
    CHECK_EQ(right.text, std::string(u8"权利"));
    CHECK(right.matches.empty());

    const CleanResult lamp = cleaner.clean(u8"华灯");
    CHECK_EQ(lamp.text, std::string(u8"华灯"));
    CHECK(lamp.matches.empty());

    // 支付故 differs from 支付宝 in a whole syllable (D=2), not just a tone.
    const CleanResult payment = cleaner.clean(u8"支付故");
    CHECK_EQ(payment.text, std::string(u8"支付故"));
    CHECK(payment.matches.empty());

    // Exact AC hits are still locked and untouched.
    const CleanResult power = cleaner.clean(u8"权力");
    CHECK_EQ(power.text, std::string(u8"权力"));
    CHECK_EQ(power.matches.size(), std::size_t{1});
    CHECK(power.matches[0].kind == MatchKind::Exact);

    const CleanResult remains = cleaner.clean(u8"残骸");
    CHECK_EQ(remains.text, std::string(u8"残骸"));
    CHECK_EQ(remains.matches.size(), std::size_t{1});
    CHECK(remains.matches[0].kind == MatchKind::Exact);
}

void test_hotwords_are_recalled() {
    const auto dict = make_dict();
    auto cleaner = make_cleaner(dict);

    const CleanResult wechat = cleaner.clean(u8"薇信");
    CHECK_EQ(wechat.text, std::string(u8"微信"));
    CHECK_EQ(wechat.matches.size(), std::size_t{1});
    CHECK(wechat.matches[0].kind == MatchKind::Pinyin);
    CHECK_EQ(wechat.matches[0].distance, std::size_t{0});
    CHECK(wechat.matches[0].score > 0.0);

    const CleanResult alipay = cleaner.clean(u8"支付包");
    CHECK_EQ(alipay.text, std::string(u8"支付宝"));
    CHECK_EQ(alipay.matches.size(), std::size_t{1});
    CHECK(alipay.matches[0].kind == MatchKind::Fuzzy);
    CHECK_EQ(alipay.matches[0].distance, std::size_t{1});
    CHECK(alipay.matches[0].score > 0.0);

    const CleanResult bytedance = cleaner.clean(u8"紫节跳动");
    CHECK_EQ(bytedance.text, std::string(u8"字节跳动"));
    CHECK_EQ(bytedance.matches.size(), std::size_t{1});
    CHECK(bytedance.matches[0].kind == MatchKind::Fuzzy);
    CHECK_EQ(bytedance.matches[0].distance, std::size_t{1});

    const CleanResult huawei = cleaner.clean(u8"华伟");
    CHECK_EQ(huawei.text, std::string(u8"华为"));
    CHECK_EQ(huawei.matches.size(), std::size_t{1});
    CHECK(huawei.matches[0].kind == MatchKind::Fuzzy);
    CHECK_EQ(huawei.matches[0].distance, std::size_t{1});

    // Polyphone: 行 is read hang2 here, matching 航.
    const CleanResult bank = cleaner.clean(u8"银航");
    CHECK_EQ(bank.text, std::string(u8"银行"));
    CHECK_EQ(bank.matches.size(), std::size_t{1});
    CHECK(bank.matches[0].kind == MatchKind::Pinyin);
    CHECK_EQ(bank.matches[0].distance, std::size_t{0});

    // Neutral tone: 的 is de5 while 德 is de2.
    const CleanResult his = cleaner.clean(u8"他德");
    CHECK_EQ(his.text, std::string(u8"他的"));
    CHECK_EQ(his.matches.size(), std::size_t{1});
    CHECK(his.matches[0].kind == MatchKind::Fuzzy);
    CHECK_EQ(his.matches[0].distance, std::size_t{1});
}

void test_word_boundary_windows() {
    const auto dict = make_dict();
    TextCleaner cleaner(make_boundary_lexicon(), dict, {}, std::nullopt,
                        make_boundary_frequency());

    // 谈话/核实 are complete dictionary words. The old sliding window could
    // extract 话核 and rewrite it to 话盒; boundary-aligned windows must not.
    const CleanResult boundary = cleaner.clean(u8"谈话核实");
    CHECK_EQ(boundary.text, std::string(u8"谈话核实"));
    CHECK(boundary.matches.empty());

    // Cross-word matching is still allowed when 支付 and 包 are separate
    // dictionary tokens.
    const CleanResult cross = cleaner.clean(u8"支付包");
    CHECK_EQ(cross.text, std::string(u8"支付宝"));
    CHECK_EQ(cross.matches.size(), std::size_t{1});
    CHECK(cross.matches[0].kind == MatchKind::Fuzzy);
    CHECK_EQ(cross.matches[0].distance, std::size_t{1});
    CHECK(cross.matches[0].score > 0.0);
}

void test_initial_parameter_constraints() {
    CleanerConfig config;
    const double right_power =
        std::log((1.0 + 14581.0) / (1.0 + 7829.0));  // D = 0
    const double huawei_lamp =
        std::log((1.0 + 373.0) / (1.0 + 100.0));  // D = 1
    CHECK(config.distance_penalty >= 0.0);
    CHECK(config.modification_threshold > right_power);
    CHECK(config.distance_penalty >
          huawei_lamp - config.modification_threshold);
}

}  // namespace

int main() {
    test_tone_distances();
    test_correct_text_is_preserved();
    test_hotwords_are_recalled();
    test_word_boundary_windows();
    test_initial_parameter_constraints();
    return test::finish("test_tone_correction");
}