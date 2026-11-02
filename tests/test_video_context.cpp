#include "test_framework.h"
#include "text_clean/text_cleaner.h"
#include "text_clean/pinyin_dict.h"
#include "text_clean/utf8.h"
#include <cmath>
using namespace text_clean;
int main() {
    PinyinDict dict;
    std::string error;
    CHECK(dict.load_file(std::string(TC_DATA_DIR) + "/pinyin_dict.txt", &error));
    Lexicon lex;
    CHECK(Lexicon::load_file(std::string(TC_DATA_DIR) + "/lexicon.txt",
        [&](const std::u32string& w) { return dict.to_pinyin(w); }, lex, &error));
    WordFrequency freq;
    CHECK(freq.load_file(std::string(TC_DATA_DIR) + "/word_freq.txt", &error));
    Vocabulary vocabulary;
    CHECK(vocabulary.load_file(std::string(TC_DATA_DIR) + "/dict.txt", &error));
    TextCleaner cleaner(std::move(lex), dict, {}, std::vector<std::u32string>{}, std::move(freq), std::move(vocabulary));
    const std::vector<std::string> negatives = {
        "我买了微星主板", "请在微信里讨论微星主板", "我在微信群里讨论微星显卡",
        "微星笔记本用于开发", "王维的诗", "李白与杜甫", "陈晨负责数据分析",
        "张华介绍研究结果", "量子纠缠", "傅里叶变换用于频谱分析", "熵增和信息论",
        "使用拉普拉斯变换", "支付保证金", "支付保护账户", "谈话核实", "谈话人员",
        "提升个人威信", "在微信里比较微星和华为的产品"
    };
    for (const auto& metadata : {std::string{}, std::string("旅游摄影"), std::string("微信华为转账"),
                                std::string("微信华为转账微信华为转账微信华为转账")}) {
        const auto misleading = cleaner.prepare_context(metadata, metadata, metadata);
        for (const auto& correct : negatives)
            CHECK_EQ(cleaner.clean(correct, misleading).text, correct);
    }
    const auto ctx = cleaner.prepare_context("微信", "微信使用教程", "微信微信微信");
    CHECK(ctx.bonus(U"微信") <= std::log(2.5));
    CHECK(ctx.bonus(U"不存在") == 0);
    CHECK_EQ(cleaner.clean("薇星").text, std::string("薇星"));
    CHECK_EQ(cleaner.clean("薇星", ctx).text, std::string("微信"));
    const auto title_only = cleaner.prepare_context("微信", "", "");
    const auto corroborated = cleaner.prepare_context("微信", "", "微信微信微信");
    CHECK_EQ(cleaner.clean("薇星", title_only).text, std::string("薇星"));
    CHECK_EQ(cleaner.clean("薇星", corroborated).text, std::string("微信"));
    const auto noisy = cleaner.prepare_context("微信", "", "微星微星微星微星");
    CHECK_EQ(cleaner.clean("薇星", noisy).text, std::string("薇星"));
    const auto saturated = cleaner.prepare_context("微信微信微信微信", "微信微信", "微信微信微信微信微信");
    CHECK(std::abs(saturated.bonus(U"微信") - ctx.bonus(U"微信")) < 1e-12);
    const auto only_asr = cleaner.prepare_context("", "", std::string(10000, 'x') + "微信微信微信");
    CHECK(only_asr.bonus(U"微信") == 0);
    CHECK_EQ(cleaner.clean("薇星", only_asr).text, std::string("薇星"));
    const auto unrelated = cleaner.prepare_context("支付宝", "支付宝教程", "微信微信");
    CHECK_EQ(cleaner.clean("薇星", unrelated).text, std::string("薇星"));
    // A valid static word cannot be forced to change by repetition.
    const auto attack = cleaner.prepare_context("微信微信微信", "微信微信微信", "微信微信微信");
    CHECK_EQ(cleaner.clean("威信", attack).text, std::string("威信"));
    CHECK_EQ(cleaner.clean("薇星").text, std::string("薇星")); // no context leakage
    CHECK_EQ(cleaner.clean("他在位信群里说").text, std::string("他在微信群里说"));
    CHECK_EQ(cleaner.clean("支付保").text, std::string("支付宝"));
    for (const auto* text : {"谈话核实", "谈话人员", "支付保证金", "支付保护账户", "转折", "花了很多心血", "画上一个句号"})
        CHECK_EQ(cleaner.clean(text, ctx).text, std::string(text));
    const auto result = cleaner.clean("位信、支付保、他在位信群里说");
    CHECK_EQ(result.text, std::string("微信、支付宝、他在微信群里说"));
    for (std::size_t i = 1; i < result.matches.size(); ++i)
        CHECK(result.matches[i - 1].end <= result.matches[i].begin);
    // AC locking still overrides contextual evidence.
    Lexicon locked_lex;
    CHECK(Lexicon::parse("微信\twei xin\t-\treplace", {}, locked_lex, &error));
    WordFrequency locked_freq; locked_freq.add_word(U"微信", 3);
    TextCleaner locked(std::move(locked_lex), dict, {}, std::vector<std::u32string>{U"薇星"}, std::move(locked_freq));
    CHECK_EQ(locked.clean("薇星", ctx).text, std::string("薇星"));
    return test::finish("test_video_context");
}
