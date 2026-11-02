#include "test_framework.h"
#include "text_clean/text_cleaner.h"
#include "text_clean/pinyin_dict.h"
#include "text_clean/word_maintaining.h"
#include "text_clean/utf8.h"
using namespace text_clean;
TextCleaner cleaner(const PinyinDict& d, const char* word, const char* pronunciation,
                    std::uint64_t frequency = 3) {
    Lexicon l; std::string error;
    CHECK(Lexicon::parse(std::string(word)+"\t"+pronunciation+"\t-\treplace", {}, l, &error));
    WordFrequency f; f.add_word_utf8(word,frequency);
    // Force the observed ambiguous segmentation, without protecting the typo.
    f.add_word(U"要略",26); f.add_word(U"略微",277); f.add_word(U"一点",14165);
    return TextCleaner(std::move(l),d,{},std::vector<std::u32string>{},std::move(f));
}
int main() {
    PinyinDict d; std::string error;
    CHECK(d.load_file(std::string(TC_DATA_DIR)+"/pinyin_dict.txt",&error));
    // The full character dictionary still contains the secondary reading.
    CHECK_EQ(PinyinDict::aligned_distance(d.to_toned_syllables(U"微深"),
        d.to_toned_syllables(U"微信"),2),std::size_t{0});
    for (const auto frequency : {std::uint64_t{3},std::uint64_t{1000000}}) {
        auto c=cleaner(d,"微信","wei xin",frequency);
        const auto context=c.prepare_context("微信微信", "微信教程", "微信微信微信");
        for (const auto* text : {"这个颜色要略微深一点", "颜色略微深一些", "微深", "微申", "微身"}) {
            CHECK_EQ(c.clean(text).text,std::string(text));
            CHECK_EQ(c.clean(text,context).text,std::string(text));
        }
        CHECK_EQ(c.clean("薇信").text,std::string("微信"));
        CHECK_EQ(c.clean("位信").text,std::string("微信"));
    }
    // Explicit non-primary target pronunciation must survive: not a global
    // primary-reading-only fix. Also preserve source-side polyphone matching.
    auto bank=cleaner(d,"银行","yin hang",1000);
    CHECK_EQ(bank.clean("银航").text,std::string("银行"));
    auto bankcard=cleaner(d,"银行卡","yin hang ka",1000);
    CHECK_EQ(bankcard.clean("银形卡").text,std::string("银形卡"));
    auto source_poly=cleaner(d,"航芒","hang mang",1000);
    CHECK_EQ(source_poly.clean("行芒").text,std::string("航芒"));
    // Synthetic reading-order invariance proves this is not a 信 special case.
    PinyinDict custom;
    custom.add_char(U'甲',{"jia1"});
    custom.add_char(U'乙',{"shen1","xin4"});
    custom.add_char(U'丙',{"shen1"});
    custom.add_char(U'丁',{"xin4"});
    auto pinned=cleaner(custom,"甲乙","jia xin",1000000);
    CHECK_EQ(pinned.clean("甲丙").text,std::string("甲丙"));
    CHECK_EQ(pinned.clean("甲丁").text,std::string("甲乙"));
    // Missing target reading falls back only to the declared base (tone unknown).
    PinyinDict missing;
    missing.add_char(U'甲',{"jia1"}); missing.add_char(U'乙',{"shen1"});
    missing.add_char(U'丙',{"shen1"}); missing.add_char(U'丁',{"xin4"});
    auto fallback=cleaner(missing,"甲乙","jia xin",1000000);
    CHECK_EQ(fallback.clean("甲丙").text,std::string("甲丙"));
    CHECK_EQ(fallback.clean("甲丁").text,std::string("甲乙"));
    return test::finish("test_word_pronunciation");
}
