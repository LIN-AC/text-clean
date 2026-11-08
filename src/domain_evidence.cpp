#include "text_clean/domain_evidence.h"

#include <cmath>
#include <fstream>
#include <sstream>
#include <vector>

#include "text_clean/utf8.h"

namespace text_clean {
namespace {

std::vector<std::string> split_tabs(const std::string& line) {
    std::vector<std::string> out;
    std::string field;
    std::istringstream in(line);
    while (std::getline(in, field, '\t')) out.push_back(field);
    return out;
}

std::string trim_cr(std::string value) {
    while (!value.empty() && (value.back() == '\r' || value.back() == ' ')) value.pop_back();
    return value;
}

}  // namespace

bool DomainEvidence::load(const std::string& dir, std::string* error) {
    if (error != nullptr) error->clear();
    std::ifstream words(dir + "/words.tsv", std::ios::binary);   // 可选：纯上下文表没有这一项
    std::string line;
    while (words && std::getline(words, line)) {
        line = trim_cr(line);
        if (line.empty() || line.front() == '#') continue;
        const auto f = split_tabs(line);
        if (f.size() < 2 || f[0] == "text" || f[0] == "word") continue;
        try {
            zipfs_[utf8::decode(f[0])] = std::stod(f[1]);
        } catch (...) {
            if (error != nullptr) *error = "words.tsv 数值解析失败: " + line;
            return false;
        }
    }
    std::ifstream unis(dir + "/unis.tsv", std::ios::binary);
    if (unis) {
        while (std::getline(unis, line)) {
            line = trim_cr(line);
            if (line.empty() || line.front() == '#') continue;
            const auto f = split_tabs(line);
            if (f.size() < 2 || f[0] == "char") continue;
            const auto decoded = utf8::decode(f[0]);
            if (decoded.size() != 1) continue;
            try {
                unis_[decoded.front()] = std::stoull(f[1]);
            } catch (...) {
            }
        }
    }
    std::ifstream pairs(dir + "/pairs.tsv", std::ios::binary);
    if (pairs) {
        while (std::getline(pairs, line)) {
            line = trim_cr(line);
            if (line.empty() || line.front() == '#') continue;
            const auto f = split_tabs(line);
            if (f.size() < 3 || f[0] == "left") continue;
            const auto a = utf8::decode(f[0]), b = utf8::decode(f[1]);
            if (a.size() != 1 || b.size() != 1) continue;
            try {
                pairs_[pair_key(a.front(), b.front())] = std::stoull(f[2]);
            } catch (...) {
            }
        }
    }
    std::ifstream ngrams(dir + "/ngrams.tsv", std::ios::binary);
    if (ngrams) {
        while (std::getline(ngrams, line)) {
            line = trim_cr(line);
            if (line.empty() || line.front() == '#') continue;
            const auto f = split_tabs(line);
            if (f.size() < 2 || f[0] == "text") continue;
            std::uint64_t n = 0;
            try {
                n = std::stoull(f[1]);
            } catch (...) {
                continue;
            }
            const auto key = utf8::decode(f[0]);
            if (key.size() >= 1 && key.size() <= 8) ngrams_[key] = n;
        }
    }
    if (zipfs_.empty() && ngrams_.empty() && pairs_.empty()) {
        if (error != nullptr) *error = "证据目录里没有可用表: " + dir;
        return false;
    }
    return true;
}

std::optional<double> DomainEvidence::zipf(const std::u32string& text) const {
    const auto it = zipfs_.find(text);
    return it == zipfs_.end() ? std::nullopt : std::optional<double>(it->second);
}

std::optional<double> DomainEvidence::log_prob_next(char32_t prev, char32_t next) const {
    const auto base = unis_.find(prev);
    if (base == unis_.end() || base->second == 0) return std::nullopt;   // 邻字没出现过：弃权
    const auto pair = pairs_.find(pair_key(prev, next));
    const double hit = pair == pairs_.end() ? 0.0 : static_cast<double>(pair->second);
    return std::log((hit + 0.5) / (static_cast<double>(base->second) + 0.5));
}

std::optional<double> DomainEvidence::log_prob_follow(const std::u32string& anchor,
                                                      const std::u32string& follow) const {
    if (anchor.empty() || follow.empty()) return std::nullopt;
    const auto base = ngrams_.find(anchor);
    if (base == ngrams_.end() || base->second < min_anchor_count_) return std::nullopt;   // 支持不足：弃权
    std::u32string joined = anchor;
    joined += follow;
    const auto hit = ngrams_.find(joined);
    const double hits = hit == ngrams_.end() ? 0.0 : static_cast<double>(hit->second);
    return std::log((hits + 0.5) / (static_cast<double>(base->second) + 0.5));
}

}  // namespace text_clean
