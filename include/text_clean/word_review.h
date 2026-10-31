#pragma once

#include <cstddef>
#include <iosfwd>
#include <string>
#include <vector>

#include "text_clean/text_split.h"
#include "text_clean/word_maintaining.h"

namespace text_clean {

struct UnknownWord {
    std::u32string text;
    std::size_t count = 0;
    std::vector<std::string> sections;  // "标题", "简介", ...
};

// Orchestrates word review for a sectioned document.
//
// Only Title and Intro sections are segmented. Body text (and any Other
// section) is never tokenized or reported as unknown.
class WordReview {
public:
    static std::vector<UnknownWord> collect(const WordMaintainer& words,
                                            const std::vector<Section>& sections,
                                            std::size_t min_length);

    // Prints unknown title/intro words, reads phrases from input until an empty
    // line, appends them to word_file, and repeats until the title/intro text
    // is covered or the user enters an empty batch.
    static bool run(WordMaintainer& words, const std::vector<Section>& sections,
                    const std::string& word_file, std::size_t min_length,
                    std::istream& input, std::ostream& output,
                    std::string* error = nullptr);
};

}  // namespace text_clean