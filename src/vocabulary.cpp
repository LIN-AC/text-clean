#include "text_clean/vocabulary.h"
#include "text_clean/utf8.h"
#include <filesystem>
#include <fstream>
#include <sstream>
namespace text_clean {
void Vocabulary::add(std::u32string word) {
    if (word.size() < 2) return;
    for (auto ch : word) if (!utf8::is_han(ch)) return;
    words_.insert(std::move(word));
}
bool Vocabulary::load_file(const std::string& path, std::string* error) {
    if (error) error->clear();
    std::ifstream in(std::filesystem::u8path(path), std::ios::binary);
    if (!in) { if (error) *error = "cannot open vocabulary: " + path; return false; }
    Vocabulary parsed;
    std::string line;
    while (std::getline(in, line)) {
        if (line.compare(0, 3, "\xEF\xBB\xBF") == 0) line.erase(0, 3);
        const auto start = line.find_first_not_of(" \t\r");
        if (start == std::string::npos || line[start] == '#') continue;
        const auto end = line.find_first_of(" \t\r", start);
        parsed.add(utf8::decode(line.substr(start, end - start)));
    }
    if (in.bad()) { if (error) *error = "cannot read vocabulary: " + path; return false; }
    *this = std::move(parsed);
    return true;
}
}
