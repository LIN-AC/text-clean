#include "text_clean/pinyin_index.h"

#include <algorithm>
#include <cctype>
#include <stdexcept>
#include <unordered_set>

namespace text_clean {
namespace {

std::string normalize(std::string syllable) {
    for (char& ch : syllable) {
        const auto byte = static_cast<unsigned char>(ch);
        if (byte >= 'A' && byte <= 'Z') ch = static_cast<char>(byte - 'A' + 'a');
    }
    return syllable;
}

std::vector<std::string> normalize_all(const std::vector<std::string>& syllables) {
    std::vector<std::string> out;
    out.reserve(syllables.size());
    for (const auto& syllable : syllables) out.push_back(normalize(syllable));
    return out;
}

}  // namespace

void PinyinInvertedIndex::add(EntryId id, std::vector<std::string> syllables) {
    entries_[id] = normalize_all(syllables);
    built_ = false;
}

void PinyinInvertedIndex::build() {
    exact_.clear();
    postings_.clear();

    std::vector<EntryId> ids;
    ids.reserve(entries_.size());
    for (const auto& entry : entries_) ids.push_back(entry.first);
    std::sort(ids.begin(), ids.end());

    for (const EntryId id : ids) {
        const auto& syllables = entries_.at(id);
        exact_[make_key(syllables)].push_back(id);

        std::unordered_set<std::string> seen;
        seen.reserve(syllables.size());
        for (const auto& syllable : syllables) {
            if (seen.insert(syllable).second) postings_[syllable].push_back(id);
        }
    }
    built_ = true;
}

void PinyinInvertedIndex::require_built() const {
    if (!built_) {
        throw std::logic_error(
            "PinyinInvertedIndex::build() must be called before querying");
    }
}

std::size_t PinyinInvertedIndex::syllable_count(EntryId id) const {
    const auto it = entries_.find(id);
    return it == entries_.end() ? 0 : it->second.size();
}

std::string PinyinInvertedIndex::make_key(const std::vector<std::string>& syllables) {
    std::string key;
    for (const auto& syllable : syllables) {
        if (!key.empty()) key.push_back('\x1F');
        key += syllable;
    }
    return key;
}

std::vector<PinyinInvertedIndex::EntryId> PinyinInvertedIndex::find_exact(
    const std::vector<std::string>& syllables) const {
    require_built();
    const auto it = exact_.find(make_key(normalize_all(syllables)));
    if (it == exact_.end()) return {};
    return it->second;
}

std::vector<PinyinInvertedIndex::Candidate> PinyinInvertedIndex::find_candidates(
    const std::vector<std::string>& syllables, std::size_t max_candidates) const {
    require_built();
    if (syllables.empty() || max_candidates == 0) return {};

    std::unordered_map<EntryId, std::size_t> shared;
    std::unordered_set<std::string> seen;
    seen.reserve(syllables.size());

    for (const auto& raw : syllables) {
        const std::string syllable = normalize(raw);
        if (!seen.insert(syllable).second) continue;
        const auto postings = postings_.find(syllable);
        if (postings == postings_.end()) continue;
        for (const EntryId id : postings->second) ++shared[id];
    }

    std::vector<Candidate> candidates;
    candidates.reserve(shared.size());
    for (const auto& item : shared) {
        candidates.push_back(Candidate{item.first, item.second});
    }
    std::sort(candidates.begin(), candidates.end(),
              [](const Candidate& a, const Candidate& b) {
                  if (a.shared_syllables != b.shared_syllables) {
                      return a.shared_syllables > b.shared_syllables;
                  }
                  return a.id < b.id;
              });
    if (candidates.size() > max_candidates) candidates.resize(max_candidates);
    return candidates;
}

}  // namespace text_clean
