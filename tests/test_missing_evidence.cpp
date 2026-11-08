#include "test_framework.h"
#include "text_clean/text_cleaner.h"
#include "text_clean/pinyin_dict.h"
#include <string>
#include <vector>
using namespace text_clean;

namespace {
Lexicon lex() {
    Lexicon l;
    LexiconEntry e;
    e.canonical = U"微信";
    e.pinyin = {"wei", "xin"};
    e.pronunciations = {{"wei1", "xin4"}};
    l.add_entry(e);
    return l;
}
using ME = CleanerConfig::MissingEvidence;
const std::vector<std::u32string> kNoLocks;
constexpr double K = 2.302585;

WordFrequency table() {
    WordFrequency f;
    f.use_zipf();
    f.add_zipf(U"微信", 4.85);
    f.add_char_zipf(U'薇', 3.0);  // est(薇信) = 3.0 + 5.0 - 9 = -1.0
    f.add_char_zipf(U'信', 5.0);
    return f;
}
}  // namespace

int main() {
    PinyinDict d;
    d.add_char(U'微', {"wei1"});
    d.add_char(U'威', {"wei1"});
    d.add_char(U'薇', {"wei1"});
    d.add_char(U'信', {"xin4"});
    const WordFrequency base = table();

    // 1) 基线 veto：原文没有词级证据就不改（E022 冻结行为）。
    TextCleaner veto(lex(), d, {}, kNoLocks, base);
    CHECK_EQ(veto.clean("薇信").text, std::string("薇信"));

    // 2) M1 char：用字频独立估计补原文，ZipfO = -1.0。
    CleanerConfig c1;
    c1.missing_evidence = ME::CharEstimate;
    TextCleaner m1(lex(), d, c1, kNoLocks, base);
    const auto r1 = m1.clean("薇信");
    CHECK_EQ(r1.text, std::string("微信"));
    CHECK_EQ(r1.matches.size(), std::size_t{1});
    if (!r1.matches.empty()) {
        CHECK(std::abs(r1.matches[0].original_zipf.value() + 1.0) < 1e-12);
        CHECK(std::abs(r1.matches[0].log_ratio - K * (4.85 + 1.0)) < 1e-12);
    }

    // 3) M2 fixed：不查字频，直接按 ZipfC - K 记原文档。
    CleanerConfig c2;
    c2.missing_evidence = ME::FixedCap;
    c2.missing_cap = 1.5;
    TextCleaner m2(lex(), d, c2, kNoLocks, base);
    const auto r2 = m2.clean("薇信");
    CHECK_EQ(r2.text, std::string("微信"));
    if (!r2.matches.empty()) CHECK(std::abs(r2.matches[0].log_ratio - K * 1.5) < 1e-12);

    // 4) M2 上限收紧到 0.2 档：log_ratio 0.46 < μ，必须不改（证明上限真的生效）。
    CleanerConfig c3 = c2;
    c3.missing_cap = 0.2;
    TextCleaner m3(lex(), d, c3, kNoLocks, base);
    CHECK_EQ(m3.clean("薇信").text, std::string("薇信"));

    // 5) M1+M2：字频估计 -1.0 被上限抬到 4.85-1.5=3.35，与 M2 同分。
    CleanerConfig c4;
    c4.missing_evidence = ME::CharEstimate;
    c4.missing_cap = 1.5;
    TextCleaner m4(lex(), d, c4, kNoLocks, base);
    const auto r4 = m4.clean("薇信");
    CHECK_EQ(r4.text, std::string("微信"));
    if (!r4.matches.empty()) CHECK(std::abs(r4.matches[0].log_ratio - K * 1.5) < 1e-12);

    // 6) 连字频都缺 → 仍然弃权，不凭空造证据。
    WordFrequency partial;
    partial.use_zipf();
    partial.add_zipf(U"微信", 4.85);
    partial.add_char_zipf(U'信', 5.0);
    TextCleaner m5(lex(), d, c1, kNoLocks, partial);
    CHECK_EQ(m5.clean("薇信").text, std::string("薇信"));

    // 7) 原文本来有词级证据时，模式不介入，结果与基线一致。
    WordFrequency both = table();
    both.add_zipf(U"薇信", 4.7);  // 4.85-4.7 = 0.15 → log_ratio 0.35 < μ
    TextCleaner b0(lex(), d, {}, kNoLocks, both);
    TextCleaner b1(lex(), d, c1, kNoLocks, both);
    CHECK_EQ(b0.clean("薇信").text, std::string("薇信"));
    CHECK_EQ(b1.clean("薇信").text, b0.clean("薇信").text);

    // 8) 目标词缺词级证据时弃权（M3 兜底已按 E025 结论移除）。
    WordFrequency no_target;
    no_target.use_zipf();
    no_target.add_zipf(U"薇信", 0.5);   // 原文有词级证据，且很低；目标"微信"没有
    CleanerConfig c5;
    c5.missing_evidence = ME::CharEstimate;
    c5.missing_cap = 0.6;
    TextCleaner m6(lex(), d, c5, kNoLocks, no_target);
    CHECK_EQ(m6.clean("薇信").text, std::string("薇信"));  // 目标侧缺证据：弃权

    // 9) 多字目标同样弃权：不再用字频乘积估计冒充目标词证据。
    WordFrequency idiom;
    idiom.use_zipf();
    idiom.add_zipf(U"卖关于绝", 3.0);
    for (char32_t ch : std::u32string{U'卖', U'官', U'鬻', U'爵'})
        idiom.add_char_zipf(ch, 3.0);
    idiom.add_char_zipf(U'关', 4.0);
    idiom.add_char_zipf(U'于', 4.0);
    idiom.add_char_zipf(U'绝', 4.0);
    Lexicon idiom_lex;
    LexiconEntry ie;
    ie.canonical = U"卖官鬻爵";
    ie.pinyin = {"mai", "guan", "yu", "jue"};
    ie.pronunciations = {{"mai4", "guan1", "yu4", "jue2"}};
    idiom_lex.add_entry(ie);
    PinyinDict idict;
    for (const auto& pair : {std::make_pair(U'卖', "mai4"), std::make_pair(U'买', "mai3"),
                             std::make_pair(U'官', "guan1"), std::make_pair(U'关', "guan1"),
                             std::make_pair(U'于', "yu2"), std::make_pair(U'鬻', "yu4"),
                             std::make_pair(U'爵', "jue2"), std::make_pair(U'绝', "jue2")})
        idict.add_char(pair.first, {pair.second});
    CleanerConfig c6;
    c6.missing_evidence = ME::CharEstimate;
    c6.missing_cap = 0.6;
    TextCleaner m8(idiom_lex, idict, c6, kNoLocks, idiom);
    // 目标"卖官鬻爵"没有词级证据 → 直接弃权，与原文证据高低无关
    CHECK_EQ(m8.clean("卖关于绝").text, std::string("卖关于绝"));

    // 10) 旧次数口径不受新模式影响（模式只在 Zipf 分支生效）。
    WordFrequency counts;
    counts.add_word(U"微信", 3);
    TextCleaner legacy(lex(), d, c1, kNoLocks, counts);
    CHECK_EQ(legacy.clean("薇信").text, std::string("微信"));

    return test::finish("test_missing_evidence");
}
