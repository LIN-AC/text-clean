#include "text_clean/text_split.h"

#include <utility>

namespace text_clean {
namespace {

std::string_view trim_ascii(std::string_view value) {
    while (!value.empty() &&
           (value.front() == ' ' || value.front() == '\t' || value.front() == '\r')) {
        value.remove_prefix(1);
    }
    while (!value.empty() &&
           (value.back() == ' ' || value.back() == '\t' || value.back() == '\r')) {
        value.remove_suffix(1);
    }
    return value;
}

struct Marker {
    bool is_marker = false;
    SectionKind kind = SectionKind::Other;
    std::string name;
};

Marker parse_marker(std::string_view line) {
    line = trim_ascii(line);
    std::size_t left = 0;
    while (left < line.size() && line[left] == '=') ++left;
    if (left < 5) return {};

    std::size_t right = line.size();
    while (right > left && line[right - 1] == '=') --right;
    if (line.size() - right < 5) return {};

    const std::string_view name = trim_ascii(line.substr(left, right - left));
    if (name.empty()) return {};

    Marker marker;
    marker.is_marker = true;
    marker.name = std::string(name);
    if (name == "标题") {
        marker.kind = SectionKind::Title;
    } else if (name == "简介") {
        marker.kind = SectionKind::Intro;
    } else if (name == "正文") {
        marker.kind = SectionKind::Body;
    }
    return marker;
}

const char* default_marker_name(SectionKind kind) {
    switch (kind) {
        case SectionKind::Title:
            return "标题";
        case SectionKind::Intro:
            return "简介";
        case SectionKind::Body:
            return "正文";
        case SectionKind::Other:
            return nullptr;
    }
    return nullptr;
}

}  // namespace

const char* TextSplitter::kind_name(SectionKind kind) {
    switch (kind) {
        case SectionKind::Title:
            return "标题";
        case SectionKind::Intro:
            return "简介";
        case SectionKind::Body:
            return "正文";
        case SectionKind::Other:
            return "其他";
    }
    return "其他";
}

std::vector<Section> TextSplitter::split(std::string_view utf8_text) {
    std::vector<Section> sections;
    if (utf8_text.empty()) return sections;

    bool has_current = false;
    Section current;
    auto flush = [&]() {
        if (!has_current) return;
        sections.push_back(std::move(current));
        current = Section{};
        has_current = false;
    };

    std::size_t position = 0;
    while (position <= utf8_text.size()) {
        const std::size_t newline = utf8_text.find('\n', position);
        const std::size_t line_end =
            newline == std::string_view::npos ? utf8_text.size() : newline;
        std::string_view line = utf8_text.substr(position, line_end - position);
        if (!line.empty() && line.back() == '\r') line.remove_suffix(1);
        const bool has_newline = newline != std::string_view::npos;

        const Marker marker = parse_marker(line);
        if (marker.is_marker) {
            flush();
            current.kind = marker.kind;
            current.name = marker.name;
            has_current = true;
        } else {
            if (!has_current) {
                current = Section{};
                has_current = true;
            }
            current.content.append(line);
            if (has_newline) current.content.push_back('\n');
        }

        if (!has_newline) break;
        position = newline + 1;
    }
    flush();
    return sections;
}

std::string TextSplitter::join(const std::vector<Section>& sections) {
    std::string output;
    for (std::size_t i = 0; i < sections.size(); ++i) {
        const Section& section = sections[i];
        std::string marker = section.name;
        if (marker.empty()) {
            const char* fallback = default_marker_name(section.kind);
            if (fallback != nullptr) marker = fallback;
        }
        if (!marker.empty()) {
            output += "===== ";
            output += marker;
            output += " =====\n";
        }
        output += section.content;
        if (i + 1 < sections.size() && !output.empty() && output.back() != '\n') {
            output.push_back('\n');
        }
    }
    return output;
}

}  // namespace text_clean