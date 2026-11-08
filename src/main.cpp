#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <fcntl.h>
#include <io.h>
#include <shellapi.h>
#endif

#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "text_clean/lexicon.h"
#include "text_clean/dictionary_bundle.h"
#include "text_clean/pinyin_dict.h"
#include "text_clean/text_cleaner.h"
#include "text_clean/text_split.h"
#include "text_clean/utf8.h"
#include "text_clean/domain_evidence.h"
#include "text_clean/word_frequency.h"
#include "text_clean/word_maintaining.h"
#include "text_clean/word_review.h"

namespace {

namespace fs = std::filesystem;

struct Options {
    std::string data_dir, index_cache;
    bool legacy_data=false, no_candidates=false, check_data=false, no_index_cache=false;
    std::string lexicon_path;
    std::string pinyin_path;
    std::string word_path;
    std::string word_freq_path;
    std::string char_freq_path;
    std::string vocabulary_path;
    std::string input_path;
    std::string title, description, title_path, description_path;
    bool video_context = false;
    bool enable_pinyin = true;
    bool char_baseline = true;
    bool review = false;
    bool verbose = false;
    bool help = false;
    std::size_t max_distance = 2;
    std::size_t min_fuzzy = 2;
    std::size_t min_unknown = 2;
    double distance_penalty = 0.65;
    double modification_threshold = 0.70;
    std::string missing_evidence = "char";   // 2026-11-09 起默认 M1（园长批准）
    bool missing_evidence_set = false;
    double missing_cap = 0.6;     // 默认 M2 封顶档位
    bool enable_admission_guard = true;
    bool require_first_syllable_match = true;
    std::size_t min_window_syllables = 2;
    bool target_char_frequency = false;
    bool use_domain_frequency = false;
    std::string evidence_dir;    // 显式指定的证据表目录；空=用 data/context/modern
    double domain_gap = 1.5;
    bool use_context_evidence = true;   // 2026-11-09 起默认开启（单边）
    bool ctx_set = false;               // 是否被命令行显式改过
    double context_weight = 1.0;
    std::size_t context_span = 2;
    std::uint64_t context_min_anchor = 3;
    bool context_one_sided = true;
    char32_t mask_char = U'*';
    std::vector<std::string> words;
};

std::string find_data_file(const std::string& program, const char* name) {
    std::error_code error;
    const fs::path relative = fs::path("data") / name;
    if (fs::exists(relative, error)) return relative.string();

    if (!program.empty()) {
        const fs::path beside = fs::path(program).parent_path() / "data" / name;
        if (fs::exists(beside, error)) return beside.string();
    }
#ifdef TC_DATA_DIR
    const fs::path installed = fs::path(TC_DATA_DIR) / name;
    if (fs::exists(installed, error)) return installed.string();
#endif
    return {};
}

void print_help() {
    std::cout
        << "ASR 文本清洗：AC 自动机 + 拼音倒排索引 + 编辑距离回退\n\n"
        << "用法: text_clean [选项] [文本...]\n\n"
        << "不提供文本时从标准输入读取。\n\n"
        << "选项:\n"
        << "  --data-dir <dir>       新 TSV 词库根目录（默认 data）\n"
        << "  --no-candidates        不读取候选表，运行零修改基线\n"
        << "  --check-data           校验新词库并输出规模，不纠错\n"
        << "  --legacy-data          显式读取 data/old 兼容数据；仍使用新的保护规则\n"
        << "  --no-index-cache       不读写自动索引缓存\n"
        << "  --index-cache <path>   自动生成的索引缓存（可不指定）\n"
        << "新词库默认使用 2.302585*(ZipfC-ZipfO)；缺失任一词频则保留原文。\n"
        << "  --lexicon <path>       动作/拼音词表 (默认 data/lexicon.txt)\n"
        << "  --word-file <path>     AC 精确词表 (默认 data/word.txt)\n"
        << "  --vocabulary <path>    合法词汇集合（默认 data/dict.txt；不参与评分）\n"
        << "  --word-freq <path>     词频表 (默认 data/word_freq.txt)\n"
        << "  --char-freq <path>     单字频率表，未收录原文的概率基线 (默认 data/dict.txt)\n"
        << "  --no-char-baseline     关闭概率基线，退回 f(O)=0 的旧打分口径\n"
        << "  --pinyin-dict <path>   拼音字表 (默认 data/pinyin_dict.txt)\n"
        << "  --title <text>        视频标题（启用临时上下文）\n"
        << "  --title-file <path>   UTF-8 标题文件（优先于 --title）\n"
        << "  --description-file <path> UTF-8 简介文件（优先于 --description）\n"
        << "  --description <text>  视频简介（正文作为低可信 ASR 证据）\n"
        << "  --review               清洗前审核标题/简介中的未收录词语 (交互)\n"
        << "  --input-file <path>    从文件读取待清洗文档 (审核时推荐)\n"
        << "  --min-unknown <n>      待审核词语最短长度 (默认 2)\n"
        << "  --no-pinyin            关闭拼音近似匹配，仅用 AC 精确锁定\n"
        << "  --max-distance <n>     拼音编辑距离阈值 (默认 2)\n"
        << "  --min-fuzzy <n>        允许模糊匹配的最短音节数 (默认 2)\n"
        << "  --lambda <x>           声调距离惩罚 λ (默认 0.65)\n"
        << "  --mu <x>               修改门槛 μ (默认 0.70)\n"
        << "  --missing-evidence <m> 原文缺词频证据时：veto(默认基线)|char(M1)|fixed(M2)\n"
        << "  --missing-cap <K>      M2 上限档位 K（默认 0.6；fixed 模式必填）\n"
        << "  --evidence-dir <dir>   E030：历史证据表目录（words/pairs/unis.tsv，默认不用）\n"
        << "  --domain-freq          E030：证据来源改用历史词频（需 --evidence-dir）\n"
        << "  --domain-gap <x>       原文在历史语料查不到时记 ZipfC-x（默认 1.5）\n"
        << "  --ctx-evidence         加邻接上下文证据（默认开，且默认只扣分不放行）\n"
        << "  --no-ctx-evidence      关掉上下文证据，退回 M1+M2 口径\n"
        << "  --context-dir <dir>    上下文表目录（默认 <data-dir>/context/modern）\n"
        << "  --ctx-weight <x>       上下文证据权重（默认 1.0）\n"
        << "  --ctx-span <1|2>       上下文锚点跨度：1=单个邻字，2=两个邻字（默认 1）\n"
        << "  --ctx-one-sided        上下文只扣分不放行（单边否决）\n"
        << "  --ctx-min-anchor <n>   锚点在语料里少于 n 次就弃权（默认 3）\n"
        << "  --target-char-freq     单字目标词缺词级证据时改用单字频率表（默认关）\n"
        << "  --min-window <n>     拼音窗口最短长度 (默认 2；设 1 时同时放开单字检索)\n"
        << "  --no-admission-guard   关闭 E021 静态否决限制（原文为合法词且静态分≤0 时仍允许靠元数据加分改写）\n"
        << "  --no-first-syllable-gate 关闭首音节锚点保护（窗口起点门 + 索引首音节过滤）\n"
        << "  --mask-char <char>     掩码字符 (默认 *)\n"
        << "  -v, --verbose          向 stderr 输出匹配明细与 AC 词表来源\n"
        << "  -h, --help             显示帮助\n\n"
        << "word.txt: 每行一个词语，空行和 # 开头为注释；AC 只从该文件构建。\n"
        << "审核只对“标题”和“简介”分词，正文不参与分词。\n\n"
        << "动作词表格式: 规范词<TAB>拼音<TAB>别名,别名<TAB>replace|mask|keep\n"
        << "拼音填 - 表示自动生成，填 none 表示仅精确匹配。\n";
}

bool read_text_file(const std::string& path, std::string* text, std::string* error) {
    std::ifstream input(fs::u8path(path), std::ios::binary);
    if (!input) {
        *error = "cannot open input file: " + path;
        return false;
    }
    text->assign(std::istreambuf_iterator<char>(input),
                 std::istreambuf_iterator<char>());
    return true;
}

bool parse_size(const std::string& value, std::size_t* out, std::string* error) {
    try {
        std::size_t consumed = 0;
        const unsigned long long parsed = std::stoull(value, &consumed);
        if (consumed != value.size()) {
            *error = "not a number: " + value;
            return false;
        }
        *out = static_cast<std::size_t>(parsed);
        return true;
    } catch (const std::exception&) {
        *error = "not a number: " + value;
        return false;
    }
}

bool parse_double(const std::string& value, double* out, std::string* error) {
    try {
        std::size_t consumed = 0;
        const double parsed = std::stod(value, &consumed);
        if (consumed != value.size()) {
            *error = "not a number: " + value;
            return false;
        }
        *out = parsed;
        return true;
    } catch (const std::exception&) {
        *error = "not a number: " + value;
        return false;
    }
}

bool parse_options(const std::vector<std::string>& args, Options* options,
                   std::string* error) {
    const std::size_t argc = args.size();
    for (std::size_t i = 1; i < argc; ++i) {
        const std::string& arg = args[i];
        auto next_value = [&](std::string* value) {
            if (i + 1 >= argc) {
                *error = "missing value for " + arg;
                return false;
            }
            *value = args[++i];
            return true;
        };

        if (arg == "-h" || arg == "--help") {
            options->help = true;
            return true;
        }
        if(arg=="--data-dir") {
            if(!next_value(&options->data_dir)) return false;
        } else if(arg=="--index-cache") {
            if(!next_value(&options->index_cache)) return false;
        } else if(arg=="--legacy-data") options->legacy_data=true;
        else if(arg=="--no-index-cache") options->no_index_cache=true;
        else if(arg=="--no-candidates") options->no_candidates=true;
        else if(arg=="--check-data") options->check_data=true;
        else if (arg == "--no-pinyin") {
            options->enable_pinyin = false;
        } else if (arg == "--no-char-baseline") {
            options->char_baseline = false;
        } else if (arg == "-v" || arg == "--verbose") {
            options->verbose = true;
        } else if (arg == "--lexicon") {
            if (!next_value(&options->lexicon_path)) return false;
        } else if (arg == "--word-file") {
            if (!next_value(&options->word_path)) return false;
        } else if (arg == "--vocabulary") {
            if (!next_value(&options->vocabulary_path)) return false;
        } else if (arg == "--word-freq") {
            if (!next_value(&options->word_freq_path)) return false;
        } else if (arg == "--char-freq") {
            if (!next_value(&options->char_freq_path)) return false;
        } else if (arg == "--lambda") {
            std::string value;
            if (!next_value(&value)) return false;
            if (!parse_double(value, &options->distance_penalty, error)) return false;
        } else if (arg == "--mu") {
            std::string value;
            if (!next_value(&value)) return false;
            if (!parse_double(value, &options->modification_threshold, error)) {
                return false;
            }
        } else if (arg == "--missing-evidence") {
            options->missing_evidence_set = true;
            if (!next_value(&options->missing_evidence)) return false;
            if (options->missing_evidence != "veto" && options->missing_evidence != "char" &&
                options->missing_evidence != "fixed") {
                *error = "--missing-evidence must be veto|char|fixed";
                return false;
            }
        } else if (arg == "--missing-cap") {
            std::string value;
            if (!next_value(&value)) return false;
            if (!parse_double(value, &options->missing_cap, error)) return false;
            if (options->missing_cap < 0.0) { *error = "--missing-cap must be >= 0"; return false; }
        } else if (arg == "--no-admission-guard") {
            options->enable_admission_guard = false;
        } else if (arg == "--evidence-dir") {
            if (!next_value(&options->evidence_dir)) return false;
        } else if (arg == "--domain-freq") {
            options->use_domain_frequency = true;
        } else if (arg == "--domain-gap") {
            std::string value;
            if (!next_value(&value)) return false;
            if (!parse_double(value, &options->domain_gap, error)) return false;
        } else if (arg == "--ctx-evidence") {
            options->use_context_evidence = true;
            options->ctx_set = true;
        } else if (arg == "--no-ctx-evidence") {
            options->use_context_evidence = false;
            options->ctx_set = true;
        } else if (arg == "--context-dir") {
            std::string value;
            if (!next_value(&value)) return false;
            options->evidence_dir = value;
        } else if (arg == "--ctx-weight") {
            std::string value;
            if (!next_value(&value)) return false;
            if (!parse_double(value, &options->context_weight, error)) return false;
        } else if (arg == "--ctx-span") {
            std::string value;
            if (!next_value(&value)) return false;
            if (!parse_size(value, &options->context_span, error)) return false;
            if (options->context_span < 1 || options->context_span > 2) {
                *error = "--ctx-span 只能是 1 或 2"; return false; }
        } else if (arg == "--ctx-one-sided") {
            options->context_one_sided = true;
        } else if (arg == "--ctx-min-anchor") {
            std::string value;
            if (!next_value(&value)) return false;
            if (!parse_size(value, &options->context_min_anchor, error)) return false;
        } else if (arg == "--target-char-freq") {
            options->target_char_frequency = true;
        } else if (arg == "--min-window") {
            std::string value;
            if (!next_value(&value)) return false;
            if (!parse_size(value, &options->min_window_syllables, error)) return false;
            if (options->min_window_syllables < 1 || options->min_window_syllables > 8) {
                *error = "--min-window 需要 1~8"; return false; }
        } else if (arg == "--no-first-syllable-gate") {
            options->require_first_syllable_match = false;
        } else if (arg == "--input-file") {
            if (!next_value(&options->input_path)) return false;
        } else if (arg == "--title-file") {
            if (!next_value(&options->title_path)) return false;
            options->video_context = true;
        } else if (arg == "--description-file") {
            if (!next_value(&options->description_path)) return false;
            options->video_context = true;
        } else if (arg == "--title") {
            if (!next_value(&options->title)) return false;
            options->video_context = true;
        } else if (arg == "--description") {
            if (!next_value(&options->description)) return false;
            options->video_context = true;
        } else if (arg == "--review") {
            options->review = true;
        } else if (arg == "--min-unknown") {
            std::string value;
            if (!next_value(&value)) return false;
            if (!parse_size(value, &options->min_unknown, error)) return false;
        } else if (arg == "--pinyin-dict") {
            if (!next_value(&options->pinyin_path)) return false;
        } else if (arg == "--mask-char") {
            std::string value;
            if (!next_value(&value)) return false;
            const std::u32string points = text_clean::utf8::decode(value);
            if (points.size() != 1) {
                *error = "--mask-char expects exactly one character";
                return false;
            }
            options->mask_char = points[0];
        } else if (arg == "--max-distance") {
            std::string value;
            if (!next_value(&value)) return false;
            if (!parse_size(value, &options->max_distance, error)) return false;
        } else if (arg == "--min-fuzzy") {
            std::string value;
            if (!next_value(&value)) return false;
            if (!parse_size(value, &options->min_fuzzy, error)) return false;
        } else if (arg == "--") {
            for (++i; i < argc; ++i) options->words.emplace_back(args[i]);
            break;
        } else if (!arg.empty() && arg.front() == '-') {
            *error = "unknown option: " + arg;
            return false;
        } else {
            options->words.push_back(arg);
        }
    }
    return true;
}

const char* kind_name(text_clean::MatchKind kind) {
    switch (kind) {
        case text_clean::MatchKind::Exact:
            return "exact";
        case text_clean::MatchKind::Pinyin:
            return "pinyin";
        case text_clean::MatchKind::Fuzzy:
            return "fuzzy";
    }
    return "unknown";
}

const char* status_name(text_clean::MatchStatus status) {
    switch (status) {
        case text_clean::MatchStatus::LockedByAc:
            return "ac_locked";
        case text_clean::MatchStatus::None:
            return "none";
    }
    return "unknown";
}

const char* action_name(text_clean::Action action) {
    switch (action) {
        case text_clean::Action::Replace:
            return "replace";
        case text_clean::Action::Mask:
            return "mask";
        case text_clean::Action::Keep:
            return "keep";
    }
    return "unknown";
}

void print_matches(const text_clean::CleanResult& result) {
    std::size_t locked = 0;
    for (const auto& match : result.matches) {
        if (match.status == text_clean::MatchStatus::LockedByAc) ++locked;
    }
    std::cerr << "matches: " << result.matches.size() << " (ac_locked: " << locked
              << ")\n";
    for (const auto& match : result.matches) {
        std::cerr << "  [" << kind_name(match.kind) << "] status="
                  << status_name(match.status) << " " << match.begin << ".."
                  << match.end << " \"" << text_clean::utf8::encode(match.matched)
                  << "\" -> \"" << text_clean::utf8::encode(match.replacement) << "\""
                  << " entry=" << match.entry_id << " distance=" << match.distance
                  << " score=" << match.score << " logR=" << match.log_ratio
                  << " fC=" << match.candidate_frequency
                  << " fO=" << match.original_frequency
                  << " action=" << action_name(match.action)
                  << " context_bonus=" << match.context_bonus;
        if(match.candidate_zipf) std::cerr<<" zipfC="<<*match.candidate_zipf;
        if(match.original_zipf) std::cerr<<" zipfO="<<*match.original_zipf;
        std::cerr<<"\n";
    }
}

std::vector<std::string> collect_args(int argc, char** argv) {
#ifdef _WIN32
    // argv from main() is decoded with the ANSI code page, which mangles
    // non-ASCII command line arguments. Use the wide command line instead.
    int wide_argc = 0;
    LPWSTR* wide = CommandLineToArgvW(GetCommandLineW(), &wide_argc);
    if (wide == nullptr) {
        return std::vector<std::string>(argv, argv + argc);
    }
    std::vector<std::string> args;
    args.reserve(static_cast<std::size_t>(wide_argc));
    for (int i = 0; i < wide_argc; ++i) {
        const int size = WideCharToMultiByte(CP_UTF8, 0, wide[i], -1, nullptr, 0,
                                             nullptr, nullptr);
        if (size <= 0) {
            args.emplace_back();
            continue;
        }
        std::string value(static_cast<std::size_t>(size), '\0');
        WideCharToMultiByte(CP_UTF8, 0, wide[i], -1, value.data(), size, nullptr,
                            nullptr);
        value.pop_back();
        args.push_back(std::move(value));
    }
    LocalFree(wide);
    return args;
#else
    return std::vector<std::string>(argv, argv + argc);
#endif
}

int run(const std::vector<std::string>& args) {
    Options options;
    std::string error;
    if (!parse_options(args, &options, &error)) {
        std::cerr << "error: " << error << "\n";
        return 2;
    }
    if (options.help) {
        print_help();
        return 0;
    }

    const std::string program = args.empty() ? std::string() : args.front();

    text_clean::PinyinDict pinyin;
    text_clean::Lexicon lexicon;
    text_clean::WordMaintainer word_table;
    text_clean::WordFrequency word_frequency;
    text_clean::Vocabulary vocabulary;
    text_clean::CharFrequency char_frequency;
    const bool legacy=options.legacy_data || !options.lexicon_path.empty();
    if(!legacy) {
        if(options.review) { std::cerr<<"error: TSV review is read-only; use an explicit legacy --lexicon and --word-file for legacy review\n"; return 2; }
        if(options.data_dir.empty()) {
            auto probe=find_data_file(program,"ac/ac_lock.tsv");
            if(probe.empty()) {std::cerr<<"error: TSV data root not found; use --data-dir\n";return 2;}
            options.data_dir=fs::path(probe).parent_path().parent_path().string();
        }
        text_clean::DictionaryBundle bundle;
        if(!text_clean::DictionaryBundle::load(options.data_dir,options.no_candidates,bundle,&error)) {std::cerr<<"error: "<<error<<"\n";return 2;}
        if(options.check_data) {
            std::cout<<"enabled_rows="<<bundle.enabled_rows<<" disabled_rows="<<bundle.disabled_rows
                     <<" targets="<<bundle.candidates.size()<<" locks="<<bundle.locks.size()
                     <<" vocabulary="<<bundle.vocabulary.size()<<" unknown_targets="<<bundle.unknown_targets
                     <<" domain_counts_loaded=0\n"; return 0;
        }
        if(!options.no_candidates && !options.no_index_cache && options.index_cache.empty())
            options.index_cache=(fs::u8path(options.data_dir)/"generated/pinyin_index.bin").string();
        pinyin=std::move(bundle.characters); lexicon=std::move(bundle.candidates);
        word_table=std::move(bundle.locks); vocabulary=std::move(bundle.vocabulary);
        if(!options.word_path.empty() || !options.pinyin_path.empty() || !options.vocabulary_path.empty()) {
            std::cerr<<"error: use --legacy-data for legacy dictionary overrides\n"; return 2;
        }
        options.word_path=(fs::u8path(options.data_dir)/"ac/ac_lock.tsv").string();
        if(!options.no_candidates && options.word_freq_path.empty()) {
            word_frequency.use_zipf();
            for(const auto& item:bundle.word_frequency)
                if(item.second.zipf) word_frequency.add_zipf(item.first,*item.second.zipf);
            // E024 M1: the character table is evidence for a missing original only;
            // it never becomes a candidate source and never enters the counts path.
            for(const auto& item:bundle.char_frequency)
                if(item.second.zipf && item.first.size()==1)
                    word_frequency.add_char_zipf(item.first.front(),*item.second.zipf);
        }
        if(!options.no_candidates && !options.word_freq_path.empty() && !word_frequency.load_file(options.word_freq_path,&error)) {std::cerr<<"error: "<<error<<"\n";return 2;}
        if(word_frequency.is_zipf() && !options.char_freq_path.empty()) {std::cerr<<"error: count character baseline cannot be mixed with Zipf; use explicit --word-freq counts for compatibility\n";return 2;}
        if(options.missing_evidence!="veto" && !word_frequency.is_zipf() && !options.no_candidates) {std::cerr<<"error: --missing-evidence 仅适用于 Zipf 词库；旧次数模式请保持 veto\n";return 2;}
        if(options.missing_evidence=="fixed" && options.missing_cap<=0.0) {std::cerr<<"error: --missing-evidence fixed 需要 --missing-cap > 0\n";return 2;}
        if(!options.no_candidates && options.char_baseline && !options.char_freq_path.empty() && !char_frequency.load_file(options.char_freq_path,&error)) {std::cerr<<"error: "<<error<<"\n";return 2;}
    } else {
    if (options.lexicon_path.empty()) {
        options.lexicon_path = find_data_file(program, "old/lexicon.txt");
    }
    if (options.lexicon_path.empty()) {
        std::cerr << "error: lexicon not found, use --lexicon <path>\n";
        return 2;
    }

    if (options.pinyin_path.empty()) {
        options.pinyin_path = find_data_file(program, "old/pinyin_dict.txt");
    }
    if (options.enable_pinyin && options.pinyin_path.empty()) {
        std::cerr << "error: pinyin dictionary not found, use --pinyin-dict <path> "
                     "or --no-pinyin\n";
        return 2;
    }

    if (!options.pinyin_path.empty()) {
        if (!pinyin.load_file(options.pinyin_path, &error)) {
            std::cerr << "error: " << error << "\n";
            return 2;
        }
    }

    const text_clean::Lexicon::PinyinDeriver derive =
        [&pinyin](const std::u32string& word) { return pinyin.to_pinyin(word); };

    if (!options.no_candidates && !text_clean::Lexicon::load_file(options.lexicon_path, derive, lexicon, &error)) {
        std::cerr << "error: " << error << "\n";
        return 2;
    }

    if (options.word_path.empty()) {
        options.word_path = find_data_file(program, "raw/AC_word.txt");
    }
    if (options.word_path.empty()) {
        if (options.review) {
            options.word_path = "data/word.txt";
        } else {
            std::cerr << "error: word file not found, use --word-file <path>\n";
            return 2;
        }
    }

    std::error_code word_error;
    if (fs::exists(options.word_path, word_error)) {
        if (!word_table.load_file(options.word_path, &error)) {
            std::cerr << "error: " << error << "\n";
            return 2;
        }
    } else if (options.review) {
        std::cerr << "warning: word file not found, starting empty: "
                  << options.word_path << "\n";
    } else {
        std::cerr << "error: word file not found: " << options.word_path << "\n";
        return 2;
    }

    if (options.word_freq_path.empty()) {
        options.word_freq_path = find_data_file(program, "old/word_freq.txt");
    }
    if (options.word_freq_path.empty()) {
        std::cerr << "error: word frequency table not found, use --word-freq <path>\n";
        return 2;
    }
    if (!word_frequency.load_file(options.word_freq_path, &error)) {
        std::cerr << "error: " << error << "\n";
        return 2;
    }

    if (options.vocabulary_path.empty()) options.vocabulary_path = find_data_file(program, "old/dict.txt");
    if (options.vocabulary_path.empty() || !vocabulary.load_file(options.vocabulary_path, &error)) {
        std::cerr << "error: " << (error.empty() ? "vocabulary not found, use --vocabulary <path>" : error) << "\n";
        return 2;
    }
    // Optional: without it unattested windows fall back to f(O) = 0, i.e. the
    // old behaviour in which a rewrite needs no positive evidence.
    if (!options.char_baseline) {
        options.char_freq_path.clear();
    } else if (options.char_freq_path.empty()) {
        options.char_freq_path = find_data_file(program, "old/dict.txt");
    }
    if (!options.char_freq_path.empty() &&
        !char_frequency.load_file(options.char_freq_path, &error)) {
        if (options.verbose) {
            std::cerr << "warning: " << error << " (character baseline disabled)\n";
        }
        char_frequency.clear();
        error.clear();
    }
    }
    if(options.no_candidates) {lexicon.clear(); word_frequency={}; char_frequency={};}
    std::string text;
    if (!options.input_path.empty()) {
        if (!read_text_file(options.input_path, &text, &error)) {
            std::cerr << "error: " << error << "\n";
            return 2;
        }
    } else if (!options.words.empty()) {
        for (std::size_t i = 0; i < options.words.size(); ++i) {
            if (i != 0) text.push_back(' ');
            text += options.words[i];
        }
    } else if (options.review) {
        std::cerr << "error: --review requires text arguments or --input-file "
                     "(stdin is used for review input)\n";
        return 2;
    } else {
        text.assign(std::istreambuf_iterator<char>(std::cin),
                    std::istreambuf_iterator<char>());
    }

    if ((!options.title_path.empty() && !read_text_file(options.title_path, &options.title, &error)) ||
        (!options.description_path.empty() && !read_text_file(options.description_path, &options.description, &error))) {
        std::cerr << "error: " << error << "\n";
        return 2;
    }
    if (options.review) {
        const std::vector<text_clean::Section> sections =
            text_clean::TextSplitter::split(text);
        if (!text_clean::WordReview::run(word_table, sections, options.word_path,
                                         options.min_unknown, std::cin, std::cerr,
                                         &error)) {
            std::cerr << "error: " << error << "\n";
            return 2;
        }
    }

    text_clean::CleanerConfig config;
    config.enable_pinyin = options.enable_pinyin;
    config.max_pinyin_distance = options.max_distance;
    config.min_syllables_for_fuzzy = options.min_fuzzy;
    config.distance_penalty = options.distance_penalty;
    config.modification_threshold = options.modification_threshold;
    config.mask_char = options.mask_char;
    config.index_cache_path = options.no_index_cache?std::string{}:options.index_cache;
    // 次数口径（--legacy-data / --lexicon / --word-freq）没有 Zipf 证据体系：
    // 未显式传参时新默认自动退回旧基线，保证历史数字仍可复现。
    const bool counts_mode = options.legacy_data || !options.lexicon_path.empty() || !options.word_freq_path.empty() ||
                         options.no_candidates;
    if (counts_mode) {
        if (!options.missing_evidence_set) { options.missing_evidence = "veto"; options.missing_cap = 0.0; }
        if (!options.ctx_set) options.use_context_evidence = false;
    }
    std::string context_path;
    if (options.no_candidates) options.use_context_evidence = false;   // 零候选基线不依赖任何证据表
    if (options.use_context_evidence || options.use_domain_frequency) {
        namespace fs = std::filesystem;
        context_path = options.evidence_dir.empty()
            ? (fs::u8path(options.data_dir) / "context" / "modern").string()
            : options.evidence_dir;
    }

    using MissingEvidence = text_clean::CleanerConfig::MissingEvidence;
    config.missing_evidence = options.missing_evidence == "char" ? MissingEvidence::CharEstimate
                              : options.missing_evidence == "fixed" ? MissingEvidence::FixedCap
                              : MissingEvidence::Veto;
    config.missing_cap = options.missing_cap;
    config.enable_admission_guard = options.enable_admission_guard;
    config.require_first_syllable_match = options.require_first_syllable_match;
    config.min_window_syllables = options.min_window_syllables;
    config.target_char_frequency = options.target_char_frequency;
    config.use_domain_frequency = options.use_domain_frequency;
    config.domain_unknown_gap = options.domain_gap;
    config.use_context_evidence = options.use_context_evidence;
    config.context_weight = options.context_weight;
    config.context_span = options.context_span;
    config.context_min_anchor = options.context_min_anchor;
    config.context_one_sided = options.context_one_sided;
    // 放开窗口下限时，单字窗口也要允许进入检索（否则 :299 会把长度 1 全部丢掉）。
    config.min_syllables_for_exact_pinyin = std::min(config.min_syllables_for_exact_pinyin, options.min_window_syllables);

    // Captured before the moves below; reading a moved-from table would print 0.
    const std::size_t zipf_word_evidence = word_frequency.size();
    const std::size_t zipf_char_evidence = word_frequency.char_size();

    text_clean::DomainEvidence domain;
    if (!context_path.empty() && !domain.load(context_path, &error)) {
        std::cerr << "error: 领域证据加载失败: " << error << "\n";
        return 2;
    }
    if (!context_path.empty() && domain.empty()) {
        std::cerr << "error: 上下文证据表不可用: " << context_path << "\n"
                  << "       请把词库检出完整，或用 --no-ctx-evidence 关掉上下文（退回 M1+M2 口径）\n";
        return 2;
    }
    domain.set_min_anchor_count(options.context_min_anchor);
    const std::size_t domain_word_rows = domain.word_rows();
    const std::size_t domain_pair_rows = domain.pair_rows();

    std::optional<std::vector<std::u32string>> ac_words = word_table.words();
    text_clean::TextCleaner cleaner(std::move(lexicon), pinyin, config,
                                    std::move(ac_words), std::move(word_frequency),
                                    std::move(vocabulary), std::move(char_frequency),
                                    std::move(domain));

    if (options.verbose) {
        std::cerr << "ac source: word file (" << word_table.size()
                  << " words) " << options.word_path << "\n";
        std::cerr << "word frequency: " << options.word_freq_path << "\n";
        std::cerr << "character baseline: " << options.char_freq_path << "\n";
        std::cerr << "tone scoring: lambda=" << config.distance_penalty
                  << " mu=" << config.modification_threshold << "\n";
        std::cerr << "missing evidence: mode=" << options.missing_evidence
                  << " cap=" << config.missing_cap
                  << " word_evidence=" << zipf_word_evidence
                  << " char_evidence=" << zipf_char_evidence
                  << " admission_guard=" << (config.enable_admission_guard ? "on" : "off")
                  << " domain_words=" << domain_word_rows << " domain_pairs=" << domain_pair_rows
                  << " domain_gap=" << config.domain_unknown_gap
                  << " ctx_span=" << config.context_span
                  << " ctx_min_anchor=" << config.context_min_anchor
                  << " ctx_one_sided=" << (config.context_one_sided ? "on" : "off")
                  << " ctx_evidence=" << (config.use_context_evidence ? "on" : "off")
                  << " ctx_table=" << (context_path.empty() ? std::string("none") : context_path)
                  << " ctx_weight=" << config.context_weight
                  << " first_syllable_gate=" << (config.require_first_syllable_match ? "on" : "off") << "\n";
    }

    if(options.verbose) std::cerr<<"frequency mode: "<<(legacy || !options.word_freq_path.empty()?"counts":"zipf")<<"; domain counts disabled\n";
    const auto context = options.video_context
        ? cleaner.prepare_context(options.title, options.description, text)
        : text_clean::VideoContext{};
    const text_clean::CleanResult result = options.video_context
        ? cleaner.clean(text, context) : cleaner.clean(text);
    std::cout << result.text;
    if (result.text.empty() || result.text.back() != '\n') std::cout << '\n';

    if (options.verbose) print_matches(result);
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
#ifdef _WIN32
    SetConsoleOutputCP(CP_UTF8);
    SetConsoleCP(CP_UTF8);
    // Text cleaning should not rewrite line endings or touch UTF-8 bytes.
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
#endif
    return run(collect_args(argc, argv));
}
