#include "text_clean/dictionary_bundle.h"
#include "text_clean/pinyin_index.h"
#include "text_clean/edit_distance.h"
#include "text_clean/utf8.h"
#include <iostream>
#include <fstream>
#include <map>
using namespace text_clean;
int main(int argc,char**argv){
 if(argc!=3)return 2;
 DictionaryBundle b;std::string err;if(!DictionaryBundle::load("data",false,b,&err)){std::cerr<<err;return 2;}
 using Seq=std::vector<PinyinDict::TonedSyllable>;
 std::map<unsigned,std::vector<Seq>> variants;PinyinInvertedIndex ix;
 for(const auto&e:b.candidates.entries()){
  if(e.action!=Action::Replace||e.pronunciations.empty())continue;
  PinyinInvertedIndex::Readings bases(e.canonical.size());
  for(const auto&p:e.pronunciations){
   PinyinDict d;for(std::size_t k=0;k<p.size();++k)d.add_char(static_cast<char32_t>(0xE000+k),{p[k]});
   std::u32string keys;for(std::size_t k=0;k<p.size();++k)keys+=static_cast<char32_t>(0xE000+k);
   auto seq=d.to_toned_syllables(keys);variants[e.id].push_back(seq);
   for(std::size_t k=0;k<seq.size();++k)for(const auto&r:seq[k].readings)bases[k].push_back(r.base);
  }ix.add_readings(e.id,bases);
 }ix.build();
 std::ifstream input(argv[1]);std::ofstream out(argv[2]);out<<"site\ttarget\thard\tdistance\n";
 std::string line;unsigned site=0;
 while(std::getline(input,line)){
  auto original=utf8::decode(line);auto toned=b.characters.to_toned_syllables(original);
  PinyinInvertedIndex::Readings q;for(const auto&s:toned){q.emplace_back();for(const auto&r:s.readings)q.back().push_back(r.base);}
  for(const auto&c:ix.find_aligned_candidates(q,64,true)){
   unsigned best=999;bool hard=false;
   for(const auto&seq:variants[c.id]){
    bool near=true;for(std::size_t k=0;k<seq.size();++k){bool yes=false;
     for(const auto&a:toned[k].readings)for(const auto&z:seq[k].readings)yes|=levenshtein_bounded(a.base,z.base,1)<=1;
     near&=yes;
    }if(near){hard=true;best=std::min(best,static_cast<unsigned>(PinyinDict::aligned_distance(toned,seq,100)));}
   }
   out<<site<<'\t'<<utf8::encode(b.candidates.entries()[c.id].canonical)<<'\t'<<hard<<'\t'<<best<<'\n';
  }++site;
 }
}
