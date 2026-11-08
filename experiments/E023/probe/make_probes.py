#!/usr/bin/env python3
"""Generate ablation + funnel probe copies of src/text_cleaner.cpp.

Each probe changes exactly one rule and nothing else; anchors are matched by
unique string, and the script aborts if any anchor is not found exactly once.
Production source is never touched.
"""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC = (ROOT / "src" / "text_cleaner.cpp").read_text(encoding="utf-8")
OUT = ROOT / "experiments" / "E023" / "probe"
OUT.mkdir(parents=True, exist_ok=True)

A_WINDOW = "        for (const Window& window : windows) {\n"
A_MISSING_ORIG = ("            if(frequencies.is_zipf() && !original_zipf) continue;"
                  " // no fabricated evidence for KEEP\n")
A_MISSING_CAND = "                if(frequencies.is_zipf() && !candidate_zipf) continue;\n"
A_LOGRATIO = "                    ? 2.302585 * (*candidate_zipf - *original_zipf)\n"
A_NO_CAND = "            if (candidates.empty()) continue;\n"
A_FIRST = "            if (config.require_first_syllable_match && !has_base(text[window.begin], first_bases)) continue;\n"
A_DIST = "                if(distance>config.max_pinyin_distance || (window.edge && distance>1)) continue;\n"
A_EDGE = "                if (window.edge) {\n"
A_EDGE1 = "                    if(candidate.shared_syllables!=length) continue;\n"
A_EDGE2 = "                    if(changed!=1) continue;\n"
A_ACTION = "                if (entry.action != Action::Replace || entry.canonical.size()!=length) continue;\n"
A_PROTECT = "                if(protected_change) continue;\n"
A_SCORE = "                if (!(score > 0.0)) continue;\n"
A_COMPETE = ("            if (local[best].score > keep_score &&\n"
             "                (j == i + 1 || local[best].score - runner > config.modification_threshold))\n"
             "                out.push_back(local[best]);\n")
INCLUDES = "#include <algorithm>\n"

FUNNEL_DECL = '''namespace {
struct Funnel {
    long windows = 0, first_gate = 0, no_candidate = 0, missing_orig = 0, missing_cand = 0,
         action_rej = 0, protected_rej = 0, edge_rej = 0, dist_rej = 0, score_rej = 0,
         accepted = 0, singleton = 0, margin_win = 0, group_veto = 0, keep_win = 0;
    ~Funnel() {
        if (getenv("TC_FUNNEL"))
            fprintf(stderr,
                    "#FUNNEL windows=%ld first_gate=%ld no_candidate=%ld missing_orig=%ld "
                    "missing_cand=%ld action_rej=%ld protected_rej=%ld edge_rej=%ld dist_rej=%ld "
                    "score_rej=%ld accepted=%ld singleton=%ld margin_win=%ld group_veto=%ld "
                    "keep_win=%ld\\n",
                    windows, first_gate, no_candidate, missing_orig, missing_cand, action_rej,
                    protected_rej, edge_rej, dist_rej, score_rej, accepted, singleton, margin_win,
                    group_veto, keep_win);
    }
} funnel;
}  // namespace

'''


def patch(text: str, anchor: str, replacement: str, label: str) -> str:
    count = text.count(anchor)
    if count != 1:
        sys.exit("anchor not unique (%d) for %s" % (count, label))
    return text.replace(anchor, replacement)


def bump(text: str, anchor: str, field: str, label: str) -> str:
    """把单行 `if (cond) continue;`（可带行尾注释）改写成
    `if (cond) { ++funnel.field; continue; }`，只统计真正被该分支拦下的次数。"""
    stripped = anchor.rstrip("\n")
    if " continue;" not in stripped or not stripped.lstrip().startswith("if"):
        sys.exit("bump anchor is not an `if ... continue;` line: %s" % label)
    head, tail = stripped.split(" continue;", 1)
    return patch(text, anchor, head + " { ++funnel.%s; continue; }" % field + tail + "\n", label)


def loop_entry(text: str, anchor: str, field: str, label: str) -> str:
    """循环体第一行插入计数（anchor 必须是以 `{` 结尾的 for 行）。"""
    if not anchor.rstrip("\n").endswith("{"):
        sys.exit("loop_entry anchor must end with a brace: %s" % label)
    indent = " " * (len(anchor) - len(anchor.lstrip()) + 4)
    return patch(text, anchor, anchor.rstrip("\n") + "\n" + indent + "++funnel.%s;\n" % field, label)


def add_includes(text: str) -> str:
    return patch(text, INCLUDES, INCLUDES + "#include <cstdio>\n#include <cstdlib>\n", "includes")


# --- B: 恢复旧缺频策略（原文缺 Zipf 不弃权，按"机会为 0"给满额） ---
b = add_includes(SRC)
b = patch(b, A_MISSING_ORIG,
          "            const double zipf_used = original_zipf ? *original_zipf : 0.0;  // ABLATION-B\n",
          "B-missing-orig")
