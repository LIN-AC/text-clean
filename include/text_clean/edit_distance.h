#pragma once

#include <algorithm>
#include <cstddef>
#include <vector>

namespace text_clean {

// Unit-cost Levenshtein distance over any indexable sequence of comparable
// tokens (e.g. std::string, std::u32string, std::vector<std::string>).
template <typename Sequence>
std::size_t levenshtein(const Sequence& a, const Sequence& b) {
    const std::size_t n = a.size();
    const std::size_t m = b.size();
    if (n == 0) return m;
    if (m == 0) return n;

    std::vector<std::size_t> previous(m + 1);
    std::vector<std::size_t> current(m + 1);
    for (std::size_t j = 0; j <= m; ++j) previous[j] = j;

    for (std::size_t i = 1; i <= n; ++i) {
        current[0] = i;
        for (std::size_t j = 1; j <= m; ++j) {
            const std::size_t substitution =
                previous[j - 1] + (a[i - 1] == b[j - 1] ? 0 : 1);
            current[j] = std::min({previous[j] + 1, current[j - 1] + 1, substitution});
        }
        previous.swap(current);
    }
    return previous[m];
}

// Returns the distance when it is <= max_distance, otherwise max_distance + 1.
// Uses a banded DP and stops as soon as a full row exceeds the threshold.
template <typename Sequence>
std::size_t levenshtein_bounded(const Sequence& a, const Sequence& b,
                                std::size_t max_distance) {
    const std::size_t n = a.size();
    const std::size_t m = b.size();

    if (max_distance >= n && max_distance >= m) return levenshtein(a, b);

    // The length difference alone exceeds the threshold (overflow-safe form).
    if (n > m) {
        if (n - m > max_distance) return max_distance + 1;
    } else {
        if (m - n > max_distance) return max_distance + 1;
    }

    const std::size_t inf = max_distance + 1;
    std::vector<std::size_t> previous(m + 1, inf);
    std::vector<std::size_t> current(m + 1, inf);
    previous[0] = 0;
    for (std::size_t j = 1; j <= m && j <= max_distance; ++j) previous[j] = j;

    for (std::size_t i = 1; i <= n; ++i) {
        std::fill(current.begin(), current.end(), inf);
        const std::size_t lo = i > max_distance ? i - max_distance : 1;
        const std::size_t hi = std::min(m, i + max_distance);

        std::size_t row_min = inf;
        if (i <= max_distance) {
            current[0] = i;
            row_min = i;
        }

        for (std::size_t j = lo; j <= hi; ++j) {
            const std::size_t substitution =
                previous[j - 1] + (a[i - 1] == b[j - 1] ? 0 : 1);
            const std::size_t deletion = previous[j] + 1;
            const std::size_t insertion = current[j - 1] + 1;
            std::size_t value = std::min({substitution, deletion, insertion});
            if (value > inf) value = inf;
            current[j] = value;
            row_min = std::min(row_min, value);
        }

        if (row_min >= inf) return inf;
        previous.swap(current);
    }
    return std::min(previous[m], inf);
}

// Same as levenshtein_bounded(), but token equality is supplied by the
// caller. This allows weighted comparisons such as base+tone pinyin
// syllables without changing the DP.
template <typename Sequence, typename Equal>
std::size_t levenshtein_bounded_if(const Sequence& a, const Sequence& b,
                                   std::size_t max_distance, Equal equal) {
    const std::size_t n = a.size();
    const std::size_t m = b.size();

    if (max_distance >= n && max_distance >= m) {
        std::vector<std::size_t> previous(m + 1);
        std::vector<std::size_t> current(m + 1);
        for (std::size_t j = 0; j <= m; ++j) previous[j] = j;
        for (std::size_t i = 1; i <= n; ++i) {
            current[0] = i;
            for (std::size_t j = 1; j <= m; ++j) {
                const std::size_t substitution =
                    previous[j - 1] + (equal(a[i - 1], b[j - 1]) ? 0 : 1);
                current[j] =
                    std::min({previous[j] + 1, current[j - 1] + 1, substitution});
            }
            previous.swap(current);
        }
        return previous[m];
    }

    if (n > m) {
        if (n - m > max_distance) return max_distance + 1;
    } else {
        if (m - n > max_distance) return max_distance + 1;
    }

    const std::size_t inf = max_distance + 1;
    std::vector<std::size_t> previous(m + 1, inf);
    std::vector<std::size_t> current(m + 1, inf);
    previous[0] = 0;
    for (std::size_t j = 1; j <= m && j <= max_distance; ++j) previous[j] = j;

    for (std::size_t i = 1; i <= n; ++i) {
        std::fill(current.begin(), current.end(), inf);
        const std::size_t lo = i > max_distance ? i - max_distance : 1;
        const std::size_t hi = std::min(m, i + max_distance);

        std::size_t row_min = inf;
        if (i <= max_distance) {
            current[0] = i;
            row_min = i;
        }

        for (std::size_t j = lo; j <= hi; ++j) {
            const std::size_t substitution =
                previous[j - 1] + (equal(a[i - 1], b[j - 1]) ? 0 : 1);
            const std::size_t deletion = previous[j] + 1;
            const std::size_t insertion = current[j - 1] + 1;
            std::size_t value = std::min({substitution, deletion, insertion});
            if (value > inf) value = inf;
            current[j] = value;
            row_min = std::min(row_min, value);
        }

        if (row_min >= inf) return inf;
        previous.swap(current);
    }
    return std::min(previous[m], inf);
}

// Same as levenshtein_bounded(), but the caller supplies the substitution
// cost. Insertions and deletions still cost 1.
template <typename Sequence, typename Substitute>
std::size_t levenshtein_bounded_with(const Sequence& a, const Sequence& b,
                                     std::size_t max_distance,
                                     Substitute substitution_cost) {
    const std::size_t n = a.size();
    const std::size_t m = b.size();

    if (max_distance >= n && max_distance >= m) {
        std::vector<std::size_t> previous(m + 1);
        std::vector<std::size_t> current(m + 1);
        for (std::size_t j = 0; j <= m; ++j) previous[j] = j;
        for (std::size_t i = 1; i <= n; ++i) {
            current[0] = i;
            for (std::size_t j = 1; j <= m; ++j) {
                const std::size_t substitution =
                    previous[j - 1] + substitution_cost(a[i - 1], b[j - 1]);
                current[j] =
                    std::min({previous[j] + 1, current[j - 1] + 1, substitution});
            }
            previous.swap(current);
        }
        return previous[m];
    }

    if (n > m) {
        if (n - m > max_distance) return max_distance + 1;
    } else {
        if (m - n > max_distance) return max_distance + 1;
    }

    const std::size_t inf = max_distance + 1;
    std::vector<std::size_t> previous(m + 1, inf);
    std::vector<std::size_t> current(m + 1, inf);
    previous[0] = 0;
    for (std::size_t j = 1; j <= m && j <= max_distance; ++j) previous[j] = j;

    for (std::size_t i = 1; i <= n; ++i) {
        std::fill(current.begin(), current.end(), inf);
        const std::size_t lo = i > max_distance ? i - max_distance : 1;
        const std::size_t hi = std::min(m, i + max_distance);

        std::size_t row_min = inf;
        if (i <= max_distance) {
            current[0] = i;
            row_min = i;
        }

        for (std::size_t j = lo; j <= hi; ++j) {
            const std::size_t substitution =
                previous[j - 1] + substitution_cost(a[i - 1], b[j - 1]);
            const std::size_t deletion = previous[j] + 1;
            const std::size_t insertion = current[j - 1] + 1;
            std::size_t value = std::min({substitution, deletion, insertion});
            if (value > inf) value = inf;
            current[j] = value;
            row_min = std::min(row_min, value);
        }

        if (row_min >= inf) return inf;
        previous.swap(current);
    }
    return std::min(previous[m], inf);
}

}  // namespace text_clean
