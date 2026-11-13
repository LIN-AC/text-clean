#pragma once
#include <cstddef>
#include <memory>
#include <string>
#include <vector>

namespace text_clean {
struct EvidenceSegment {
    long long id = 0, off = 0;
    std::string cluster, text, left, left_class, right_class, family, source_doc;
    bool bos = false, eos = false;
};
struct RetrievalResult {
    std::vector<EvidenceSegment> segments;
    std::size_t characters = 0;
    bool truncated = false;
};
// Read-only tc-rag-2 retrieval. Scores here select evidence, never authorize edits.
class Retriever {
public:
    explicit Retriever(const std::string& database);
    ~Retriever();
    Retriever(const Retriever&) = delete;
    Retriever& operator=(const Retriever&) = delete;
    RetrievalResult retrieve(const std::string& context,
                             const std::vector<std::string>& alternatives,
                             std::size_t limit = 300, std::size_t budget = 8192,
                             bool legacy = false);
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace text_clean