b = patch(b, A_LOGRATIO, "                    ? 2.302585 * (*candidate_zipf - zipf_used)\n", "B-logratio")
(OUT / "text_cleaner_B.cpp").write_text(b, encoding="utf-8")

# --- C: 恢复旧字符频率补偿（原文缺 Zipf 时按字频独立估计） ---
c = add_includes(SRC)
c = patch(c, INCLUDES + "#include <cstdio>\n#include <cstdlib>\n",
          INCLUDES + "#include <cstdio>\n#include <cstdlib>\n#include <fstream>\n#include <map>\n",
          "C-includes")
c = patch(c, "}  // namespace\n",
          '''std::map<char32_t, double>& char_zipf_table() {
    static std::map<char32_t, double> table;
    if (table.empty()) {
        const char* path = getenv("TC_CHAR_FREQ");
        if (path) {
            std::ifstream in(path, std::ios::binary);
            std::string line;
            while (std::getline(in, line)) {
                if (!line.empty() && line.back() == '\\r') line.pop_back();
                if (line.empty() || line.front() == '#') continue;
                std::size_t t1 = line.find('\\t');
                std::size_t t2 = line.find('\\t', t1 + 1);
                std::size_t t5 = line.find('\\t', line.find('\\t', t2 + 1) + 1);
                if (t1 == std::string::npos || t2 == std::string::npos) continue;
                std::string ch = line.substr(0, t1);
                if (ch.size() < 2 || ch == "char") continue;
                std::string gen = line.substr(t1 + 1, t2 - t1 - 1);
                std::string src = t5 == std::string::npos ? "" : line.substr(t5 + 1);
                if (src.find("wordfreq") == std::string::npos) continue;
                try {
                    double value = std::stod(gen);
                    if (value > 0 && value <= 10) {
                        auto points = utf8::decode(ch);
                        if (points.size() == 1) table[points[0]] = value;
                    }
                } catch (...) {
                }
            }
        }
    }
    return table;
}
}  // namespace
''', "C-loader-anchor")
c = patch(c, A_MISSING_ORIG,
          '''            double zipf_used = original_zipf ? *original_zipf : 0.0;
            if (frequencies.is_zipf() && !original_zipf) {  // ABLATION-C
                auto& table = char_zipf_table();
                double sum = 0.0;
                bool ok = true;
                for (auto ch : original) {
                    auto it = table.find(ch);
                    if (it == table.end()) { ok = false; break; }
                    sum += it->second;
                }
                if (!ok) continue;
                zipf_used = sum - 9.0 * static_cast<double>(length - 1);
            }
''', "C-missing-orig")
c = patch(c, A_LOGRATIO, "                    ? 2.302585 * (*candidate_zipf - zipf_used)\n", "C-logratio")
(OUT / "text_cleaner_C.cpp").write_text(c, encoding="utf-8")

# --- F: 漏斗计数器（行为不变，只计数） ---
f = add_includes(SRC)
f = patch(f, "namespace text_clean {\nnamespace {\n",
          "namespace text_clean {\n" + FUNNEL_DECL + "namespace {\n", "F-namespace")
f = loop_entry(f, A_WINDOW, "windows", "F-windows")
f = bump(f, A_FIRST, "first_gate", "F-first")
f = bump(f, A_NO_CAND, "no_candidate", "F-no-candidate")
f = bump(f, A_MISSING_ORIG, "missing_orig", "F-missing-orig")
f = bump(f, A_MISSING_CAND, "missing_cand", "F-missing-cand")
f = bump(f, A_ACTION, "action_rej", "F-action")
f = bump(f, A_PROTECT, "protected_rej", "F-protect")
f = bump(f, A_EDGE1, "edge_rej", "F-edge-shared")
f = bump(f, A_EDGE2, "edge_rej", "F-edge-changed")
f = bump(f, A_DIST, "dist_rej", "F-dist")
f = bump(f, A_SCORE, "score_rej", "F-score")
f = patch(f, A_COMPETE,
          '''            if (local[best].score <= keep_score) {
                ++funnel.keep_win;
            } else if (j == i + 1) {
                ++funnel.singleton;
                ++funnel.accepted;
                out.push_back(local[best]);
            } else if (local[best].score - runner > config.modification_threshold) {
                ++funnel.margin_win;
                ++funnel.accepted;
                out.push_back(local[best]);
            } else {
                ++funnel.group_veto;
            }
''', "F-compete")
(OUT / "text_cleaner_F.cpp").write_text(f, encoding="utf-8")

print("probe 生成完成：B=旧缺频策略 C=旧字符频率补偿 F=漏斗计数器")
for name in sorted(p.name for p in OUT.glob("text_cleaner_*.cpp")):
    print("  ", name)
