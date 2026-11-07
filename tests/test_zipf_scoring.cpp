#include "test_framework.h"
#include "text_clean/text_cleaner.h"
#include "text_clean/pinyin_dict.h"
#include <cmath>
#include <limits>
using namespace text_clean;
int main() {
    PinyinDict d;d.add_char(U'微',{"wei1"});d.add_char(U'威',{"wei1"});d.add_char(U'薇',{"wei1"});d.add_char(U'信',{"xin4"});
    auto lex=[](){Lexicon l;LexiconEntry e;e.canonical=U"微信";e.pinyin={"wei","xin"};e.pronunciations={{"wei1","xin4"}};l.add_entry(e);return l;};
    WordFrequency f;f.use_zipf();f.add_zipf(U"微信",4.85);f.add_zipf(U"威信",3.62);
    CHECK_EQ(f.size(),std::size_t{2});CHECK(!f.empty());CHECK(!f.zipf(U"薇信"));
    TextCleaner c(lex(),d,{},std::vector<std::u32string>{},f);
    auto r=c.clean("威信");CHECK_EQ(r.text,std::string("微信"));CHECK_EQ(r.matches.size(),std::size_t{1});
    if(!r.matches.empty()) {
        CHECK(std::abs(r.matches[0].log_ratio-2.302585*(4.85-3.62))<1e-12);
        CHECK(std::abs(r.matches[0].score-(2.302585*(4.85-3.62)-.7))<1e-12);
        CHECK_EQ(r.matches[0].candidate_zipf.value(),4.85);
    }
    const auto ctx=c.prepare_context("微信微信微信","微信","微信微信");
    CHECK_EQ(c.clean("薇信",ctx).text,std::string("薇信")); // missing KEEP evidence cannot be invented
    TextCleaner lock(lex(),d,{},std::vector<std::u32string>{U"威"},f);
    CHECK_EQ(lock.clean("威信").text,std::string("威信"));
    TextCleaner bridge(lex(),d,{},std::vector<std::u32string>{U"信"},f);
    CHECK_EQ(bridge.clean("威信").text,std::string("微信"));
    f.add_zipf(U"威信",4.85);
    TextCleaner tied(lex(),d,{},std::vector<std::u32string>{},f);
    CHECK_EQ(tied.clean("威信",ctx).text,std::string("威信"));
    WordFrequency missing;missing.use_zipf();missing.add_zipf(U"威信",1);
    TextCleaner absent(lex(),d,{},std::vector<std::u32string>{},missing);
    CHECK_EQ(absent.clean("威信").text,std::string("威信"));
    for(double x:{0.,-1.,std::numeric_limits<double>::infinity(),std::numeric_limits<double>::quiet_NaN()}) {
        bool threw=false;try {f.add_zipf(U"威信",x);}catch(const std::invalid_argument&){threw=true;}CHECK(threw);
    }
    bool mixed=false;try {f.add_word(U"微信",3);}catch(const std::logic_error&){mixed=true;}CHECK(mixed);
    std::string error;CHECK(f.load_string("微信\t3\n",&error));CHECK(!f.is_zipf());CHECK_EQ(f.count(U"微信"),3u);
    return test::finish("test_zipf_scoring");
}
