#include "text_clean/video_context.h"
#include "text_clean/ac_automaton.h"
#include "text_clean/utf8.h"
#include <algorithm>
#include <cmath>
namespace text_clean {
VideoContext VideoContext::build(std::string_view title, std::string_view description,
                                std::string_view asr,
                                const std::vector<std::u32string>& vocabulary) {
    VideoContext result;
    AcAutomaton ac;
    for (const auto& word : vocabulary) {
        if (word.size() >= 2 && result.counts_.emplace(word, Counts{}).second)
            ac.add_pattern(word);
    }
    ac.build();
    auto collect = [&](std::string_view source, bool metadata) {
        for (const auto& hit : ac.find_non_overlapping(utf8::decode(source))) {
            auto& counts = result.counts_.at(std::u32string(ac.pattern(hit.pattern)));
            auto& count = metadata ? counts.metadata : counts.asr;
            count = std::min(3u, count + 1);
        }
    };
    collect(title, true);
    collect(description, true);
    collect(asr, false);
    return result;
}
double VideoContext::bonus(const std::u32string& word) const {
    const auto it = counts_.find(word);
    if (it == counts_.end() || it->second.metadata == 0) return 0;
    // Metadata at most doubles prior odds. ASR only corroborates metadata;
    // repeated errors alone cannot promote a term, and counts saturate.
    return std::log1p(std::min(2u, it->second.metadata) / 2.0) +
           std::log1p(it->second.asr / 12.0);
}
}
