#include "text_clean/retrieval.h"
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
std::string hex(const std::string& s) {
    const char* digits="0123456789abcdef"; std::string out;
    for (unsigned char c : s) { out+=digits[c>>4]; out+=digits[c&15]; }
    return out;
}
std::string unhex(const std::string& s) {
    auto digit=[](char c) { if(c>='0'&&c<='9') return c-'0'; if(c>='a'&&c<='f') return c-'a'+10; throw std::invalid_argument("invalid hex"); };
    if(s.size()%2) throw std::invalid_argument("odd hex length");
    std::string out;
    for(std::size_t i=0;i<s.size();i+=2) out+=static_cast<char>((digit(s[i])<<4)|digit(s[i+1]));
    return out;
}
}
// A persistent, UTF-8-safe line protocol; no Python or model dependency in this process.
int main(int argc, char** argv) {
    if (argc!=2) { std::cerr<<"usage: tc_retrieve evidence.sqlite\n"; return 2; }
    try {
        text_clean::Retriever retriever(argv[1]); std::string line;
        while(std::getline(std::cin,line)) {
            try {
                if(line.size()>131072) throw std::invalid_argument("request too large");
                std::vector<std::string> f; std::stringstream in(line); std::string part;
                while(std::getline(in,part,'\t')) f.push_back(part);
                if(f.size()<4 || (f[0]!="Q"&&f[0]!="L")) throw std::invalid_argument("invalid request");
                std::vector<std::string> words;
                for(std::size_t i=4;i<f.size();++i) words.push_back(unhex(f[i]));
                auto r=retriever.retrieve(unhex(f[3]),words,std::stoul(f[1]),std::stoul(f[2]),f[0]=="L");
                std::cout<<"B\t"<<r.characters<<'\t'<<r.truncated<<'\n';
                for(const auto& e:r.segments)
                    std::cout<<"S\t"<<e.id<<'\t'<<hex(e.cluster)<<'\t'<<hex(e.text)<<'\t'<<e.off<<'\t'
                        <<hex(e.left)<<'\t'<<e.bos<<'\t'<<e.eos<<'\t'<<hex(e.left_class)<<'\t'
                        <<hex(e.right_class)<<'\t'<<hex(e.family)<<'\t'<<hex(e.source_doc)<<'\n';
                std::cout<<"E\n"<<std::flush;
            } catch(const std::exception& e) { std::cout<<"X\t"<<hex(e.what())<<'\n'<<std::flush; }
        }
    } catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
}
