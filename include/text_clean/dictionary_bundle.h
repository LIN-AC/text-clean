#pragma once
#include <optional>
#include <string>
#include <unordered_map>
#include "text_clean/lexicon.h"
#include "text_clean/pinyin_dict.h"
#include "text_clean/vocabulary.h"
#include "text_clean/word_maintaining.h"

namespace text_clean {
// These are evidence, NOT the integer counts consumed by the frozen scorer.
struct FrequencyEvidence {
    std::optional<double> zipf;
    std::string source;
};
struct DictionaryBundle {
    Lexicon candidates;
    PinyinDict characters;
    WordMaintainer locks;
    Vocabulary vocabulary;
    std::unordered_map<std::u32string, FrequencyEvidence> word_frequency, char_frequency;
    std::size_t enabled_rows = 0, disabled_rows = 0, unknown_targets = 0;
    // Transactional loading. no_candidates does not read the candidate file.
    // Domain counts are deliberately not imported: they contain evaluation truth.
    static bool load(const std::string& directory, bool no_candidates,
                     DictionaryBundle& out, std::string* error);
};
}
