#pragma once
#include <string_view>
#include <unordered_map>
#include <vector>
#include <string>
namespace text_clean {
// Per-video evidence, independent of static frequencies. Owns no source text.
class VideoContext {
public:
    static VideoContext build(std::string_view title, std::string_view description,
                              std::string_view asr,
                              const std::vector<std::u32string>& vocabulary);
    double bonus(const std::u32string& word) const;
private:
    struct Counts { unsigned metadata = 0; unsigned asr = 0; };
    std::unordered_map<std::u32string, Counts> counts_;
};
}
