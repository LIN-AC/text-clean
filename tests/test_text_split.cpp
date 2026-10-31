#include "test_framework.h"

#include <string>
#include <vector>

#include "text_clean/text_split.h"

namespace {

using text_clean::Section;
using text_clean::SectionKind;
using text_clean::TextSplitter;

void test_standard_document() {
    const std::string text =
        "===== 标题 =====\n"
        "微信支付故障说明\n"
        "===== 简介 =====\n"
        "今天使用维信和支付包。\n"
        "===== 正文 =====\n"
        "我们用微信和支付宝测试。\n";

    const auto sections = TextSplitter::split(text);
    CHECK_EQ(sections.size(), std::size_t{3});

    CHECK(sections[0].kind == SectionKind::Title);
    CHECK_EQ(sections[0].name, std::string("标题"));
    CHECK_EQ(sections[0].content, std::string("微信支付故障说明\n"));

    CHECK(sections[1].kind == SectionKind::Intro);
    CHECK_EQ(sections[1].name, std::string("简介"));
    CHECK_EQ(sections[1].content, std::string("今天使用维信和支付包。\n"));

    CHECK(sections[2].kind == SectionKind::Body);
    CHECK_EQ(sections[2].name, std::string("正文"));
    CHECK_EQ(sections[2].content, std::string("我们用微信和支付宝测试。\n"));

    CHECK_EQ(TextSplitter::join(sections), text);
}

void test_crlf_and_marker_spacing() {
    const std::string text =
        "  ===== 标题 =====  \r\n"
        "T\r\n"
        "=====简介=====\r\n"
        "I\r\n"
        "===== 正文 =====\r\n"
        "B\r\n";
    const auto sections = TextSplitter::split(text);
    CHECK_EQ(sections.size(), std::size_t{3});
    CHECK(sections[0].kind == SectionKind::Title);
    CHECK(sections[1].kind == SectionKind::Intro);
    CHECK(sections[2].kind == SectionKind::Body);
    CHECK_EQ(sections[0].content, std::string("T\n"));
    CHECK_EQ(sections[1].content, std::string("I\n"));
    CHECK_EQ(sections[2].content, std::string("B\n"));
    CHECK_EQ(TextSplitter::join(sections),
             std::string("===== 标题 =====\nT\n===== 简介 =====\nI\n"
                         "===== 正文 =====\nB\n"));
}

void test_leading_content() {
    const std::string text =
        "前言\n"
        "===== 标题 =====\n"
        "T\n";
    const auto sections = TextSplitter::split(text);
    CHECK_EQ(sections.size(), std::size_t{2});
    CHECK(sections[0].kind == SectionKind::Other);
    CHECK(sections[0].name.empty());
    CHECK_EQ(sections[0].content, std::string("前言\n"));
    CHECK(sections[1].kind == SectionKind::Title);
    CHECK_EQ(TextSplitter::join(sections), text);
}

void test_unknown_marker_and_empty_sections() {
    const std::string unknown_marker =
        "===== 附录 =====\n"
        "A\n";
    const auto appendix = TextSplitter::split(unknown_marker);
    CHECK_EQ(appendix.size(), std::size_t{1});
    CHECK(appendix[0].kind == SectionKind::Other);
    CHECK_EQ(appendix[0].name, std::string("附录"));
    CHECK_EQ(appendix[0].content, std::string("A\n"));
    CHECK_EQ(TextSplitter::join(appendix), unknown_marker);

    const std::string empty_sections =
        "===== 标题 =====\n"
        "===== 简介 =====\n"
        "I\n"
        "===== 正文 =====\n";
    const auto sections = TextSplitter::split(empty_sections);
    CHECK_EQ(sections.size(), std::size_t{3});
    CHECK(sections[0].content.empty());
    CHECK_EQ(sections[1].content, std::string("I\n"));
    CHECK(sections[2].content.empty());
    CHECK_EQ(TextSplitter::join(sections), empty_sections);
}

void test_unsectioned_and_empty() {
    const std::string plain = "just text\nsecond line";
    const auto sections = TextSplitter::split(plain);
    CHECK_EQ(sections.size(), std::size_t{1});
    CHECK(sections[0].kind == SectionKind::Other);
    CHECK(sections[0].name.empty());
    CHECK_EQ(sections[0].content, plain);
    CHECK_EQ(TextSplitter::join(sections), plain);

    CHECK(TextSplitter::split("").empty());
    CHECK(TextSplitter::join({}).empty());
}

void test_malformed_markers_are_content() {
    const std::string text =
        "===== 标题\n"
        "x ===== 标题 =====\n"
        "===== 标题 ===== trailing\n";
    const auto sections = TextSplitter::split(text);
    CHECK_EQ(sections.size(), std::size_t{1});
    CHECK(sections[0].kind == SectionKind::Other);
    CHECK(sections[0].name.empty());
    CHECK_EQ(sections[0].content, text);
}

void test_kind_names() {
    CHECK_EQ(std::string(TextSplitter::kind_name(SectionKind::Title)),
             std::string("标题"));
    CHECK_EQ(std::string(TextSplitter::kind_name(SectionKind::Intro)),
             std::string("简介"));
    CHECK_EQ(std::string(TextSplitter::kind_name(SectionKind::Body)),
             std::string("正文"));
    CHECK_EQ(std::string(TextSplitter::kind_name(SectionKind::Other)),
             std::string("其他"));
}

}  // namespace

int main() {
    test_standard_document();
    test_crlf_and_marker_spacing();
    test_leading_content();
    test_unknown_marker_and_empty_sections();
    test_unsectioned_and_empty();
    test_malformed_markers_are_content();
    test_kind_names();
    return test::finish("test_text_split");
}