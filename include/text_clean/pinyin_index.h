#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

namespace text_clean {

// Inverted index from pinyin syllable sequences to entry ids.
//
// Two lookups are provided:
//   * find_exact()      full syllable sequence match (homophones included)
//   * find_candidates() entries sharing at least one syllable with the query,
//                       ordered by the number of shared distinct syllables.
//
// Syllables are normalized to ASCII lowercase. Duplicate syllables inside one
// entry or query are counted once for candidate scoring. build() must be
// called after adding entries; queries throw std::logic_error otherwise.
class PinyinInvertedIndex {
public:
    using EntryId = std::uint32_t;
    static constexpr EntryId kInvalidEntry = static_cast<EntryId>(-1);

    struct Candidate {
        EntryId id;
        std::size_t shared_syllables;
    };

    void add(EntryId id, std::vector<std::string> syllables);
    using Readings = std::vector<std::vector<std::string>>;
    void add_readings(EntryId id, Readings readings);
    // Length bucket + positional shared bases, with all polyphone readings.
    std::vector<Candidate> find_aligned_candidates(const Readings& query,
        std::size_t limit = 64, bool require_first = true) const;
    void build();

    bool empty() const { return entries_.empty(); }
    bool is_built() const { return built_; }
    std::size_t size() const { return entries_.size(); }
    std::size_t syllable_count(EntryId id) const;

    std::vector<EntryId> find_exact(const std::vector<std::string>& syllables) const;

    std::vector<Candidate> find_candidates(const std::vector<std::string>& syllables,
                                           std::size_t max_candidates = 64) const;

private:
    void require_built() const;
    static std::string make_key(const std::vector<std::string>& syllables);

    std::unordered_map<EntryId, std::vector<std::string>> entries_;
    std::unordered_map<std::string, std::vector<EntryId>> exact_;
    std::unordered_map<std::string, std::vector<EntryId>> postings_;
    std::unordered_map<EntryId, Readings> readings_;
    std::unordered_map<std::size_t, std::unordered_map<std::string, std::vector<EntryId>>> length_postings_;
    bool built_ = false;
};

}  // namespace text_clean
