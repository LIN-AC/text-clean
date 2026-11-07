#include "test_framework.h"
#include "text_clean/dictionary_bundle.h"
#include <filesystem>
#include <fstream>
using namespace text_clean;
int main() {
    const auto root=std::filesystem::temp_directory_path()/"tc_bundle_fixture";
    auto write=[&](const char* file,const char* body){auto p=root/file;std::filesystem::create_directories(p.parent_path());std::ofstream(p,std::ios::binary)<<body;};
    write("ac/ac_lock.tsv","word\tgroup\n信\t保护\n");
    write("vocabulary/vocabulary.tsv","word\tweight\n微星\t99999\n");
    write("vocabulary/extvocabulary.tsv","word\tweight\n微信\t3\n");
    write("pronunciation/pronunciation_char.tsv","char\treadings\tsources\tagreement\tdropped\n微\twei1\tcedict\tagree\t\n信\txin4\tcedict\tagree\t\n");
    write("pronunciation/pronunciation.tsv","entry\treadings\n微信\twei1xin4\n");
    write("frequency/word_freq.tsv","word\tgeneral\tours_count\tours_per_million\tsources\n微信\t4.85\t9999999\t99999\twordfreq+ours\n未知\t0\t0\t\tnone\n零值\t0\t99999\t999\twordfreq+ours\n");
    write("frequency/char_freq.tsv","char\tgeneral\tours_count\tours_per_million\tsources\n信\t5.2\t123\t99\twordfreq+ours\n");
    write("correction/candidates.tsv","canonical\tpinyin\talias\tsource\tstatus\n微信\twei1xin4\t薇信\t人工确认\t1\n微信\twei1xin4\t威信\tLLM 提议\t0\n微信\twei1xin4\t维信\t人工确认\t1\n");
    DictionaryBundle b;std::string error;
    CHECK(DictionaryBundle::load(root.string(),false,b,&error));
    CHECK_EQ(b.candidates.size(),std::size_t{1});CHECK_EQ(b.enabled_rows,std::size_t{2});
    CHECK_EQ(b.candidates.entries().at(0).aliases.size(),std::size_t{2});
    CHECK_EQ(b.candidates.entries().at(0).pronunciations.at(0).at(1),std::string("xin4"));
    CHECK(b.vocabulary.contains(U"微星"));CHECK_EQ(b.locks.size(),std::size_t{1});
    CHECK_EQ(b.word_frequency.at(U"微信").zipf.value(),4.85);
    CHECK(!b.word_frequency.at(U"未知").zipf.has_value());
    CHECK(!b.word_frequency.at(U"零值").zipf.has_value()); // zero and domain counts cannot manufacture a prior
    write("correction/candidates.tsv","invalid data");
    CHECK(!DictionaryBundle::load(root.string(),false,b,&error));
    CHECK_EQ(b.candidates.size(),std::size_t{1}); // failed load is atomic
    CHECK(DictionaryBundle::load(root.string(),true,b,&error));CHECK(b.candidates.empty());
    DictionaryBundle actual;
    CHECK(DictionaryBundle::load(TC_NEW_DATA_DIR,false,actual,&error));
    if(!error.empty()) std::cerr<<error<<"\n";
    CHECK(actual.enabled_rows>0);CHECK(actual.candidates.size()<actual.enabled_rows);
    CHECK(DictionaryBundle::load(TC_NEW_DATA_DIR,true,actual,&error));CHECK(actual.candidates.empty());
    return test::finish("test_dictionary_bundle");
}
