#include "text_clean/pinyin_index.h"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <map>
#include <iterator>
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


namespace {
void put32(std::string& out, std::uint32_t x) {for(int i=0;i<4;++i) out.push_back(static_cast<char>((x>>(8*i))&255));}
void putstr(std::string& out,const std::string& x) {put32(out,static_cast<std::uint32_t>(x.size()));out+=x;}
struct BinReader {
    const std::string& bytes;std::size_t pos=0;
    std::uint32_t number(){if(bytes.size()-pos<4)throw std::runtime_error("truncated cache");std::uint32_t n=0;for(int i=0;i<4;++i)n|=static_cast<std::uint32_t>(static_cast<unsigned char>(bytes[pos++]))<<(8*i);return n;}
    std::string string(){auto n=number();if(n>bytes.size()-pos)throw std::runtime_error("invalid cache string");auto r=bytes.substr(pos,n);pos+=n;return r;}
};
std::uint32_t checksum(const std::string& s){std::uint32_t h=2166136261u;for(unsigned char c:s){h^=c;h*=16777619u;}return h;}
}
bool PinyinInvertedIndex::build_cached(const std::string& path,const std::string& identity) {
    if(path.empty()){build();return false;}
    std::string key="TC_INDEX_V1";putstr(key,identity);
    std::map<EntryId,Readings> ordered(readings_.begin(),readings_.end());
    for(const auto& item:ordered){put32(key,item.first);put32(key,item.second.size());for(const auto& rs:item.second){put32(key,rs.size());for(const auto& r:rs)putstr(key,r);}}
    using Posts=std::unordered_map<std::string,std::vector<EntryId>>;
    auto encode=[](std::string& out,const Posts& posts){
        std::map<std::string,std::vector<EntryId>> sorted(posts.begin(),posts.end());put32(out,sorted.size());
        for(const auto& item:sorted){putstr(out,item.first);put32(out,item.second.size());for(auto id:item.second)put32(out,id);}
    };
    auto decode=[&](BinReader& in){
        Posts posts;auto count=in.number();if(count>in.bytes.size()/8)throw std::runtime_error("invalid cache count");
        for(std::uint32_t i=0;i<count;++i){auto k=in.string();auto n=in.number();if(n>in.bytes.size()/4)throw std::runtime_error("invalid posting count");std::vector<EntryId> ids;
            for(std::uint32_t j=0;j<n;++j){auto id=in.number();if(!entries_.count(id))throw std::runtime_error("invalid cache id");ids.push_back(id);}if(!posts.emplace(k,std::move(ids)).second)throw std::runtime_error("duplicate cache key");}
        return posts;
    };
    try {
        const auto file=std::filesystem::u8path(path);
        if(std::filesystem::file_size(file)<=64*1024*1024) {
            std::ifstream input(file,std::ios::binary);std::string bytes((std::istreambuf_iterator<char>(input)),{});BinReader r{bytes};
            if(r.string()==key) {
                auto digest=r.number();auto payload=r.string();
                if(r.pos==bytes.size() && checksum(payload)==digest) {
                    BinReader p{payload};auto ex=decode(p),po=decode(p);decltype(length_postings_) lengths;
                    auto n=p.number();if(n>entries_.size())throw std::runtime_error("invalid bucket count");
                    for(std::uint32_t i=0;i<n;++i){auto length=p.number();auto posts=decode(p);for(const auto& item:posts)for(auto id:item.second)if(syllable_count(id)!=length)throw std::runtime_error("wrong length bucket");if(!lengths.emplace(length,std::move(posts)).second)throw std::runtime_error("duplicate length");}
                    if(p.pos!=payload.size())throw std::runtime_error("trailing cache payload");
                    exact_=std::move(ex);postings_=std::move(po);length_postings_=std::move(lengths);built_=true;return true;
                }
            }
        }
    } catch(const std::exception&) { /* cache is disposable; source remains authoritative */ }
    build();
    std::string payload;encode(payload,exact_);encode(payload,postings_);
    std::map<std::size_t,Posts> lengths(length_postings_.begin(),length_postings_.end());put32(payload,lengths.size());
    for(const auto& bucket:lengths){put32(payload,bucket.first);encode(payload,bucket.second);}
    std::string bytes;putstr(bytes,key);put32(bytes,checksum(payload));putstr(bytes,payload);
    // Best effort. A partial/concurrent write fails checksum and rebuilds next time.
    std::ofstream output(std::filesystem::u8path(path),std::ios::binary|std::ios::trunc);
    if(output)output.write(bytes.data(),static_cast<std::streamsize>(bytes.size()));
    return false;
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
