#include "text_clean/dictionary_bundle.h"
#include "text_clean/utf8.h"
#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <functional>
#include <stdexcept>

namespace text_clean {
namespace {
using Fields = std::vector<std::string>;
Fields split(const std::string& s, char delimiter) {
    Fields out;
    std::size_t start=0;
    for (;;) {
        auto end=s.find(delimiter,start);
        out.push_back(s.substr(start,end==std::string::npos?end:end-start));
        if(end==std::string::npos) return out;
        start=end+1;
    }
}
void table(const std::filesystem::path& path, const Fields& header,
           const std::function<void(const Fields&)>& consume) {
    std::ifstream in(path, std::ios::binary);
    if(!in) throw std::runtime_error("cannot open "+path.u8string());
    std::string line; bool found=false; std::size_t n=0;
    while(std::getline(in,line)) {
        ++n;
        if(n==1 && line.compare(0,3,"\xef\xbb\xbf")==0) line.erase(0,3);
        if(!line.empty() && line.back()=='\r') line.pop_back();
        if(line.empty() || line.front()=='#') continue;
        auto fields=split(line,'\t');
        try {
            if(!found) { if(fields!=header) throw std::runtime_error("unexpected TSV header"); found=true; }
            else { if(fields.size()!=header.size()) throw std::runtime_error("unexpected column count"); consume(fields); }
        } catch(const std::exception& e) { throw std::runtime_error(path.u8string()+":"+std::to_string(n)+": "+e.what()); }
    }
    if(!found || in.bad()) throw std::runtime_error("incomplete TSV "+path.u8string());
}
// Only fully tone-bearing syllables are eligible; malformed/unknown word
// pronunciations remain unavailable, never silently become tone-0 matches.
std::vector<std::string> syllables(const std::string& text) {
    std::vector<std::string> result; std::string current;
    for(char c:text) {
        if(c>='a' && c<='z') current+=c;
        else if(c>='1' && c<='5' && !current.empty()) { current+=c; result.push_back(current); current.clear(); }
        else return {};
    }
    return current.empty()?result:std::vector<std::string>{};
}
using Pronunciations=std::vector<std::vector<std::string>>;
Pronunciations pronunciations(const std::string& text, std::size_t length) {
    Pronunciations result;
    for(const auto& variant:split(text,'|')) {
        auto value=syllables(variant);
        if(value.size()==length && std::find(result.begin(),result.end(),value)==result.end()) result.push_back(std::move(value));
    }
    return result;
}
}
bool DictionaryBundle::load(const std::string& directory, bool no_candidates,
                            DictionaryBundle& out, std::string* error) {
    if(error) error->clear();
    try {
        DictionaryBundle b; const auto root=std::filesystem::u8path(directory);
        table(root/"ac/ac_lock.tsv",{"word","group"},[&](const Fields& f){b.locks.add_word_utf8(f[0]);});
        // With no candidates, neither reading nor building the large reference
        // and frequency tables can affect output. Avoid that startup cost and
        // prevent any evaluation-derived evidence entering this baseline.
        if(no_candidates) { out=std::move(b); return true; }
        for(const auto* file:{"vocabulary/vocabulary.tsv","vocabulary/extvocabulary.tsv"})
            table(root/file,{"word","weight"},[&](const Fields& f){b.vocabulary.add(utf8::decode(f[0]));});
        table(root/"pronunciation/pronunciation_char.tsv",{"char","readings","sources","agreement","dropped"},[&](const Fields& f){
            auto ch=utf8::decode(f[0]); if(ch.size()!=1) throw std::runtime_error("expected one character");
            std::vector<std::string> valid;
            for(auto& reading:split(f[1],'|')) if(syllables(reading).size()==1) valid.push_back(reading);
            if(!valid.empty()) b.characters.add_char(ch.front(),std::move(valid));
        });
        std::unordered_map<std::u32string,Pronunciations> words;
        table(root/"pronunciation/pronunciation.tsv",{"entry","readings"},[&](const Fields& f){
            auto word=utf8::decode(f[0]); auto readings=pronunciations(f[1],word.size());
            if(!readings.empty()) words[word]=std::move(readings);
        });
        for(const auto* type:{"word","char"}) {
            auto& target=std::string(type)=="word"?b.word_frequency:b.char_frequency;
            table(root/(std::string("frequency/")+type+"_freq.tsv"),{type,"general","ours_count","ours_per_million","sources"},[&](const Fields& f){
                FrequencyEvidence e; e.source=f[4];
                // Never consume ours_count/ours_per_million, nor interpret a
                // SUBTLEX fallback integer as a Zipf value.
                if(f[4].find("wordfreq")!=std::string::npos) {
                    std::size_t used=0; const auto x=std::stod(f[1],&used);
                    if(used!=f[1].size() || !std::isfinite(x) || x<0 || x>10) throw std::runtime_error("invalid Zipf frequency");
                    if(x>0) e.zipf=x; // wordfreq default zero means unavailable, not a measured rarity
                }
                target.emplace(utf8::decode(f[0]),std::move(e));
            });
        }
        std::unordered_map<std::u32string,std::size_t> ids;
        std::vector<LexiconEntry> entries;
        if(!no_candidates) table(root/"correction/candidates.tsv",{"canonical","pinyin","alias","source","status"},[&](const Fields& f){
            if(f[4]!="0" && f[4]!="1") throw std::runtime_error("status must be 0 or 1");
            if(f[4]=="0") {++b.disabled_rows; return;}
            ++b.enabled_rows;
            auto word=utf8::decode(f[0]), alias=utf8::decode(f[2]);
            if(word.empty() || (!alias.empty() && word.size()!=alias.size())) throw std::runtime_error("enabled pair must have equal nonzero lengths");
            for(auto c:word+alias) if(!utf8::is_han(c)) throw std::runtime_error("enabled pair must be Han text");
            auto found=ids.find(word);
            if(found==ids.end()) {
                LexiconEntry e; e.canonical=word;
                auto pr=words.find(word);
                e.pronunciations=pr!=words.end()?pr->second:pronunciations(f[1],word.size());
                if(e.pronunciations.empty()) ++b.unknown_targets;
                else for(const auto& syl:e.pronunciations.front()) e.pinyin.push_back(PinyinDict::normalize_reading(syl));
                ids[word]=entries.size(); entries.push_back(std::move(e)); found=ids.find(word);
            }
            auto& e=entries[found->second];
            if(!alias.empty() && std::find(e.aliases.begin(),e.aliases.end(),alias)==e.aliases.end()) e.aliases.push_back(alias);
            e.sources.push_back(f[3]);
        });
        for(auto& e:entries) b.candidates.add_entry(std::move(e));
        out=std::move(b); return true;
    } catch(const std::exception& e) { if(error) *error=e.what(); return false; }
}
}
