#!/usr/bin/env python3
"""Generate data/pinyin_dict.txt from the locally installed pypinyin package.

Format: <hex codepoint><TAB><syllable>[,<syllable>...]
Readings are lowercase ASCII with a tone number 1-5; neutral tone is 5 and
"v" stands for "ü".
"""

import json
import os
import re
import sys

try:
    import pypinyin
    from pypinyin import Style, pinyin
except ImportError:
    sys.exit("pypinyin is required: pip install pypinyin")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(ROOT, "data", "pinyin_dict.txt")


def is_han(cp: int) -> bool:
    return (
        0x4E00 <= cp <= 0x9FFF
        or 0x3400 <= cp <= 0x4DBF
        or 0xF900 <= cp <= 0xFAFF
        or 0x20000 <= cp <= 0x2FA1F
        or cp == 0x3007
    )


def readings_for(char: str):
    readings = []
    for raw in pinyin(char, style=Style.TONE3, heteronym=True)[0]:
        syllable = raw.strip().lower()
        if not re.fullmatch(r"[a-z]+[1-5]?", syllable):
            continue
        if syllable[-1] not in "12345":
            syllable += "5"  # pypinyin omits the neutral-tone digit
        if syllable not in readings:
            readings.append(syllable)
    return readings


def main() -> None:
    dict_path = os.path.join(os.path.dirname(pypinyin.__file__), "pinyin_dict.json")
    with open(dict_path, encoding="utf-8") as handle:
        source = json.load(handle)

    rows = []
    for key in sorted(source, key=int):
        codepoint = int(key)
        if not is_han(codepoint):
            continue
        readings = readings_for(chr(codepoint))
        if readings:
            rows.append(f"{codepoint:04x}\t{','.join(readings)}")

    version = getattr(pypinyin, "__version__", "unknown")
    header = [
        "# Pinyin readings generated from pypinyin "
        f"{version} (MIT License).",
        "# Source: https://github.com/mozillazg/python-pinyin",
        "# Format: <hex codepoint><TAB><syllable>[,<syllable>...]",
        "# Syllables are lowercase ASCII with tone 1-5 (5 = neutral); v = ü.",
        "",
    ]
    with open(OUTPUT, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(header + rows) + "\n")
    print(f"wrote {len(rows)} characters to {OUTPUT}")


if __name__ == "__main__":
    main()
