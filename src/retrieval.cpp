#include "text_clean/retrieval.h"
#include "text_clean/utf8.h"
#include <sqlite3.h>
#include <algorithm>
#include <cmath>
#include <map>
#include <set>
#include <stdexcept>
#include <utility>

namespace text_clean {
namespace {
struct Statement {
    sqlite3_stmt* p = nullptr;
    Statement(sqlite3* db, const std::string& sql) {
        if (sqlite3_prepare_v2(db, sql.c_str(), -1, &p, nullptr) != SQLITE_OK)
            throw std::runtime_error(sqlite3_errmsg(db));
    }
    ~Statement() { sqlite3_finalize(p); }
    void bind(int i, const std::string& v) {
        if (sqlite3_bind_text(p, i, v.c_str(), -1, SQLITE_TRANSIENT) != SQLITE_OK)
            throw std::runtime_error("cannot bind retrieval query");
    }
    bool next() {
        int rc = sqlite3_step(p);
        if (rc == SQLITE_ROW) return true;
        if (rc == SQLITE_DONE) return false;
        throw std::runtime_error(sqlite3_errmsg(sqlite3_db_handle(p)));
    }
    std::string str(int i) const {
        auto s = sqlite3_column_text(p, i);
        return s ? reinterpret_cast<const char*>(s) : "";
    }
};
bool han(char32_t c) { return c >= 0x4e00 && c <= 0x9fff; }
std::set<std::string> bigrams(const std::string& text) {
    const auto s = utf8::decode(text); std::set<std::string> out;
    for (std::size_t i = 1; i < s.size(); ++i)
        if (han(s[i-1]) && han(s[i])) out.insert(utf8::encode(s.substr(i-1, 2)));
    return out;
}
std::string expression(const std::vector<std::string>& terms, const char* op) {
    std::string s;
    for (const auto& term : terms) { if (!s.empty()) s += op; s += '"' + term + '"'; }
    return s;
}
} // namespace

struct Retriever::Impl {
    sqlite3* db = nullptr;
    std::map<std::string, long long> df_cache;
    explicit Impl(const std::string& path) {
        if (sqlite3_open_v2(path.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
            const std::string error = db ? sqlite3_errmsg(db) : "cannot open evidence database";
            if (db) sqlite3_close(db);
            db = nullptr; throw std::runtime_error(error);
        }
        try {
            Statement s(db, "select value from meta where key='format'");
            if (!s.next() || s.str(0) != "tc-rag-2") throw std::runtime_error("native retrieval requires tc-rag-2");
        } catch (...) { sqlite3_close(db); db = nullptr; throw; }
    }
    ~Impl() { if (db) sqlite3_close(db); }
    long long df(const std::string& term) {
        const auto it = df_cache.find(term); if (it != df_cache.end()) return it->second;
        Statement s(db, "select docs from term_docs where term=?"); s.bind(1, term);
        const auto count = s.next() ? sqlite3_column_int64(s.p, 0) : 0;
        if (df_cache.size() >= 10000) df_cache.clear();
        df_cache[term] = count; return count;
    }
    std::vector<EvidenceSegment> search(const std::string& query, std::size_t limit,
                                         const std::string& exact = "") {
        if (query.empty()) return {};
        // Exact words are checked in the contiguous segment plus its real prefix.
        // FTS stores bigrams: AND alone would also match non-contiguous characters.
        Statement s(db, "select s.id,s.cluster_id,s.text,s.off,s.left_context,s.bos,s.eos,"
            "s.left_class,s.right_class,d.source_family,d.source_doc_id "
            "from search join segments s on s.id=search.rowid "
            "join documents d on d.cluster_id=s.cluster_id where search match ? "
            "and (?='' or instr(s.left_context||s.text,?)>0) "
            "order by bm25(search),search.rowid limit ?");
        s.bind(1, query); s.bind(2, exact); s.bind(3, exact);
        sqlite3_bind_int64(s.p, 4, static_cast<sqlite3_int64>(limit));
        std::vector<EvidenceSegment> out;
        while (s.next()) {
            EvidenceSegment e;
            e.id = sqlite3_column_int64(s.p, 0); e.cluster = s.str(1); e.text = s.str(2);
            e.off = sqlite3_column_int64(s.p, 3); e.left = s.str(4);
            e.bos = sqlite3_column_int(s.p, 5) != 0; e.eos = sqlite3_column_int(s.p, 6) != 0;
            e.left_class = s.str(7); e.right_class = s.str(8); e.family = s.str(9); e.source_doc = s.str(10);
            if (utf8::decode(e.text).size() > 256 || utf8::decode(e.left).size() > 3)
                throw std::runtime_error("oversized evidence block");
            out.push_back(std::move(e));
        }
        return out;
    }
};
Retriever::Retriever(const std::string& path) : impl_(new Impl(path)) {}
Retriever::~Retriever() = default;

RetrievalResult Retriever::retrieve(const std::string& context,
        const std::vector<std::string>& alternatives, std::size_t limit,
        std::size_t budget, bool legacy) {
    if (!limit || limit > 3000 || !budget || budget > 8192 || alternatives.size() > 16)
        throw std::invalid_argument("retrieval budget out of range");
    auto ts = bigrams(context); std::vector<std::string> terms(ts.begin(), ts.end());
    std::vector<std::vector<EvidenceSegment>> streams;
    if (!legacy) {
        // A short local query instead of hundreds of topic-wide OR terms.
        std::vector<std::pair<long long, std::string>> ranked;
        for (const auto& t : terms) { auto df = impl_->df(t); if (df) ranked.emplace_back(df, t); }
        std::sort(ranked.begin(), ranked.end()); terms.clear();
        for (std::size_t i = 0; i < std::min<std::size_t>(8, ranked.size()); ++i) terms.push_back(ranked[i].second);
    }
    streams.push_back(impl_->search(expression(terms, " OR "), limit));
    if (!legacy) {
        const std::set<std::string> words(alternatives.begin(), alternatives.end());
        for (const auto& word : words) {
            auto gs = bigrams(word);
            const auto length = utf8::decode(word).size();
            if (length < 2 || length > 4 || gs.empty()) throw std::invalid_argument("alternative must be 2-4 Han characters");
            const auto decoded = utf8::decode(word);
            if (!std::all_of(decoded.begin(), decoded.end(), han)) throw std::invalid_argument("non-Han alternative");
            auto rows = impl_->search(expression({gs.begin(), gs.end()}, " AND "), limit, word);
            // Only retrieval ordering uses local context overlap. It never enters S.
            auto support = [&](const EvidenceSegment& e) {
                double value = 0; auto text = e.left + e.text;
                for (const auto& t : terms) if (word.find(t) == std::string::npos && text.find(t) != std::string::npos)
                    value += 1. / std::log(2. + static_cast<double>(impl_->df(t)));
                return value;
            };
            std::vector<std::pair<double, std::size_t>> order;
            for (std::size_t i=0; i<rows.size(); ++i) order.emplace_back(-support(rows[i]), i);
            std::sort(order.begin(), order.end()); std::vector<EvidenceSegment> sorted;
            for (const auto& item : order) sorted.push_back(std::move(rows[item.second]));
            streams.push_back(std::move(sorted));
        }
    }
    // Interleave all branches, including KEEP's branch. A frequent word cannot
    // consume the entire payload before another alternative gets a document.
    RetrievalResult result; std::set<long long> seen;
    for (std::size_t row=0; row<limit && result.segments.size()<limit; ++row) {
        bool found = false;
        for (auto& stream : streams) {
            if (row >= stream.size()) continue;
            found = true; auto e = stream[row]; if (!seen.insert(e.id).second) continue;
            auto text = utf8::decode(e.text); const auto prefix = utf8::decode(e.left).size();
            const auto remaining = budget-result.characters;
            if (remaining <= prefix) { result.truncated=true; return result; }
            if (text.size() > remaining-prefix) {
                text.resize(remaining-prefix); e.text=utf8::encode(text);
                e.eos=false; e.right_class="载荷截断"; result.truncated=true;
            }
            result.characters += prefix+text.size(); result.segments.push_back(std::move(e));
            if (result.characters == budget) { result.truncated=true; return result; }
            if (result.segments.size() == limit) break;
        }
        if (!found) break;
    }
    return result;
}
} // namespace text_clean
