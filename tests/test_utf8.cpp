#include "test_framework.h"

#include <string>

#include "text_clean/utf8.h"

namespace {

using text_clean::utf8::decode;
using text_clean::utf8::encode;
using text_clean::utf8::is_han;

void test_roundtrip() {
    const std::string original = u8"ASR 文本清洗：微信 → WeChat";
    const auto points = decode(original);
    CHECK_EQ(encode(points), original);
    CHECK_EQ(points.size(), std::size_t{20});
}

void test_decoding() {
    const auto points = decode(u8"你a好");
    CHECK_EQ(points.size(), std::size_t{3});
    CHECK_EQ(points[0], char32_t{0x4F60});
    CHECK_EQ(points[1], char32_t{U'a'});
    CHECK_EQ(points[2], char32_t{0x597D});
}

void test_invalid_sequences() {
    const std::string truncated = "\xE4\xBD";
    const auto points = decode(truncated);
    CHECK_EQ(points.size(), std::size_t{1});
    CHECK_EQ(points[0], char32_t{0xFFFD});

    const std::string bad_continuation = "\xE4\x41\xBD";
    const auto bad = decode(bad_continuation);
    CHECK_EQ(bad.size(), std::size_t{3});
    CHECK_EQ(bad[0], char32_t{0xFFFD});
    CHECK_EQ(bad[1], char32_t{U'A'});

    const std::string stray = "\x80";
    const auto stray_points = decode(stray);
    CHECK_EQ(stray_points.size(), std::size_t{1});
    CHECK_EQ(stray_points[0], char32_t{0xFFFD});

    const std::string overlong = "\xC0\xAF";
    const auto overlong_points = decode(overlong);
    CHECK_EQ(overlong_points[0], char32_t{0xFFFD});
}

void test_han_detection() {
    CHECK(is_han(U'微'));
    CHECK(is_han(U'信'));
    CHECK(is_han(U'\u3400'));
    CHECK(!is_han(U'a'));
    CHECK(!is_han(U'1'));
    CHECK(!is_han(U'，'));
    CHECK(!is_han(U'\U0001F600'));
}

void test_four_byte() {
    const std::string emoji = "\xF0\x9F\x98\x80";  // U+1F600
    const auto points = decode(emoji);
    CHECK_EQ(points.size(), std::size_t{1});
    CHECK_EQ(points[0], char32_t{0x1F600});
    CHECK_EQ(encode(points), emoji);
}

}  // namespace

int main() {
    test_roundtrip();
    test_decoding();
    test_invalid_sequences();
    test_han_detection();
    test_four_byte();
    return test::finish("test_utf8");
}
