#include "test_framework.h"

#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "text_clean/char_frequency.h"
#include "text_clean/lexicon.h"
#include "text_clean/pinyin_dict.h"
#include "text_clean/text_cleaner.h"
#include "text_clean/utf8.h"
#include "text_clean/word_frequency.h"

namespace {

using text_clean::Action;
using text_clean::CharFrequency;
using text_clean::CleanResult;
using text_clean::CleanerConfig;
using text_clean::Lexicon;
using text_clean::LexiconEntry;
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
    add_entry(lexicon, "第一", {"di", "yi"});
    add_entry(lexicon, "地方", {"di", "fang"});
    add_entry(lexicon, "颈椎", {"jing", "zhui"});
    return lexicon;
}

WordFrequency make_frequency() {
    WordFrequency frequency;
    frequency.add_word_utf8("第一", 10000);
    frequency.add_word_utf8("地方", 2000);
    frequency.add_word_utf8("颈椎", 300);
    return frequency;
}

// 的一 is an ordinary character sequence with a large chance frequency.
// 颈锥 is a rare sequence: both characters are almost unused elsewhere.
CharFrequency make_char_frequency() {
    CharFrequency chars;
    chars.add(U'的', 300000);
    chars.add(U'一', 200000);
    chars.add(U'地', 100000);
    chars.add(U'方', 100000);
    chars.add(U'颈', 2);
    chars.add(U'锥', 1);
    return chars;
}

PinyinDict make_dict() {
    PinyinDict dict;
    std::string error;
    const std::string path = std::string(TC_DATA_DIR) + "/pinyin_dict.txt";
    CHECK(dict.load_file(path, &error));
    if (!error.empty()) std::cerr << "  " << error << "\n";
    return dict;
}

void test_common_sequence_is_not_rewritten() {
    const auto dict = make_dict();
    TextCleaner cleaner(make_lexicon(), dict, {}, std::nullopt, make_frequency(),
                        {}, make_char_frequency());

    // 的一 -> 第一 only differs in the first syllable's base, so the distance
    // penalty alone would not stop it; the chance frequency does.
    const CleanResult result = cleaner.clean(U("的一"));
    CHECK_EQ(result.text, std::string(u8"的一"));
    CHECK(result.matches.empty());
}

void test_without_baseline_keeps_legacy_behaviour() {
    const auto dict = make_dict();
    TextCleaner cleaner(make_lexicon(), dict, {}, std::nullopt, make_frequency());

    // No character table: an unattested original still has f(O) = 0, which is
    // the behaviour the baseline replaces.
    const CleanResult result = cleaner.clean(U("的一"));
    CHECK_EQ(result.text, std::string(u8"第一"));
    CHECK_EQ(result.matches.size(), std::size_t{1});
}

void test_rare_sequence_is_still_corrected() {
    const auto dict = make_dict();
    TextCleaner cleaner(make_lexicon(), dict, {}, std::nullopt, make_frequency(),
                        {}, make_char_frequency());

    const CleanResult result = cleaner.clean(U("颈锥"));
    CHECK_EQ(result.text, std::string(u8"颈椎"));
    CHECK_EQ(result.matches.size(), std::size_t{1});
    CHECK(result.matches[0].log_ratio > 1.0);
}

void test_no_zero_evidence_channel() {
    const auto dict = make_dict();
    // A candidate whose own table frequency is 0 must not be admitted by a
    // floor: "存在正向证据才可改写".
    WordFrequency frequency;
    frequency.add_word_utf8("颈椎", 0);
    TextCleaner cleaner(make_lexicon(), dict, {}, std::nullopt,
                        std::move(frequency), {}, make_char_frequency());
    const CleanResult result = cleaner.clean(U("颈锥"));
    CHECK_EQ(result.text, std::string(u8"颈锥"));
    CHECK(result.matches.empty());
}

}  // namespace

int main() {
    test_common_sequence_is_not_rewritten();
    test_without_baseline_keeps_legacy_behaviour();
    test_rare_sequence_is_still_corrected();
    test_no_zero_evidence_channel();
    return test::finish("test_legitimacy");
}
