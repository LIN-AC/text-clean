#!/usr/bin/env python3
"""挖掘真实 ASR 语料中词库规范词的同音/近音写法。

用于判断 whisper_txt 是否存在可直接用于召回测试的真实识别错误样本。
"""

from __future__ import annotations

import pathlib
import re
import sys
import unicodedata

sys.stdout.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parents[1]
PINYIN = ROOT / "data" / "pinyin_dict.txt"
LEXICON = ROOT / "data" / "lexicon.txt"
WHISPER = ROOT / "whisper_txt"

HAN = re.compile(r"[\u4e00-\u9fff]")


def load_pinyin():
    table = {}
    for line in PINYIN.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cp, _, syllables = line.partition("\t")
        try:
            ch = chr(int(cp, 16))
        except ValueError:
            continue
        first = syllables.split(",")[0].strip()
        if first:
            table[ch] = re.sub(r"[1-5]$", "", first)
    return table


def load_targets():
    out = {}
    for line in LEXICON.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        canonical = cols[0]
        aliases = cols[2].split(",") if len(cols) > 2 and cols[2] else []
        out[canonical] = [canonical] + [a for a in aliases if a]
    return out


def toneless(word, table):
    return [table.get(ch) for ch in word]


def main():
    table = load_pinyin()
    targets = load_targets()
    docs = {p.name: p.read_text(encoding="utf-8") for p in sorted(WHISPER.glob("*.txt"))}
    total_chars = sum(len(re.findall(HAN, t)) for t in docs.values())
    print(f"真实 ASR 语料 {len(docs)} 篇，汉字 {total_chars} 个")
    print()

    for canonical, forms in targets.items():
        if not canonical:
            continue
        want = toneless(canonical, table)
        if any(s is None for s in want):
            continue
        n = len(want)
        exact = {}      # 完全同音（无声调）的其他写法
        for name, text in docs.items():
            for i in range(len(text) - n + 1):
                gram = text[i:i + n]
                if not HAN.fullmatch(gram):
                    continue
                if toneless(gram, table) == want and gram != canonical:
                    exact[gram] = exact.get(gram, 0) + 1
        canon_count = sum(t.count(canonical) for t in docs.values())
        alias_count = {a: sum(t.count(a) for t in docs.values())
                       for a in forms if a != canonical}
        print(f"{canonical} ({' '.join(want)}) 规范写法出现 {canon_count} 次 "
              f"别名 {alias_count or '-'}")
        if exact:
            for gram, c in sorted(exact.items(), key=lambda x: -x[1]):
                ctx = ""
                for text in docs.values():
                    i = text.find(gram)
                    if i >= 0:
                        ctx = text[max(0, i - 10):i + n + 10].replace("\n", "⏎")
                        break
                print(f"    同音不同字: {gram} x{c}  例：…{ctx}…")
        else:
            print("    同音不同字: 无")


if __name__ == "__main__":
    main()
