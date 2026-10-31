#!/usr/bin/env python3
"""对比同一篇文本在 seed 词表与动态扩充词表下的 AC 命中收益。

Usage:
  python tools/hotword_gain.py <BV-stem>     # 单篇详细报告
  python tools/hotword_gain.py --scan        # 全语料锁覆盖/改写命中概览
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXE = ROOT / "build-gcc" / "text_clean.exe"
CORPUS_DIR = ROOT / "whisper_txt"
NEW_TABLE = ROOT / "data" / "word.txt"
SEED_TABLE = ROOT / "data" / "word.txt.seed.bak"

HIT_RE = re.compile(
    r'\[(exact|pinyin|fuzzy)\] status=(\S+) (\d+)\.\.(\d+) "(.*?)" -> "(.*?)" '
    r'entry=(\d+) distance=(\d+) action=(\S+)'
)


def run(path: pathlib.Path, table: pathlib.Path, flags=()):
    proc = subprocess.run(
        [str(EXE), "--word-file", str(table), "--lexicon",
         str(ROOT / "data" / "lexicon.txt"), "--pinyin-dict",
         str(ROOT / "data" / "pinyin_dict.txt"), *flags,
         "--input-file", str(path), "-v"],
        capture_output=True, cwd=ROOT)
    stderr = proc.stderr.decode("utf-8", "replace")
    out = proc.stdout.decode("utf-8", "replace")
    hits = [m.groups() for m in HIT_RE.finditer(stderr)]
    return hits, out


def stress(stem: str, flags: list[str]) -> int:
    """放宽拼音/模糊参数后，比较空词表与动态扩充词表的误改数量。"""
    path = CORPUS_DIR / f"{stem}.txt"
    src = raw_text(path)
    with tempfile.TemporaryDirectory() as td:
        empty = pathlib.Path(td) / "empty_word.txt"
        empty.write_text("", encoding="utf-8")
        hits_none, out_none = run(path, empty, flags)
    hits_new, out_new = run(path, NEW_TABLE, flags)
    rw_none = {(b, e, m, r) for b, e, m, r in rewrites(hits_none)}
    rw_new = {(b, e, m, r) for b, e, m, r in rewrites(hits_new)}
    _, wn = locked_points(hits_new)
    print(f"flags: {' '.join(flags)}")
    print(f"误改次数：空词表 {len(rw_none)} -> 动态扩充词表 {len(rw_new)}"
          f"（热词锁定抑制 {len(rw_none - rw_new)} 次）")
    print(f"改动字符数：空 {out_seed_text_diff(src, out_none.rstrip(chr(10)))} -> "
          f"新 {out_seed_text_diff(src, out_new.rstrip(chr(10)))}")
    print(f"命中热词 {len(wn)} 个，锁定 {sum(len(v) for v in wn.values())} 处")
    for b, e, m, r in sorted(rw_none - rw_new):
        print(f"  [被热词抑制] {b}..{e} \"{m}\" -> \"{r}\"  {ctx(src, b, e)}")
    for b, e, m, r in sorted(rw_new - rw_none):
        print(f"  [新表独有]   {b}..{e} \"{m}\" -> \"{r}\"  {ctx(src, b, e)}")
    return 0


def locked_points(hits):
    """被 AC 精确锁定的码点数与词条计数。"""
    spans, words = set(), {}
    for kind, status, begin, end, matched, repl, *_ in hits:
        if status == "ac_locked":
            spans.update(range(int(begin), int(end)))
            words.setdefault(matched, []).append((int(begin), int(end)))
    return spans, words


def rewrites(hits):
    """真正改变文本的命中（替换词与原文不同）。"""
    return [(int(b), int(e), m, r) for _, _, b, e, m, r, *_ in hits if m != r]


def raw_text(path: pathlib.Path):
    return path.read_bytes().decode("utf-8")


def changed_chars(before: str, after: str) -> int:
    n = 0
    for i, (a, b) in enumerate(zip(before, after)):
        if a != b:
            n += 1
    return n + abs(len(before) - len(after))


def ctx(text: str, begin: int, end: int, pad: int = 12) -> str:
    return text[max(0, begin - pad):end + pad].replace("\r", "").replace("\n", "⏎")


def report(stem: str) -> int:
    path = CORPUS_DIR / f"{stem}.txt"
    src = raw_text(path)
    with tempfile.TemporaryDirectory() as td:
        empty = pathlib.Path(td) / "empty_word.txt"
        empty.write_text("", encoding="utf-8")
        hits_none, out_none = run(path, empty)
    hits_seed, out_seed = run(path, SEED_TABLE)
    hits_new, out_new = run(path, NEW_TABLE)

    add_words = [l.strip() for l in NEW_TABLE.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.startswith("#")]
    seed_words = {l.strip() for l in SEED_TABLE.read_text(encoding="utf-8").splitlines()
                  if l.strip() and not l.startswith("#")}
    hot_added = set(add_words) - seed_words

    lock_seed, w_seed = locked_points(hits_seed)
    lock_new, w_new = locked_points(hits_new)
    lock_none, _ = locked_points(hits_none)
    rw_none, rw_seed, rw_new = rewrites(hits_none), rewrites(hits_seed), rewrites(hits_new)
    added_locks = lock_new - lock_seed

    print(f"== {stem}  原文 {len(src)} 码点 ==")
    print(f"词表：seed {len(seed_words)} 条 -> 动态扩充 {len(set(add_words))} 条"
          f"（新增 {len(hot_added)}）")
    print(f"AC 精确命中次数：{len(hits_seed)} -> {len(hits_new)}"
          f"（+{len(hits_new) - len(hits_seed)}）")
    print(f"AC 锁定码点：{len(lock_seed)} -> {len(lock_new)}"
          f"（+{len(added_locks)}，占原文 {len(added_locks) / len(src) * 100:.2f}%）")
    print(f"锁定覆盖原文比例：{len(lock_seed) / len(src) * 100:.2f}% -> "
          f"{len(lock_new) / len(src) * 100:.2f}%")
    print(f"改写型命中（matched != replacement）："
          f"空词表 {len(rw_none)} / seed {len(rw_seed)} / 新表 {len(rw_new)}")
    print(f"被锁定抑制掉的改写：空词表 -> 新表 抑制 {len(rw_none) - len(rw_new)} 次")
    print(f"输出与原文差异字符数：空 {changed_chars(src, out_none.rstrip(chr(10)))} / "
          f"seed {changed_chars(src, out_seed.rstrip(chr(10)))} / "
          f"新 {changed_chars(src, out_new.rstrip(chr(10)))}")
    print(f"清洗结果是否随词表变化：{'是' if out_seed != out_new else '否'}"
          f"（空表 vs 新表：{'是' if out_none != out_new else '否'}）")

    print("\n-- 新词表新增命中的词条（seed 表未命中）--")
    gained = [(w, len(pos)) for w, pos in w_new.items() if w not in w_seed]
    for w, c in sorted(gained, key=lambda x: -x[1]):
        tag = "热词" if w in hot_added else "seed"
        first = w_new[w][0]
        print(f"  {tag}  {w}  x{c}  首次 {first[0]}..{first[1]}  "
              f"{ctx(src, first[0], first[1])}")
    print(f"  合计新增命中词条 {len(gained)} 个，命中 "
          f"{sum(c for _, c in gained)} 次")

    print("\n-- seed 表已命中的词条 --")
    for w, pos in sorted(w_seed.items(), key=lambda x: -len(x[1])):
        print(f"  {w} x{len(pos)}")

    print("\n-- 改写型命中明细（空词表 vs seed vs 新表）--")
    none_set, seed_set, new_set = (
        {(b, e, m, r) for b, e, m, r in rw_none},
        {(b, e, m, r) for b, e, m, r in rw_seed},
        {(b, e, m, r) for b, e, m, r in rw_new},
    )
    for key in sorted(none_set | seed_set | new_set):
        b, e, m, r = key
        marks = []
        if key in none_set:
            marks.append("空表")
        if key in seed_set:
            marks.append("seed")
        if key in new_set:
            marks.append("新表")
        mark = "+".join(marks) if len(marks) > 1 else ("仅" + marks[0] + "（被锁定抑制）")
        print(f"  [{mark}] {b}..{e} \"{m}\" -> \"{r}\"  上下文 {ctx(src, b, e)}")

    if out_seed != out_new:
        print("\n-- 清洗输出差异片段 --")
        s, d = out_seed.rstrip("\n"), out_new.rstrip("\n")
        i = 0
        while i < min(len(s), len(d)) and s[i] == d[i]:
            i += 1
        print(f"  首个差异位于码点 {i}")
        print(f"  seed 输出: ...{s[max(0, i-16):i+16]!r}")
        print(f"  新表输出:  ...{d[max(0, i-16):i+16]!r}")
    return 0


def scan() -> int:
    rows = []
    used = set()
    used_new_only = set()
    seed_used = set()
    hot_added = None
    with tempfile.TemporaryDirectory() as td:
        empty = pathlib.Path(td) / "empty_word.txt"
        empty.write_text("", encoding="utf-8")
        new_words = {l.strip() for l in NEW_TABLE.read_text(encoding="utf-8").splitlines()
                     if l.strip() and not l.startswith("#")}
        seed_words = {l.strip() for l in SEED_TABLE.read_text(encoding="utf-8").splitlines()
                      if l.strip() and not l.startswith("#")}
        hot_added = new_words - seed_words
        for path in sorted(CORPUS_DIR.glob("*.txt")):
            src = raw_text(path)
            hits_none, out_none = run(path, empty)
            hits_seed, _ = run(path, SEED_TABLE)
            hits_new, out_new = run(path, NEW_TABLE)
            ls, ws = locked_points(hits_seed)
            ln, wn = locked_points(hits_new)
            seed_used |= set(ws)
            used |= set(wn)
            used_new_only |= {w for w in wn if w in hot_added}
            rows.append((path.stem, len(src), len(hits_seed), len(hits_new),
                         len(ls), len(ln), len(rewrites(hits_none)),
                         len(rewrites(hits_new)), out_seed_text_diff(out_none, out_new)))
    print(f"{'文件':<16}{'码点':>7}{'AC命中':>12}{'锁定码点':>16}"
          f"{'改写(空->新)':>16}{'输出差异':>14}")
    tot_none = tot_new = tot_diff = 0
    for stem, n, hs, hn, lsn, lnn, rn, rnew, diff in rows:
        tot_none += rn
        tot_new += rnew
        tot_diff += diff
        print(f"{stem:<16}{n:>7}{hs:>5}->{hn:<6}{lsn:>7}->{lnn:<8}"
              f"{rn:>6}->{rnew:<6}{diff:>11}")
    print(f"{'合计':<16}{'':>7}{'':>11}{'':>15}{tot_none:>6}->{tot_new:<6}"
          f"{tot_diff:>11}")
    print(f"\n全语料热词利用率：新增 {len(hot_added)} 条中 "
          f"{len(used_new_only)} 条至少命中一次（{len(used_new_only) / len(hot_added) * 100:.0f}%）")
    print(f"  未命中（本语料中的死词条）：{sorted(hot_added - used_new_only)}")
    print(f"seed 18 条中命中 {len(seed_used & seed_words)} 条：{sorted(seed_used & seed_words)}")
    return 0


def out_seed_text_diff(a: str, b: str) -> int:
    """两段清洗输出之间的差异字符数（按码点逐位比较，长度差计入）。"""
    n = sum(1 for x, y in zip(a, b) if x != y)
    return n + abs(len(a) - len(b))


def probe(stem: str, extra: list[str]) -> int:
    """反事实：在当前词表上再补几个候选词，看能抑制多少次误改。"""
    path = CORPUS_DIR / f"{stem}.txt"
    src = raw_text(path)
    base = [l.strip() for l in NEW_TABLE.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]
    with tempfile.TemporaryDirectory() as td:
        table = pathlib.Path(td) / "probe_word.txt"
        table.write_text("\n".join(base + extra) + "\n", encoding="utf-8")
        hits_p, out_p = run(path, table)
    hits_new, out_new = run(path, NEW_TABLE)
    rw_new = {(b, e, m, r) for b, e, m, r in rewrites(hits_new)}
    rw_p = {(b, e, m, r) for b, e, m, r in rewrites(hits_p)}
    print(f"基线词表 {len(set(base))} 条 -> 探针 {len(set(base)) + len(extra)} 条"
          f"（补 {'、'.join(extra)}）")
    print(f"改写型命中：{len(rw_new)} -> {len(rw_p)}（抑制 {len(rw_new) - len(rw_p)} 次）")
    for b, e, m, r in sorted(rw_new - rw_p):
        print(f"  [被抑制] {b}..{e} \"{m}\" -> \"{r}\"  上下文 {ctx(src, b, e)}")
    for b, e, m, r in sorted(rw_p - rw_new):
        print(f"  [新增]   {b}..{e} \"{m}\" -> \"{r}\"  上下文 {ctx(src, b, e)}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] == "--scan":
        sys.exit(scan())
    if len(sys.argv) > 3 and sys.argv[1] == "--probe":
        sys.exit(probe(sys.argv[2], sys.argv[3].split(",")))
    if len(sys.argv) > 3 and sys.argv[1] == "--stress":
        sys.exit(stress(sys.argv[2], sys.argv[3:]))
    stem = sys.argv[1] if len(sys.argv) > 1 else "BV1DaGy6GEQK"
    sys.exit(report(stem))
