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
#include "text_clean/pinyin_dict.h"
#include "text_clean/text_cleaner.h"
#include "text_clean/text_split.h"
#include "text_clean/utf8.h"
#include "text_clean/word_maintaining.h"
#include "text_clean/word_review.h"

namespace {

namespace fs = std::filesystem;

struct Options {
    std::string lexicon_path;
    std::string pinyin_path;
    std::string word_path;
    std::string input_path;
    bool enable_pinyin = true;
    bool review = false;
    bool verbose = false;
    bool help = false;
    std::size_t max_distance = 1;
    std::size_t min_fuzzy = 3;
    std::size_t min_unknown = 2;
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
        << "  --lexicon <path>       动作/拼音词表 (默认 data/lexicon.txt)\n"
        << "  --word-file <path>     AC 精确词表 (默认 data/word.txt)\n"
        << "  --pinyin-dict <path>   拼音字表 (默认 data/pinyin_dict.txt)\n"
        << "  --review               清洗前审核标题/简介中的未收录词语 (交互)\n"
        << "  --input-file <path>    从文件读取待清洗文档 (审核时推荐)\n"
        << "  --min-unknown <n>      待审核词语最短长度 (默认 2)\n"
        << "  --no-pinyin            关闭拼音近似匹配，仅用 AC 精确锁定\n"
        << "  --max-distance <n>     拼音编辑距离阈值 (默认 1)\n"
        << "  --min-fuzzy <n>        允许模糊匹配的最短音节数 (默认 3)\n"
        << "  --mask-char <char>     掩码字符 (默认 *)\n"
        << "  -v, --verbose          向 stderr 输出匹配明细与 AC 词表来源\n"
        << "  -h, --help             显示帮助\n\n"
        << "word.txt: 每行一个词语，空行和 # 开头为注释；AC 只从该文件构建。\n"
        << "审核只对“标题”和“简介”分词，正文不参与分词。\n\n"
        << "动作词表格式: 规范词<TAB>拼音<TAB>别名,别名<TAB>replace|mask|keep\n"
        << "拼音填 - 表示自动生成，填 none 表示仅精确匹配。\n";
}

bool read_text_file(const std::string& path, std::string* text, std::string* error) {
    std::ifstream input(path, std::ios::binary);
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
        if (arg == "--no-pinyin") {
            options->enable_pinyin = false;
        } else if (arg == "-v" || arg == "--verbose") {
            options->verbose = true;
        } else if (arg == "--lexicon") {
            if (!next_value(&options->lexicon_path)) return false;
        } else if (arg == "--word-file") {
            if (!next_value(&options->word_path)) return false;
        } else if (arg == "--input-file") {
            if (!next_value(&options->input_path)) return false;
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
                  << " action=" << action_name(match.action) << "\n";
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

    if (options.lexicon_path.empty()) {
        options.lexicon_path = find_data_file(program, "lexicon.txt");
    }
    if (options.lexicon_path.empty()) {
        std::cerr << "error: lexicon not found, use --lexicon <path>\n";
        return 2;
    }

    if (options.pinyin_path.empty()) {
        options.pinyin_path = find_data_file(program, "pinyin_dict.txt");
    }
    if (options.enable_pinyin && options.pinyin_path.empty()) {
        std::cerr << "error: pinyin dictionary not found, use --pinyin-dict <path> "
                     "or --no-pinyin\n";
        return 2;
    }

    text_clean::PinyinDict pinyin;
    if (!options.pinyin_path.empty()) {
        if (!pinyin.load_file(options.pinyin_path, &error)) {
            std::cerr << "error: " << error << "\n";
            return 2;
        }
    }

    const text_clean::Lexicon::PinyinDeriver derive =
        [&pinyin](const std::u32string& word) { return pinyin.to_pinyin(word); };

    text_clean::Lexicon lexicon;
    if (!text_clean::Lexicon::load_file(options.lexicon_path, derive, lexicon, &error)) {
        std::cerr << "error: " << error << "\n";
        return 2;
    }

    if (options.word_path.empty()) {
        options.word_path = find_data_file(program, "word.txt");
    }
    if (options.word_path.empty()) {
        if (options.review) {
            options.word_path = "data/word.txt";
        } else {
            std::cerr << "error: word file not found, use --word-file <path>\n";
            return 2;
        }
    }

    text_clean::WordMaintainer word_table;
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
    config.mask_char = options.mask_char;

    std::optional<std::vector<std::u32string>> ac_words = word_table.words();
    text_clean::TextCleaner cleaner(std::move(lexicon), pinyin, config,
                                    std::move(ac_words));

    if (options.verbose) {
        std::cerr << "ac source: word file (" << word_table.size()
                  << " words) " << options.word_path << "\n";
    }

    const text_clean::CleanResult result = cleaner.clean(text);
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
