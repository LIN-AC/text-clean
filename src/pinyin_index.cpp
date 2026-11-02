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
    Readings readings;
    for (const auto& base : entries_[id]) readings.push_back({base});
    readings_[id] = std::move(readings);
    built_ = false;
}

void PinyinInvertedIndex::build() {
    exact_.clear();
    postings_.clear();
    length_postings_.clear();

    std::vector<EntryId> ids;
    ids.reserve(entries_.size());
    for (const auto& entry : entries_) ids.push_back(entry.first);
    std::sort(ids.begin(), ids.end());

    for (const EntryId id : ids) {
        const auto& syllables = entries_.at(id);
        exact_[make_key(syllables)].push_back(id);

        std::unordered_set<std::string> alternatives;
        for (const auto& position : readings_.at(id))
            for (const auto& base : position)
                if (alternatives.insert(base).second) length_postings_[syllables.size()][base].push_back(id);
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

void PinyinInvertedIndex::add_readings(EntryId id, Readings readings) {
    std::vector<std::string> primary;
    for (auto& position : readings) {
        position = normalize_all(position);
        primary.push_back(position.empty() ? std::string{} : position.front());
    }
    add(id, std::move(primary));
    readings_[id] = std::move(readings);
}
std::vector<PinyinInvertedIndex::Candidate> PinyinInvertedIndex::find_aligned_candidates(
    const Readings& raw, std::size_t limit, bool require_first) const {
    require_built();
    if (raw.empty() || limit == 0) return {};
    const auto bucket = length_postings_.find(raw.size());
    if (bucket == length_postings_.end()) return {};
    Readings query;
    for (const auto& position : raw) query.push_back(normalize_all(position));
    std::unordered_set<EntryId> ids;
    for (const auto& position : query) for (const auto& base : position) {
        const auto it = bucket->second.find(base);
        if (it != bucket->second.end()) ids.insert(it->second.begin(), it->second.end());
    }
    std::vector<Candidate> result;
    for (auto id : ids) {
        const auto& target = readings_.at(id);
        std::size_t shared = 0;
        bool first = false;
        for (std::size_t k = 0; k < query.size(); ++k) {
            bool match = false;
            for (const auto& base : query[k])
                match = match || std::find(target[k].begin(), target[k].end(), base) != target[k].end();
            if (k == 0) first = match;
            shared += match;
        }
        if (shared && (!require_first || first)) result.push_back({id, shared});
    }
    std::sort(result.begin(), result.end(), [](const Candidate& a, const Candidate& b) {
        return a.shared_syllables != b.shared_syllables ? a.shared_syllables > b.shared_syllables : a.id < b.id;
    });
    if (result.size() > limit) result.resize(limit);
    return result;
}
}  // namespace text_clean
