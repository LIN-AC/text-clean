#pragma once

#include <string>
#include <string_view>
#include <vector>

namespace text_clean {

enum class SectionKind {
    Title,
    Intro,
    Body,
    Other,
};

struct Section {
    SectionKind kind = SectionKind::Other;
    std::string name;     // marker name from the input; empty when unsectioned
    std::string content;  // UTF-8 text between markers, marker lines excluded
};

// Parses documents shaped like:
//
//   ===== 标题 =====
//   ...
//   ===== 简介 =====
//   ...
//   ===== 正文 =====
//   ...
//
// Marker lines need at least five '=' on each side. Text before the first
// marker becomes an Other section. Unrecognized marker names are kept as
// Other sections with their original name. join() reconstructs the document
// with normalized line endings.
class TextSplitter {
public:
    static std::vector<Section> split(std::string_view utf8_text);
    static std::string join(const std::vector<Section>& sections);
    static const char* kind_name(SectionKind kind);
};

}  // namespace text_clean