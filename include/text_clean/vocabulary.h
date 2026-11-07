#pragma once
#include <string>
#include <string_view>
#include <unordered_set>
namespace text_clean {
// Word membership for segmentation/reference; never a frequency or AC action.
// Accepts one word per line, or jieba word/frequency/tag rows. Counts ignored.
class Vocabulary {
public:
    bool load_file(const std::string& path, std::string* error = nullptr);
    void add(std::u32string word);
    bool contains(const std::u32string& word) const { return words_.count(word) != 0; }
    std::size_t size() const { return words_.size(); }
    const std::unordered_set<std::u32string>& words() const { return words_; }
private:
    std::unordered_set<std::u32string> words_;
};
}
