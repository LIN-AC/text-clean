#!/usr/bin/env python3
"""Generate data/word_freq.txt from a local jieba dictionary plus hotwords.

The frequency table is used as comparable evidence f(C)/f(O) by the pinyin
scorer. Words from data/word.txt and canonical forms from data/lexicon.txt are
always included and receive at least --hotword-floor, so curated hotwords
absent from the general dictionary still have minimum evidence. Aliases are
not given that floor: their only evidence is their real jieba frequency, so
the error variant does not automatically cancel its canonical form.

Usage:
  python tools/gen_word_freq.py --jieba-dict path/to/jieba/dict.txt
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUTPUT = os.path.join(ROOT, "data", "word_freq.txt")


def is_han(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF
        or 0x3400 <= cp <= 0x4DBF
        or 0xF900 <= cp <= 0xFAFF
        or 0x20000 <= cp <= 0x2FA1F
        or cp == 0x3007
    )


def read_hotwords() -> set[str]:
    words: set[str] = set()
    for name in ("word.txt", "lexicon.txt"):
        path = os.path.join(ROOT, "data", name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                fields = line.split("\t")
                if fields and fields[0].strip():
                    words.add(fields[0].strip())
    return words


def read_jieba(path: str, min_frequency: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split(" ")
            if len(fields) < 2:
                continue
            word = fields[0]
            try:
                frequency = int(fields[1])
            except ValueError:
                continue
            if frequency < min_frequency:
                continue
            if not (2 <= len(word) <= 8) or not all(is_han(ch) for ch in word):
                continue
            counts[word] = max(counts.get(word, 0), frequency)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jieba-dict", required=True, help="path to jieba dict.txt")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--min-frequency", type=int, default=10)
    parser.add_argument("--hotword-floor", type=int, default=3)
    args = parser.parse_args()

    if not os.path.exists(args.jieba_dict):
        sys.exit(f"jieba dictionary not found: {args.jieba_dict}")

    counts = read_jieba(args.jieba_dict, args.min_frequency)
    hotwords = read_hotwords()
    for word in hotwords:
        counts[word] = max(counts.get(word, 0), args.hotword_floor)

    header = [
        "# Word frequencies derived from jieba dict.txt (MIT License).",
        "# Source: https://github.com/fxsjy/jieba",
        f"# jieba entries: Han length 2-8, frequency >= {args.min_frequency}.",
        f"# word.txt words and lexicon canonicals get a floor of {args.hotword_floor}.",
        "# Lexicon aliases keep only their real jieba frequency.",
        "# Format: <word><TAB><frequency>",
        "",
    ]
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(header))
        for word, frequency in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            handle.write(f"{word}\t{frequency}\n")
    print(f"wrote {len(counts)} words to {args.output}")


if __name__ == "__main__":
    main()