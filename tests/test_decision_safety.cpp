#include "test_framework.h"
#include "text_clean/text_cleaner.h"
#include "text_clean/pinyin_dict.h"
#include "text_clean/pinyin_index.h"
#include <filesystem>
#include <fstream>
#include <cmath>
using namespace text_clean;
int main() {
    PinyinDict d;
    for(auto c:std::u32string(U"微薇维威"))d.add_char(c,{"wei1"});
    d.add_char(U'信',{"xin4"});d.add_char(U'星',{"xing1"});
    d.add_char(U'感',{"gan3"});d.add_char(U'敏',{"min3"});d.add_char(U'词',{"ci2"});d.add_char(U'慈',{"ci2"});
    auto lex=[&](){Lexicon l;LexiconEntry e;e.canonical=U"微信";e.aliases={U"威信"};e.pinyin={"wei","xin"};e.pronunciations={{"wei1","xin4"}};l.add_entry(e);return l;};
    WordFrequency f;f.add_word(U"微信",1000);
    TextCleaner alias(lex(),d,{},std::vector<std::u32string>{},f);
    CHECK_EQ(alias.clean("威信").text,std::string("微信"));
    CHECK_EQ(alias.clean("微信").text,std::string("微信"));
    TextCleaner veto(lex(),d,{},std::vector<std::u32string>{},{});
    CHECK_EQ(veto.clean("威信").text,std::string("威信")); // alias does not bypass score
    TextCleaner locked(lex(),d,{},std::vector<std::u32string>{U"威信"},f);
    CHECK_EQ(locked.clean("威信").text,std::string("威信"));
    TextCleaner bridge(lex(),d,{},std::vector<std::u32string>{U"信"},f);
    const auto repaired=bridge.clean("薇信");CHECK_EQ(repaired.text,std::string("微信"));
    CHECK_EQ(bridge.clean("薇\n信").text,std::string("薇\n信"));
    TextCleaner forbidden(lex(),d,{},std::vector<std::u32string>{U"薇"},f);
    CHECK_EQ(forbidden.clean("薇信").text,std::string("薇信"));
    TextCleaner overlap(lex(),d,{},std::vector<std::u32string>{U"薇信",U"信星"},f);
    CHECK_EQ(overlap.clean("薇信星").text,std::string("薇信星"));
    Lexicon mask;LexiconEntry m;m.canonical=U"敏感词";m.pinyin={"min","gan","ci"};m.action=Action::Mask;mask.add_entry(m);
    WordFrequency mf;mf.add_word(m.canonical,100000);
    TextCleaner masked(std::move(mask),d,{},std::vector<std::u32string>{U"敏感词"},mf);
    CHECK_EQ(masked.clean("敏感词、敏感慈").text,std::string("敏感词、敏感慈"));
    Vocabulary reference;reference.add(U"薇信");
    TextCleaner referenced(lex(),d,{},std::vector<std::u32string>{},f,reference);
    CHECK_EQ(referenced.clean("薇信").text,std::string("微信")); // membership is not a lock
    WordFrequency low;low.add_word(U"微信",3);
    Vocabulary known_brand;known_brand.add(U"微星");
    TextCleaner contextual(lex(),d,{},std::vector<std::u32string>{},low,known_brand);
    const auto misleading=contextual.prepare_context("微信微信","微信教程","微信微信微信");
    CHECK_EQ(contextual.clean("微星",misleading).text,std::string("微星"));
    // This is not unconditional vocabulary protection: a positive static
    // decision is still allowed (covered by referenced above).
    WordFrequency original=f;original.add_word(U"薇信",1000);
    TextCleaner keep(lex(),d,{},std::vector<std::u32string>{},original);
    CHECK_EQ(keep.clean("薇信").text,std::string("薇信")); // explicit KEEP score 0 beats replacement
    for(const auto& match:repaired.matches)if(match.action==Action::Replace)
        CHECK(std::abs(match.score-(std::log(1001.0)-0.7))<1e-12); // frozen equation
    const auto cache=(std::filesystem::temp_directory_path()/"tc_index_fixture.bin").string();
    PinyinInvertedIndex index;index.add(1,{"wei","xin"});
    index.build_cached(cache,"first");CHECK(index.build_cached(cache,"first"));
    CHECK_EQ(index.find_exact({"wei","xin"}).at(0),1u);
    CHECK(!index.build_cached(cache,"changed-source"));
    std::ofstream(cache,std::ios::binary|std::ios::trunc)<<"corrupted";
    CHECK(!index.build_cached(cache,"changed-source"));CHECK(index.build_cached(cache,"changed-source"));
    index.add(2,{"wei","xin"});CHECK(!index.build_cached(cache,"changed-source"));
    CHECK_EQ(index.find_exact({"wei","xin"}).size(),std::size_t{2});
    // A complete word reading cannot be fabricated by mixing alternatives.
    d.add_char(U'甲',{"jia1","ga1"});d.add_char(U'乙',{"yi1","ni1"});
    d.add_char(U'丙',{"jia1"});d.add_char(U'丁',{"ni1"});
    Lexicon multi;LexiconEntry e;e.canonical=U"甲乙";e.pinyin={"jia","yi"};e.pronunciations={{"jia1","yi1"},{"ga1","ni1"}};multi.add_entry(e);
    CleanerConfig exact;exact.max_pinyin_distance=0;
    WordFrequency multi_f;multi_f.add_word(U"甲乙",100000);
    TextCleaner coherent(std::move(multi),d,exact,std::vector<std::u32string>{},multi_f);
    CHECK_EQ(coherent.clean("丙丁").text,std::string("丙丁"));
    // Enabled five/six-character words must not be limited to four single-char tokens.
    for(auto c:std::u32string(U"天地人和合万事"))d.add_char(c,{"he2"});
    for(auto word:{std::u32string(U"天地人和万"),std::u32string(U"天地人和万事")}) {
        Lexicon l;LexiconEntry long_e;long_e.canonical=word;long_e.pinyin=d.to_pinyin(word);l.add_entry(long_e);
        WordFrequency lf;lf.add_word(word,100000);auto typo=word;typo[3]=U'合';
        TextCleaner long_c(std::move(l),d,{},std::vector<std::u32string>{},lf);
        CHECK_EQ(long_c.clean(typo).text,utf8::encode(word));
    }
    return test::finish("test_decision_safety");
}
