#include "text_clean/word_review.h"

#include <algorithm>
#include <istream>
#include <ostream>
#include <string_view>
#include <unordered_map>

#include "text_clean/utf8.h"

namespace text_clean {
namespace {

bool review_section(SectionKind kind) {
    return kind == SectionKind::Title || kind == SectionKind::Intro;
}

std::string section_label(const Section& section) {
    if (!section.name.empty()) return section.name;
    return TextSplitter::kind_name(section.kind);
}

std::string trim_ascii(std::string_view value) {
    while (!value.empty() &&
           (value.front() == ' ' || value.front() == '\t' || value.front() == '\r')) {
        value.remove_prefix(1);
    }
    while (!value.empty() &&
           (value.back() == ' ' || value.back() == '\t' || value.back() == '\r')) {
        value.remove_suffix(1);
    }
    return std::string(value);
}

}  // namespace

std::vector<UnknownWord> WordReview::collect(const WordMaintainer& words,
                                             const std::vector<Section>& sections,
                                             std::size_t min_length) {
    std::vector<UnknownWord> result;
    std::unordered_map<std::u32string, std::size_t> index;

    for (const auto& section : sections) {
        if (!review_section(section.kind)) continue;

        const std::string label = section_label(section);
        const std::u32string text = utf8::decode(section.content);
        for (const auto& span : words.unknown_spans(text, min_length)) {
            const auto it = index.find(span.text);
            if (it == index.end()) {
                index.emplace(span.text, result.size());
                UnknownWord entry;
                entry.text = span.text;
                entry.count = 1;
                entry.sections.push_back(label);
                result.push_back(std::move(entry));
                continue;
            }

            UnknownWord& entry = result[it->second];
            ++entry.count;
            if (std::find(entry.sections.begin(), entry.sections.end(), label) ==
                entry.sections.end()) {
                entry.sections.push_back(label);
            }
        }
    }
    return result;
}

bool WordReview::run(WordMaintainer& words, const std::vector<Section>& sections,
                     const std::string& word_file, std::size_t min_length,
                     std::istream& input, std::ostream& output, std::string* error) {
    if (error != nullptr) error->clear();

    while (true) {
        const std::vector<UnknownWord> unknown = collect(words, sections, min_length);
        if (unknown.empty()) {
            output << "标题/简介词表已覆盖，无需维护。\n";
            return true;
        }

        output << "标题/简介中未收录词语: " << unknown.size() << " 个\n";
        for (const auto& word : unknown) {
            output << "  " << utf8::encode(word.text) << "（" << word.count
                   << " 次；";
            for (std::size_t i = 0; i < word.sections.size(); ++i) {
                if (i != 0) output << "、";
                output << word.sections[i];
            }
            output << "）\n";
        }

        output << "请输入要加入词表的词语（每行一个，空行结束）:\n";
        std::vector<std::string> lines;
        std::string line;
        while (std::getline(input, line)) {
            line = trim_ascii(line);
            if (line.empty()) break;
            if (line.front() == '#') continue;
            lines.push_back(std::move(line));
        }
        if (lines.empty()) {
            output << "未新增词语，继续使用当前词表。\n";
            return true;
        }

        std::size_t added = 0;
        if (!words.append_words_utf8(word_file, lines, &added, error)) {
            return false;
        }
        output << "已新增 " << added << " 个词语到 " << word_file << "\n";
        if (added == 0) {
            output << "没有新增词语（可能已存在）。\n";
        }
    }
}

}  // namespace text_clean