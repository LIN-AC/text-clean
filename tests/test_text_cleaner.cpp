#include "test_framework.h"

#include <string>
#include <utility>
#include <vector>

#include "text_clean/lexicon.h"
#include "text_clean/pinyin_dict.h"
#include "text_clean/text_cleaner.h"
#include "text_clean/utf8.h"

namespace {

using text_clean::Action;
using text_clean::CleanResult;
using text_clean::CleanerConfig;
using text_clean::Lexicon;
using text_clean::LexiconEntry;
using text_clean::MatchKind;
using text_clean::MatchStatus;
using text_clean::PinyinDict;
using text_clean::TextCleaner;
using text_clean::utf8::decode;

std::u32string U(const char* text) {
    return decode(text);
}

void add_readings(PinyinDict& dict, char32_t ch,
                  std::initializer_list<const char*> readings) {
    dict.add_char(ch, std::vector<std::string>(readings.begin(), readings.end()));
}

PinyinDict make_dict() {
    PinyinDict dict;
    add_readings(dict, U'微', {"wei"});
    add_readings(dict, U'信', {"xin"});
    add_readings(dict, U'威', {"wei"});
    add_readings(dict, U'薇', {"wei"});
    add_readings(dict, U'韦', {"wei"});
    add_readings(dict, U'星', {"xing"});
    add_readings(dict, U'支', {"zhi"});
    add_readings(dict, U'付', {"fu"});
    add_readings(dict, U'宝', {"bao"});
    add_readings(dict, U'知', {"zhi"});
    add_readings(dict, U'福', {"fu"});
    add_readings(dict, U'报', {"bao"});
    add_readings(dict, U'字', {"zi"});
    add_readings(dict, U'节', {"jie"});
    add_readings(dict, U'跳', {"tiao"});
    add_readings(dict, U'调', {"diao"});
    add_readings(dict, U'洞', {"dong"});
    add_readings(dict, U'动', {"dong"});
    add_readings(dict, U'紫', {"zi"});
    add_readings(dict, U'典', {"dian"});
    add_readings(dict, U'掉', {"diao"});
    add_readings(dict, U'我', {"wo"});
    add_readings(dict, U'用', {"yong"});
    add_readings(dict, U'加', {"jia"});
    add_readings(dict, U'联', {"lian"});
    add_readings(dict, U'系', {"xi"});
    add_readings(dict, U'你', {"ni"});
    add_readings(dict, U'和', {"he"});
    add_readings(dict, U'敏', {"min"});
    add_readings(dict, U'感', {"gan"});
    add_readings(dict, U'词', {"ci"});
    add_readings(dict, U'华', {"hua"});
    add_readings(dict, U'为', {"wei"});
    return dict;
}

void add_entry(Lexicon& lexicon, const char* canonical,
               std::vector<std::string> pinyin,
               std::initializer_list<const char*> aliases, Action action) {
    LexiconEntry entry;
    entry.canonical = U(canonical);
    entry.pinyin = std::move(pinyin);
    for (const char* alias : aliases) entry.aliases.push_back(U(alias));
    entry.action = action;
    lexicon.add_entry(std::move(entry));
}

Lexicon make_lexicon() {
    Lexicon lexicon;
    add_entry(lexicon, "微信", {"wei", "xin"}, {"威信"}, Action::Replace);
    add_entry(lexicon, "支付宝", {"zhi", "fu", "bao"}, {"支富宝"}, Action::Replace);
    add_entry(lexicon, "字节跳动", {"zi", "jie", "tiao", "dong"}, {},
              Action::Replace);
    add_entry(lexicon, "敏感词", {"min", "gan", "ci"}, {}, Action::Mask);
    add_entry(lexicon, "华为", {"hua", "wei"}, {}, Action::Replace);
    add_entry(lexicon, "薇信宝", {"wei", "xin", "bao"}, {}, Action::Replace);
    return lexicon;
}

TextCleaner make_cleaner(const PinyinDict& dict, CleanerConfig config = {}) {
    return TextCleaner(make_lexicon(), dict, config);
}

TextCleaner make_cleaner_with_words(const PinyinDict& dict,
                                    std::vector<std::u32string> words,
                                    CleanerConfig config = {}) {
    return TextCleaner(make_lexicon(), dict, config, std::move(words));
}

void test_exact_canonical() {
    const auto dict = make_dict();
    auto cleaner = make_cleaner(dict);

    const CleanResult result = cleaner.clean(u8"我用微信联系你");
    CHECK_EQ(result.text, std::string(u8"我用微信联系你"));
    CHECK_EQ(result.matches.size(), std::size_t{1});
    CHECK(result.matches[0].kind == MatchKind::Exact);
    CHECK_EQ(result.matches[0].begin, std::size_t{2});
    CHECK_EQ(result.matches[0].end, std::size_t{4});
    CHECK_EQ(result.matches[0].entry_id, std::uint32_t{0});
    CHECK_EQ(result.matches[0].distance, std::size_t{0});
    CHECK(result.matches[0].status == MatchStatus::LockedByAc);
    CHECK_EQ(result.matches[0].matched, U("微信"));
    CHECK_EQ(result.matches[0].replacement, U("微信"));
}

void test_exact_alias() {
    const auto dict = make_dict();
    auto cleaner = make_cleaner(dict);

    const CleanResult result = cleaner.clean(u8"用威信加我");
    CHECK_EQ(result.text, std::string(u8"用微信加我"));
    CHECK_EQ(result.matches.size(), std::size_t{1});
    CHECK(result.matches[0].kind == MatchKind::Exact);
    CHECK_EQ(result.matches[0].matched, U("威信"));
    CHECK_EQ(result.matches[0].replacement, U("微信"));
    CHECK_EQ(result.matches[0].begin, std::size_t{1});
    CHECK_EQ(result.matches[0].end, std::size_t{3});
    CHECK(result.matches[0].status == MatchStatus::LockedByAc);
}

void test_pinyin_homophone() {
    const auto dict = make_dict();
    auto cleaner = make_cleaner(dict);

    const CleanResult result = cleaner.clean(u8"用薇信加我");
    CHECK_EQ(result.text, std::string(u8"用微信加我"));
    CHECK_EQ(result.matches.size(), std::size_t{1});
    CHECK(result.matches[0].kind == MatchKind::Pinyin);
    CHECK_EQ(result.matches[0].distance, std::size_t{0});
    CHECK(result.matches[0].status == MatchStatus::None);
    CHECK_EQ(result.matches[0].matched, U("薇信"));
    CHECK_EQ(result.matches[0].replacement, U("微信"));
}

void test_short_fuzzy_is_rejected() {
    const auto dict = make_dict();
    auto cleaner = make_cleaner(dict);

    const CleanResult result = cleaner.clean(u8"用韦星加我");
    CHECK_EQ(result.text, std::string(u8"用韦星加我"));
    CHECK(result.matches.empty());
}

void test_long_fuzzy_match() {
    const auto dict = make_dict();
    auto cleaner = make_cleaner(dict);

    const CleanResult result = cleaner.clean(u8"字节调洞");
    CHECK_EQ(result.text, std::string(u8"字节跳动"));
    CHECK_EQ(result.matches.size(), std::size_t{1});
    CHECK(result.matches[0].kind == MatchKind::Fuzzy);
    CHECK_EQ(result.matches[0].distance, std::size_t{1});
    CHECK(result.matches[0].status == MatchStatus::None);
    CHECK_EQ(result.matches[0].matched, U("字节调洞"));
    CHECK_EQ(result.matches[0].replacement, U("字节跳动"));
}

void test_long_exact_pinyin() {
    const auto dict = make_dict();
    auto cleaner = make_cleaner(dict);

    const CleanResult result = cleaner.clean(u8"紫节跳动");
    CHECK_EQ(result.text, std::string(u8"字节跳动"));
    CHECK_EQ(result.matches.size(), std::size_t{1});
    CHECK(result.matches[0].kind == MatchKind::Pinyin);
    CHECK_EQ(result.matches[0].distance, std::size_t{0});
    CHECK(result.matches[0].status == MatchStatus::None);
}

void test_fuzzy_limited_by_distance() {
    const auto dict = make_dict();
    auto cleaner = make_cleaner(dict);

    const CleanResult result = cleaner.clean(u8"字典掉洞");
    CHECK_EQ(result.text, std::string(u8"字典掉洞"));
    CHECK(result.matches.empty());
}

void test_fuzzy_threshold_is_configurable() {
    const auto dict = make_dict();
    CleanerConfig config;
    config.min_syllables_for_fuzzy = 2;
    auto cleaner = make_cleaner(dict, config);

    const CleanResult result = cleaner.clean(u8"用韦星加我");
    CHECK_EQ(result.text, std::string(u8"用微信加我"));
    CHECK_EQ(result.matches.size(), std::size_t{1});
    CHECK(result.matches[0].kind == MatchKind::Fuzzy);
    CHECK_EQ(result.matches[0].matched, U("韦星"));
}

void test_fuzzy_requires_first_syllable() {
    const auto dict = make_dict();
    CleanerConfig config;
    config.min_syllables_for_fuzzy = 2;
    auto cleaner = make_cleaner(dict, config);

    // "用韦" (yong wei) is distance 1 from "华为" (hua wei) but starts with a
    // different syllable, so it must not replace the unrelated prefix.
    const CleanResult result = cleaner.clean(u8"用韦星加我");
    CHECK_EQ(result.text, std::string(u8"用微信加我"));
    CHECK_EQ(result.matches.size(), std::size_t{1});
    CHECK_EQ(result.matches[0].matched, U("韦星"));
    CHECK_EQ(result.matches[0].replacement, U("微信"));
}

void test_zero_distance_config() {
    const auto dict = make_dict();
    CleanerConfig config;
    config.max_pinyin_distance = 0;
    auto cleaner = make_cleaner(dict, config);

    const CleanResult fuzzy = cleaner.clean(u8"字节调洞");
    CHECK_EQ(fuzzy.text, std::string(u8"字节调洞"));
    CHECK(fuzzy.matches.empty());

    const CleanResult exact = cleaner.clean(u8"紫节跳动");
    CHECK_EQ(exact.text, std::string(u8"字节跳动"));
    CHECK_EQ(exact.matches.size(), std::size_t{1});
    CHECK(exact.matches[0].kind == MatchKind::Pinyin);
}

void test_pinyin_disabled() {
    const auto dict = make_dict();
    CleanerConfig config;
    config.enable_pinyin = false;
    auto cleaner = make_cleaner(dict, config);

    const CleanResult result = cleaner.clean(u8"用薇信加我");
    CHECK_EQ(result.text, std::string(u8"用薇信加我"));
    CHECK(result.matches.empty());

    const CleanResult alias = cleaner.clean(u8"用威信加我");
    CHECK_EQ(alias.text, std::string(u8"用微信加我"));
    CHECK_EQ(alias.matches.size(), std::size_t{1});
}

void test_mask_exact() {
    const auto dict = make_dict();
    auto cleaner = make_cleaner(dict);

    const CleanResult result = cleaner.clean(u8"这是敏感词测试");
    CHECK_EQ(result.text, std::string(u8"这是***测试"));
    CHECK_EQ(result.matches.size(), std::size_t{1});
    CHECK(result.matches[0].action == Action::Mask);
    CHECK_EQ(result.matches[0].matched, U("敏感词"));
    CHECK_EQ(result.matches[0].replacement, U("***"));
    CHECK_EQ(result.matches[0].begin, std::size_t{2});
    CHECK_EQ(result.matches[0].end, std::size_t{5});
    CHECK(result.matches[0].status == MatchStatus::LockedByAc);
}

void test_custom_mask_char() {
    const auto dict = make_dict();
    CleanerConfig config;
    config.mask_char = U'#';
    auto cleaner = make_cleaner(dict, config);

    const CleanResult result = cleaner.clean(u8"敏感词");
    CHECK_EQ(result.text, std::string("###"));
    CHECK_EQ(result.matches.size(), std::size_t{1});
    CHECK_EQ(result.matches[0].replacement, U("###"));
}

void test_multiple_matches() {
    const auto dict = make_dict();
    auto cleaner = make_cleaner(dict);

    const CleanResult result = cleaner.clean(u8"我用微信和支付宝");
    CHECK_EQ(result.text, std::string(u8"我用微信和支付宝"));
    CHECK_EQ(result.matches.size(), std::size_t{2});
    CHECK_EQ(result.matches[0].entry_id, std::uint32_t{0});
    CHECK_EQ(result.matches[0].begin, std::size_t{2});
    CHECK_EQ(result.matches[0].end, std::size_t{4});
    CHECK_EQ(result.matches[1].entry_id, std::uint32_t{1});
    CHECK_EQ(result.matches[1].begin, std::size_t{5});
    CHECK_EQ(result.matches[1].end, std::size_t{8});
    CHECK(result.matches[0].status == MatchStatus::LockedByAc);
    CHECK(result.matches[1].status == MatchStatus::LockedByAc);
}

void test_exact_not_double_matched() {
    const auto dict = make_dict();
    auto cleaner = make_cleaner(dict);

    const CleanResult result = cleaner.clean(u8"微信");
    CHECK_EQ(result.matches.size(), std::size_t{1});
    CHECK(result.matches[0].kind == MatchKind::Exact);
    CHECK(result.matches[0].status == MatchStatus::LockedByAc);
}

void test_external_ac_word_list() {
    const auto dict = make_dict();

    // The automaton is built only from the supplied list. 微信 is absent, so
    // it is found later by the pinyin stage instead of being locked by AC.
    auto cleaner = make_cleaner_with_words(dict, {U("支付宝")});
    const CleanResult pinyin = cleaner.clean(u8"微信");
    CHECK_EQ(pinyin.text, std::string(u8"微信"));
    CHECK_EQ(pinyin.matches.size(), std::size_t{1});
    CHECK(pinyin.matches[0].kind == MatchKind::Pinyin);
    CHECK(pinyin.matches[0].status == MatchStatus::None);

    // An alias present in the external list keeps the lexicon action.
    auto alias_cleaner = make_cleaner_with_words(dict, {U("威信")});
    const CleanResult alias = alias_cleaner.clean(u8"威信");
    CHECK_EQ(alias.text, std::string(u8"微信"));
    CHECK_EQ(alias.matches.size(), std::size_t{1});
    CHECK(alias.matches[0].kind == MatchKind::Exact);
    CHECK(alias.matches[0].status == MatchStatus::LockedByAc);
    CHECK(alias.matches[0].action == Action::Replace);

    // A word that is only in the external list gets a synthetic Keep entry:
    // it is locked, but the text is left byte-for-byte unchanged.
    auto keep_cleaner = make_cleaner_with_words(dict, {U("抖音")});
    const CleanResult keep = keep_cleaner.clean(u8"抖音");
    CHECK_EQ(keep.text, std::string(u8"抖音"));
    CHECK_EQ(keep.matches.size(), std::size_t{1});
    CHECK(keep.matches[0].kind == MatchKind::Exact);
    CHECK(keep.matches[0].status == MatchStatus::LockedByAc);
    CHECK(keep.matches[0].action == Action::Keep);
    CHECK_EQ(keep.matches[0].matched, U("抖音"));
    CHECK_EQ(keep.matches[0].replacement, U("抖音"));
}

void test_ac_lock_blocks_later_stages() {
    const auto dict = make_dict();
    auto cleaner = make_cleaner(dict);

    // "威信" is an exact alias and gets locked. Without the lock, the
    // three-character window "威信宝" would match "薇信宝" by pinyin and
    // rewrite the locked alias. The pinyin stage must never see it.
    const CleanResult result = cleaner.clean(u8"用威信宝");
    CHECK_EQ(result.text, std::string(u8"用微信宝"));
    CHECK_EQ(result.matches.size(), std::size_t{1});
    CHECK(result.matches[0].kind == MatchKind::Exact);
    CHECK(result.matches[0].status == MatchStatus::LockedByAc);
    CHECK_EQ(result.matches[0].begin, std::size_t{1});
    CHECK_EQ(result.matches[0].end, std::size_t{3});
    CHECK_EQ(result.matches[0].matched, U("威信"));
    CHECK_EQ(result.matches[0].entry_id, std::uint32_t{0});

    // Without the locked alias, a homophone variant is still corrected by the
    // pinyin + edit distance stages.
    const CleanResult unlocked = cleaner.clean(u8"用薇星宝");
    CHECK_EQ(unlocked.text, std::string(u8"用薇信宝"));
    CHECK_EQ(unlocked.matches.size(), std::size_t{1});
    CHECK(unlocked.matches[0].kind == MatchKind::Fuzzy);
    CHECK(unlocked.matches[0].status == MatchStatus::None);
    CHECK_EQ(unlocked.matches[0].begin, std::size_t{1});
    CHECK_EQ(unlocked.matches[0].end, std::size_t{4});
    CHECK_EQ(unlocked.matches[0].replacement, U("薇信宝"));
}

void test_no_match() {
    const auto dict = make_dict();
    auto cleaner = make_cleaner(dict);

    const CleanResult result = cleaner.clean("hello world");
    CHECK_EQ(result.text, std::string("hello world"));
    CHECK(result.matches.empty());

    const CleanResult empty = cleaner.clean("");
    CHECK(empty.text.empty());
    CHECK(empty.matches.empty());
}

void test_mixed_offsets() {
    const auto dict = make_dict();
    auto cleaner = make_cleaner(dict);

    const CleanResult result = cleaner.clean(u8"用威信加微信");
    CHECK_EQ(result.text, std::string(u8"用微信加微信"));
    CHECK_EQ(result.matches.size(), std::size_t{2});
    CHECK_EQ(result.matches[0].begin, std::size_t{1});
    CHECK_EQ(result.matches[0].end, std::size_t{3});
    CHECK_EQ(result.matches[1].begin, std::size_t{4});
    CHECK_EQ(result.matches[1].end, std::size_t{6});
    CHECK_EQ(result.matches[0].matched, U("威信"));
    CHECK_EQ(result.matches[1].matched, U("微信"));
    CHECK(result.matches[0].status == MatchStatus::LockedByAc);
    CHECK(result.matches[1].status == MatchStatus::LockedByAc);
}

void test_clean_u32_overload() {
    const auto dict = make_dict();
    auto cleaner = make_cleaner(dict);

    const CleanResult result = cleaner.clean(U("用薇信加我"));
    CHECK_EQ(result.text, std::string(u8"用微信加我"));
    CHECK_EQ(result.matches.size(), std::size_t{1});
}

}  // namespace

int main() {
    test_exact_canonical();
    test_exact_alias();
    test_pinyin_homophone();
    test_short_fuzzy_is_rejected();
    test_long_fuzzy_match();
    test_long_exact_pinyin();
    test_fuzzy_limited_by_distance();
    test_fuzzy_threshold_is_configurable();
    test_fuzzy_requires_first_syllable();
    test_zero_distance_config();
    test_pinyin_disabled();
    test_mask_exact();
    test_custom_mask_char();
    test_multiple_matches();
    test_exact_not_double_matched();
    test_external_ac_word_list();
    test_ac_lock_blocks_later_stages();
    test_no_match();
    test_mixed_offsets();
    test_clean_u32_overload();
    return test::finish("test_text_cleaner");
}
