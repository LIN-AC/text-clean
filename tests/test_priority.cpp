#include "test_framework.h"
#include "text_clean/text_cleaner.h"
#include "text_clean/pinyin_dict.h"
#include "text_clean/pinyin_index.h"
#include "text_clean/utf8.h"
using namespace text_clean;
Lexicon lex(const PinyinDict& d, std::initializer_list<std::u32string> words) {
    Lexicon result;
    for (const auto& w : words) { LexiconEntry e; e.canonical=w; e.pinyin=d.to_pinyin(w); e.action=Action::Replace; result.add_entry(e); }
    return result;
}
int main() {
    PinyinDict d; std::string error;
    CHECK(d.load_file(std::string(TC_DATA_DIR)+"/pinyin_dict.txt", &error));
    // Each protected fixture would otherwise be actively rewritten, not just ignored.
    for (const auto& pair : {std::pair<std::u32string,std::u32string>{U"微星",U"微信"}, {U"李白",U"李柏"}, {U"陈晨",U"陈辰"}, {U"熵增",U"商增"}}) {
        WordFrequency f; f.add_word(pair.second,100000);
        TextCleaner unsafe(lex(d,{pair.second}),d,{},std::vector<std::u32string>{},f);
        CHECK(unsafe.clean(pair.first).text != utf8::encode(pair.first));
        Vocabulary v; v.add(pair.first);
        TextCleaner safe(lex(d,{pair.second}),d,{},std::vector<std::u32string>{},f,std::move(v));
        const auto context=safe.prepare_context(utf8::encode(pair.second),utf8::encode(pair.second),utf8::encode(pair.second));
        CHECK_EQ(safe.clean(utf8::encode(pair.first),context).text,utf8::encode(pair.first));
    }
    // More than the limit of wrong-length entries cannot starve the proper bucket.
    PinyinInvertedIndex index;
    for (unsigned i=0;i<100;++i) index.add(i,{"hang","mang","a"});
    index.add_readings(1000,{{"xing","hang"},{"mang"}}); index.build();
    const auto candidates=index.find_aligned_candidates({{"hang"},{"mang"}},1);
    CHECK_EQ(candidates.size(),std::size_t{1}); CHECK_EQ(candidates[0].id,1000u);
    CHECK(index.find_aligned_candidates({{"hang"},{"mang"}},0).empty());
    index.add(1000,{"other","other"}); index.build();
    CHECK(index.find_aligned_candidates({{"hang"},{"mang"}},1).empty());
    Vocabulary loaded;
    CHECK(loaded.load_file(std::string(TC_DATA_DIR)+"/dict.txt", &error));
    CHECK(loaded.contains(U"微星"));
    const auto old_size=loaded.size();
    CHECK(!loaded.load_file(std::string(TC_DATA_DIR)+"/not-present-vocabulary", &error));
    CHECK_EQ(loaded.size(),old_size); // failed load leaves prior evidence intact
    WordFrequency f; f.add_word(U"航芒",1000);
    TextCleaner poly(lex(d,{U"航芒"}),d,{},std::vector<std::u32string>{},f);
    CHECK_EQ(poly.clean("行芒").text,std::string("航芒"));
    const auto a=d.to_toned_syllables(U"甲乙"), b=d.to_toned_syllables(U"乙甲");
    CHECK_EQ(PinyinDict::toned_distance(a,b,5),std::size_t{2});
    CHECK_EQ(PinyinDict::aligned_distance(a,b,5),std::size_t{4});
    CHECK_EQ(PinyinDict::aligned_distance(a,b,1),std::size_t{2});
    // Similar evidence for overlapping spans: abstain for the entire conflict.
    WordFrequency equal; equal.add_word(U"微信",100); equal.add_word(U"薇信宝",100);
    TextCleaner ambiguous(lex(d,{U"微信",U"薇信宝"}),d,{},std::vector<std::u32string>{},equal);
    CHECK_EQ(ambiguous.clean("薇信包").text,std::string("薇信包"));
    WordFrequency tied; tied.add_word(U"晨尘",100); tied.add_word(U"臣沉",100);
    TextCleaner tie(lex(d,{U"晨尘",U"臣沉"}),d,{},std::vector<std::u32string>{},tied);
    TextCleaner reverse_tie(lex(d,{U"臣沉",U"晨尘"}),d,{},std::vector<std::u32string>{},tied);
    CHECK_EQ(tie.clean("陈辰").text,std::string("陈辰"));
    CHECK_EQ(reverse_tie.clean("陈辰").text,std::string("陈辰"));
    // A much stronger later-starting proposal wins, not the earliest start.
    WordFrequency strong; strong.add_word(U"微信",3); strong.add_word(U"信宝",100000);
    TextCleaner later(lex(d,{U"微信",U"信宝"}),d,{},std::vector<std::u32string>{},strong);
    CHECK_EQ(later.clean("薇信包").text,std::string("薇信宝"));
    // Left and right local residue use the same permission rule.
    WordFrequency boundaries; boundaries.add_word(U"在位",100); boundaries.add_word(U"信群",100);
    boundaries.add_word(U"微信",3); boundaries.add_word(U"支付",100); boundaries.add_word(U"保证金",100);
    boundaries.add_word(U"支付宝",3);
    TextCleaner boundary(lex(d,{U"微信",U"支付宝"}),d,{},std::vector<std::u32string>{},boundaries);
    CHECK_EQ(boundary.clean("在位信群").text,std::string("在位信群")); // both known words cut
    CHECK_EQ(boundary.clean("支付保证金").text,std::string("支付保证金"));
    WordFrequency symmetric; symmetric.add_word(U"在位",100); symmetric.add_word(U"信件",100); symmetric.add_word(U"微信",3);
    TextCleaner edges(lex(d,{U"微信"}),d,{},std::vector<std::u32string>{},symmetric);
    CHECK_EQ(edges.clean("在位信").text,std::string("在微信"));
    CHECK_EQ(edges.clean("薇信件").text,std::string("微信件"));
    return test::finish("test_priority");
}
