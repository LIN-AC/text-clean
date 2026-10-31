#!/usr/bin/env python3
"""正文品牌词缺口收益：现词表 vs 现词表+缺失品牌词，在三档参数下比较误改数量。

Usage: python tools/hotword_gap.py [BV-stem]
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "hg", str(ROOT / "tools" / "hotword_gain.py"))
hg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hg)

# 语料中真实出现、但 word.txt 未收录的专有名词（--review 只分词标题/简介，正文品牌词从未被报出）
GAP = ["联想", "华硕", "荣耀", "京东", "拼多多", "惠普", "戴尔", "机械革命", "雷神",
       "ThinkBook", "MacBook", "微信", "华为", "抖音", "支付宝", "铠侠", "海力士",
       "长江存储", "瑞昱", "转账"]

CONFIGS = [([], "default md=1 mf=3"), (["--min-fuzzy", "2"], "min-fuzzy 2"),
           (["--max-distance", "2"], "max-distance 2")]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    stem = sys.argv[1] if len(sys.argv) > 1 else "BV1cLFSz4ECr"
    path = hg.CORPUS_DIR / f"{stem}.txt"
    src = hg.raw_text(path)
    base = [l.strip() for l in hg.NEW_TABLE.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]

    print(f"\n补入品牌词后的抑制收益（{stem}，原文 {len(src)} 码点）：")
    with tempfile.TemporaryDirectory() as td:
        empty = pathlib.Path(td) / "w0.txt"
        empty.write_text("", encoding="utf-8")
        gap_table = pathlib.Path(td) / "w2.txt"
        gap_table.write_text("\n".join(base + GAP) + "\n", encoding="utf-8")
        for flags, label in CONFIGS:
            h0, _ = hg.run(path, empty, flags)
            h1, o1 = hg.run(path, hg.NEW_TABLE, flags)
            h2, o2 = hg.run(path, gap_table, flags)
            r0, r1, r2 = hg.rewrites(h0), hg.rewrites(h1), hg.rewrites(h2)
            _, wn = hg.locked_points(h2)
            sites = sum(len(v) for v in wn.values())
            print(f"  [{label:>18}] 改写命中 空表 {len(r0)} / 现表 {len(r1)} / "
                  f"补品牌 {len(r2)}（品牌词额外抑制 {len(r1) - len(r2)}）"
                  f" | 改动字符 {hg.out_seed_text_diff(src, o1.rstrip(chr(10)))} -> "
                  f"{hg.out_seed_text_diff(src, o2.rstrip(chr(10)))}"
                  f" | 补品牌后锁定 {sites} 处 / {len(wn)} 词条")
            for b, e, m, r in sorted(set(r1) - set(r2))[:6]:
                print(f"      抑制: \"{m}\" -> \"{r}\"  {hg.ctx(src, b, e)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
