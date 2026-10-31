#include "test_framework.h"

#include <stdexcept>
#include <string>
#include <vector>

#include "text_clean/pinyin_index.h"

namespace {

using text_clean::PinyinInvertedIndex;

std::vector<std::string> P(std::initializer_list<const char*> syllables) {
    return std::vector<std::string>(syllables.begin(), syllables.end());
}

void test_exact_lookup() {
    PinyinInvertedIndex index;
    index.add(0, P({"wei", "xin"}));
    index.add(1, P({"wei", "xin"}));
    index.add(2, P({"zhi", "fu", "bao"}));
    index.add(3, P({"wei", "xing"}));
    index.add(4, P({"xin"}));
    index.add(5, P({"Wei", "Xin"}));
    index.build();

    CHECK_EQ(index.size(), std::size_t{6});
    CHECK_EQ(index.find_exact(P({"wei", "xin"})),
             std::vector<PinyinInvertedIndex::EntryId>({0, 1, 5}));
    CHECK_EQ(index.find_exact(P({"Wei", "Xin"})),
             std::vector<PinyinInvertedIndex::EntryId>({0, 1, 5}));
    CHECK_EQ(index.find_exact(P({"wei", "xing"})),
             std::vector<PinyinInvertedIndex::EntryId>({3}));
    CHECK_EQ(index.find_exact(P({"xin"})),
             std::vector<PinyinInvertedIndex::EntryId>({4}));
    CHECK(index.find_exact(P({"xin", "xin"})).empty());
    CHECK(index.find_exact(P({"mei", "you"})).empty());
}

void test_candidates() {
    PinyinInvertedIndex index;
    index.add(0, P({"wei", "xin"}));
    index.add(1, P({"wei", "xin"}));
    index.add(2, P({"zhi", "fu", "bao"}));
    index.add(3, P({"wei", "xing"}));
    index.add(4, P({"xin"}));
    index.add(5, P({"Wei", "Xin"}));
    index.build();

    const auto candidates = index.find_candidates(P({"wei", "xing"}));
    CHECK_EQ(candidates.size(), std::size_t{4});
    CHECK_EQ(candidates[0].id, PinyinInvertedIndex::EntryId{3});
    CHECK_EQ(candidates[0].shared_syllables, std::size_t{2});
    CHECK_EQ(candidates[1].id, PinyinInvertedIndex::EntryId{0});
    CHECK_EQ(candidates[1].shared_syllables, std::size_t{1});
    CHECK_EQ(candidates[2].id, PinyinInvertedIndex::EntryId{1});
    CHECK_EQ(candidates[3].id, PinyinInvertedIndex::EntryId{5});

    const auto limited = index.find_candidates(P({"wei", "xing"}), 2);
    CHECK_EQ(limited.size(), std::size_t{2});
    CHECK_EQ(limited[0].id, PinyinInvertedIndex::EntryId{3});
}

void test_duplicate_syllables() {
    PinyinInvertedIndex index;
    index.add(7, P({"xin", "xin"}));
    index.add(8, P({"xin"}));
    index.build();

    const auto candidates = index.find_candidates(P({"xin", "xin"}));
    CHECK_EQ(candidates.size(), std::size_t{2});
    CHECK_EQ(candidates[0].id, PinyinInvertedIndex::EntryId{7});
    CHECK_EQ(candidates[0].shared_syllables, std::size_t{1});
    CHECK_EQ(candidates[1].id, PinyinInvertedIndex::EntryId{8});
}

void test_syllable_count() {
    PinyinInvertedIndex index;
    index.add(2, P({"zhi", "fu", "bao"}));
    CHECK_EQ(index.syllable_count(2), std::size_t{3});
    CHECK_EQ(index.syllable_count(99), std::size_t{0});
    CHECK(!index.empty());
    index.build();
    CHECK_EQ(index.syllable_count(2), std::size_t{3});
}

void test_rebuild_and_replace() {
    PinyinInvertedIndex index;
    index.add(0, P({"a", "b"}));
    index.build();
    CHECK_EQ(index.find_exact(P({"a", "b"})).size(), std::size_t{1});

    index.add(0, P({"c", "d"}));
    CHECK(!index.is_built());
    index.build();
    CHECK(index.find_exact(P({"a", "b"})).empty());
    CHECK_EQ(index.find_exact(P({"c", "d"})),
             std::vector<PinyinInvertedIndex::EntryId>({0}));
}

void test_requires_build() {
    PinyinInvertedIndex index;
    index.add(0, P({"wei", "xin"}));
    bool threw = false;
    try {
        index.find_exact(P({"wei", "xin"}));
    } catch (const std::logic_error&) {
        threw = true;
    }
    CHECK(threw);
}

void test_empty_inputs() {
    PinyinInvertedIndex index;
    index.build();
    CHECK(index.find_exact({}).empty());
    CHECK(index.find_candidates({}).empty());
    CHECK(index.find_candidates(P({"wei"}), 0).empty());
}

void test_key_separator() {
    PinyinInvertedIndex index;
    index.add(0, P({"a", "b"}));
    index.add(1, P({"a b"}));
    index.build();
    CHECK_EQ(index.find_exact(P({"a", "b"})),
             std::vector<PinyinInvertedIndex::EntryId>({0}));
    CHECK_EQ(index.find_exact(P({"a b"})),
             std::vector<PinyinInvertedIndex::EntryId>({1}));
}

}  // namespace

int main() {
    test_exact_lookup();
    test_candidates();
    test_duplicate_syllables();
    test_syllable_count();
    test_rebuild_and_replace();
    test_requires_build();
    test_empty_inputs();
    test_key_separator();
    return test::finish("test_pinyin_index");
}
