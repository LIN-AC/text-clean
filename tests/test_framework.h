#pragma once

#include <iostream>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

#include "text_clean/utf8.h"

namespace test {

inline int g_checks = 0;
inline int g_failures = 0;

inline std::string describe(const std::u32string& value) {
    return text_clean::utf8::encode(value);
}

inline std::string describe(std::u32string_view value) {
    return text_clean::utf8::encode(std::u32string(value));
}

template <typename T>
std::string describe(const T& value) {
    std::ostringstream os;
    os << value;
    return os.str();
}

template <typename T>
std::string describe(const std::vector<T>& values) {
    std::string out = "[";
    for (std::size_t i = 0; i < values.size(); ++i) {
        if (i != 0) out += ", ";
        out += describe(values[i]);
    }
    out += "]";
    return out;
}

inline void check(bool ok, const char* expr, const char* file, int line,
                  const std::string& detail = {}) {
    ++g_checks;
    if (ok) return;
    ++g_failures;
    std::cerr << file << ":" << line << ": CHECK failed: " << expr;
    if (!detail.empty()) std::cerr << " (" << detail << ")";
    std::cerr << "\n";
}

inline int finish(const char* suite) {
    if (g_failures == 0) {
        std::cout << suite << ": OK (" << g_checks << " checks)\n";
        return 0;
    }
    std::cerr << suite << ": " << g_failures << " of " << g_checks << " checks failed\n";
    return 1;
}

}  // namespace test

#define CHECK(expr) ::test::check(static_cast<bool>(expr), #expr, __FILE__, __LINE__)

#define CHECK_EQ(actual, expected)                                                   \
    do {                                                                             \
        const auto tc_actual = (actual);                                             \
        const auto tc_expected = (expected);                                         \
        ::test::check(tc_actual == tc_expected, #actual " == " #expected, __FILE__,   \
                      __LINE__,                                                      \
                      "expected " + ::test::describe(tc_expected) + ", got " +       \
                          ::test::describe(tc_actual));                              \
    } while (false)
