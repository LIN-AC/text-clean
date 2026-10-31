#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>

namespace text_clean::utf8 {

// True for CJK Unified Ideographs and their common extensions.
inline bool is_han(char32_t cp) {
    return (cp >= 0x4E00 && cp <= 0x9FFF) ||
           (cp >= 0x3400 && cp <= 0x4DBF) ||
           (cp >= 0xF900 && cp <= 0xFAFF) ||
           (cp >= 0x20000 && cp <= 0x2FA1F) ||
           cp == 0x3007;
}

// Decodes UTF-8 into code points. Invalid bytes are replaced with U+FFFD.
inline std::u32string decode(std::string_view input) {
    std::u32string out;
    out.reserve(input.size());

    std::size_t i = 0;
    while (i < input.size()) {
        const auto b0 = static_cast<unsigned char>(input[i]);
        char32_t cp = 0;
        std::size_t len = 0;
        if (b0 < 0x80) {
            cp = b0;
            len = 1;
        } else if ((b0 & 0xE0) == 0xC0) {
            cp = b0 & 0x1Fu;
            len = 2;
        } else if ((b0 & 0xF0) == 0xE0) {
            cp = b0 & 0x0Fu;
            len = 3;
        } else if ((b0 & 0xF8) == 0xF0) {
            cp = b0 & 0x07u;
            len = 4;
        } else {
            out.push_back(0xFFFD);
            ++i;
            continue;
        }

        if (i + len > input.size()) {
            out.push_back(0xFFFD);
            break;
        }

        bool valid = true;
        for (std::size_t k = 1; k < len; ++k) {
            const auto b = static_cast<unsigned char>(input[i + k]);
            if ((b & 0xC0) != 0x80) {
                valid = false;
                break;
            }
            cp = (cp << 6) | (b & 0x3Fu);
        }
        if (!valid) {
            out.push_back(0xFFFD);
            ++i;
            continue;
        }

        static constexpr char32_t kMinCodePoint[] = {0, 0, 0x80, 0x800, 0x10000};
        if (cp < kMinCodePoint[len] || cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF)) {
            out.push_back(0xFFFD);
        } else {
            out.push_back(cp);
        }
        i += len;
    }
    return out;
}

// Encodes code points as UTF-8. Invalid code points become U+FFFD.
inline std::string encode(const std::u32string& text) {
    std::string out;
    out.reserve(text.size() * 3);
    for (char32_t ch : text) {
        char32_t cp = ch;
        if (cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF)) {
            cp = 0xFFFD;
        }
        if (cp < 0x80) {
            out.push_back(static_cast<char>(cp));
        } else if (cp < 0x800) {
            out.push_back(static_cast<char>(0xC0 | (cp >> 6)));
            out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
        } else if (cp < 0x10000) {
            out.push_back(static_cast<char>(0xE0 | (cp >> 12)));
            out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
        } else {
            out.push_back(static_cast<char>(0xF0 | (cp >> 18)));
            out.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
        }
    }
    return out;
}

}  // namespace text_clean::utf8
