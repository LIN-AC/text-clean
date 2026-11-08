#!/usr/bin/env python3
"""Window-level fp/tp probe for the pinyin/fuzzy rewrite channel.

Each -v diagnostic line carries the window offsets, the matched text, the
replacement, distance, dS and both frequencies. Joining those with the gold
target of the sentence gives a *window-level* label for every rewrite:

  fp    the window text already equals the gold text (it was correct)
  tp    the replacement equals the gold text (a real correction)
  wrong changed, but neither matched nor replacement is gold

This is the measurement used by E7/E8 in agents/EXPERIMENTS.md, but derived from
the diagnostics instead of a positional stdout diff, so it does not merge
adjacent rewrites into longer spans.

Usage:
  python tools/window_probe.py dump --out p0/cache/records.jsonl
  python tools/window_probe.py report --in p0/cache/records.jsonl

The binary defaults to build-probe/text_clean.exe; override with --exe or the
TC_EXE environment variable (that is how different builds are compared).
"""
import argparse
import bisect
import collections
import io
import json
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "datasets", "CTCDataset")
LEX = os.path.join(ROOT, "datasets", "ctc_probe_lexicon.txt")
TMP = os.environ.get("TC_TMP") or os.path.join(ROOT, "log")
EXE = os.environ.get("TC_EXE") or os.path.join(ROOT, "build-probe", "text_clean.exe")
TEST = ["sighan/sighan13_test", "sighan/sighan14_test", "sighan/sighan15_test",
        "MCSCSet/test", "cscd-ns/test", "cscd-ns/dev",
        "lemon/car", "lemon/cot", "lemon/enc", "lemon/gam", "lemon/mec",
        "lemon/new", "lemon/nov"]
LINE = re.compile(
    r'^\s+\[(\w+)\] status=(\w+) (\d+)\.\.(\d+) "(.*)" -> "(.*)" entry=(\d+) '
    r'distance=(\d+) score=([-0-9.eE]+) logR=([-0-9.eE]+) fC=(\d+) fO=(\d+) '
    r'action=(\w+) context_bonus=([-0-9.eE]+)$')


def pairs(split):
    rows = []
    path = os.path.join(DATA, split + ".jsonl")
    for line in io.open(path, encoding="utf-8"):
        d = json.loads(line)
        if len(d["source"]) == len(d["target"]):
            rows.append((d["source"], d["target"]))
    return rows


def dump_split(split, out):
    rows = pairs(split)
    body = "\n".join(s for s, _ in rows)
    os.makedirs(TMP, exist_ok=True)
    inp = os.path.join(TMP, "_window_probe_in.txt")
    io.open(inp, "w", encoding="utf-8", newline="\n").write(body)
    proc = subprocess.run([EXE, "--input-file", inp, "--lexicon", LEX, "-v"],
                          capture_output=True, cwd=ROOT)
    starts = [0]
    for source, _ in rows:
        starts.append(starts[-1] + len(source) + 1)
    n = 0
    skipped = 0
    text_mismatch = 0
    for raw in proc.stderr.decode("utf-8", "replace").splitlines():
        m = LINE.match(raw)
        if not m:
            continue
        (kind, status, begin, end, matched, repl, entry, distance, score,
         logr, fc, fo, action, bonus) = m.groups()
        begin, end = int(begin), int(end)
        si = bisect.bisect_right(starts, begin) - 1
        if si < 0 or si >= len(rows):
            skipped += 1
            continue
        source, target = rows[si]
        offset = begin - starts[si]
        if source[offset:offset + (end - begin)] != matched:
            # The span does not point at the text it names: the diagnostic
            # offsets are unusable, so stop rather than mislabel the record.
            text_mismatch += 1
            continue
        gold = target[offset:offset + (end - begin)]
        if len(gold) != end - begin:
            # The diagnostic span does not align with this sentence's code
            # points: do not guess a label for it.
            skipped += 1
            continue
        label = "fp" if matched == gold else ("tp" if repl == gold else "wrong")
        out.write(json.dumps(dict(split=split, begin=begin, end=end, matched=matched,
                                  repl=repl, gold=gold, kind=label,
                                  distance=int(distance), score=float(score),
                                  fC=int(fc), fO=int(fo), action=action,
                                  status=status, match_kind=kind),
                             ensure_ascii=False) + "\n")
        n += 1
    print("%-24s rows=%-6d matches=%-6d text_mismatch=%-5d skipped=%d" % (
        split, len(rows), n, text_mismatch, skipped))


def load(path):
    rows = [json.loads(line) for line in io.open(path, encoding="utf-8")]
    return [r for r in rows if r["status"] != "ac_locked" and r["matched"] != r["repl"]]


def report(path):
    rows = load(path)
    c = collections.Counter(r["kind"] for r in rows)
    print("rewrites=%d fp=%d tp=%d wrong=%d  fp:tp=%.2f  precision=%.3f" % (
        len(rows), c["fp"], c["tp"], c["wrong"], c["fp"] / max(1, c["tp"]),
        c["tp"] / max(1, len(rows))))
    print("%-10s %8s %8s %8s %9s" % ("distance", "fp", "tp", "wrong", "fp:tp"))
    by = collections.defaultdict(collections.Counter)
    for r in rows:
        by[r["distance"]][r["kind"]] += 1
    for d in sorted(by):
        g = by[d]
        print("%-10d %8d %8d %8d %9.2f" % (d, g["fp"], g["tp"], g["wrong"],
                                           g["fp"] / max(1, g["tp"])))
    print("%-10s %8s %8s %8s %9s" % ("window", "fp", "tp", "wrong", "fp:tp"))
    by = collections.defaultdict(collections.Counter)
    for r in rows:
        by[len(r["matched"])][r["kind"]] += 1
    for k in sorted(by):
        g = by[k]
        print("%-10d %8d %8d %8d %9.2f" % (k, g["fp"], g["tp"], g["wrong"],
                                           g["fp"] / max(1, g["tp"])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dump", "report"])
    ap.add_argument("--out", default=os.path.join(TMP, "window_records.jsonl"))
    ap.add_argument("--in", dest="inp", default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("--exe", default=None)
    a = ap.parse_args()
    global EXE
    if a.exe:
        EXE = a.exe
    if a.cmd == "report":
        report(a.inp or a.out)
        return
    os.makedirs(TMP, exist_ok=True)
    with io.open(a.out, "w", encoding="utf-8", newline="\n") as out:
        for split in TEST:
            if a.only and a.only not in split:
                continue
            dump_split(split, out)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
