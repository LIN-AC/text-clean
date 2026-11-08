#!/usr/bin/env python3
"""Offline simulation of a wider AC Keep lock, at full word boundaries.

Mechanism being modelled (no code change, no dictionary change): the AC stage
locks every span it matches (MatchStatus::LockedByAc), and scan_run refuses any
pinyin window that overlaps a locked char (src/text_cleaner.cpp:298,
overlaps_locked). Growing the AC word list therefore removes rewrites — both
false positives and real corrections — for every window touching a locked word.

Input is an existing window dump (E8's `p0/cache/records_final.jsonl`, or the
v1.2.2 one). The dump already excludes spans the *current* AC list locked, so
every number below is the incremental effect of adding more locked words.

Reported per hypothetical lock set:
  blockFP / blockWrong / blockTP — windows the wider lock would refuse;
  sel — blockFP / blockTP. A lock only pays when sel exceeds the current fp:tp,
        because that is the mix it substitutes into the remaining population;
  r:aft — fp:tp after blocking;
  goldL — % of gold error positions that become unreachable (recall ceiling);
  fixA — whole sentences repaired after blocking (baseline is the E8 count);
  and the same run re-scored with csc_eval.score(), i.e. the project's headline
  char-level det_P / cor_P / F0.5, so the route is judged on published metrics.

Re-selection is NOT modelled: a blocked window can be taken over by another
candidate on the same span, so blockFP is an upper bound on the gain and
blockTP is a lower bound on the damage.

Usage:
  python tools/ac_lock_sim.py matrix [--records FILE] [--json OUT]
  python tools/ac_lock_sim.py detail --source word_freq --min-len 2 --min-freq 0
"""
import argparse
import bisect
import collections
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from window_probe import TEST, pairs  # same split list and same row filter
from csc_eval import score  # same char-level metric definition as E3/E8/E9

_PAIR_CACHE = {}


def cached_pairs(split):
    if split not in _PAIR_CACHE:
        _PAIR_CACHE[split] = pairs(split)
    return _PAIR_CACHE[split]

DEFAULT_RECORDS = os.path.join(ROOT, "p0", "cache", "records_final.jsonl")
WORD_FREQ = os.path.join(ROOT, "data", "word_freq.txt")
DICT_TXT = os.path.join(ROOT, "data", "dict.txt")
WORD_TXT = os.path.join(ROOT, "data", "word.txt")
LEXICON = os.path.join(ROOT, "datasets", "ctc_probe_lexicon.txt")


def is_han(ch):
    return "一" <= ch <= "鿿"


def han_only(words):
    return {w: c for w, c in words.items() if len(w) >= 2 and all(is_han(ch) for ch in w)}


def load_word_freq(path=WORD_FREQ):
    """`<word><TAB><frequency>` — the runtime frequency table."""
    out = {}
    for line in io.open(path, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        parts = line.rstrip("\n").rsplit("\t", 1)
        if len(parts) != 2:
            continue
        try:
            out[parts[0]] = int(parts[1])
        except ValueError:
            continue
    return out


def load_dict_txt(path=DICT_TXT):
    """jieba `word freq tag`. The frequency column is the one the project
    currently loads and ignores (status.md P0 item)."""
    out = {}
    for line in io.open(path, encoding="utf-8"):
        parts = line.rstrip("\n").split(" ")
        if len(parts) < 2 or not parts[0]:
            continue
        try:
            out[parts[0]] = int(parts[1])
        except ValueError:
            continue
    return out


def load_word_txt(path=WORD_TXT):
    """The AC list in use today: data/word.txt, one word per line."""
    words = [line.strip() for line in io.open(path, encoding="utf-8")
             if line.strip() and not line.startswith("#")]
    return {w: 3 for w in words if all(is_han(c) for c in w) and len(w) >= 2}


def load_lexicon(path=LEXICON):
    """canonical + aliases of the evaluation lexicon; frequency taken from
    word_freq.txt so the frequency tiers stay comparable."""
    freq = load_word_freq()
    out = {}
    for line in io.open(path, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 4:
            continue
        for word in [parts[0]] + [a for a in parts[2].split(",") if a]:
            if len(word) >= 2 and all(is_han(c) for c in word):
                out[word] = freq.get(word, 3)
    return out


SOURCES = {
    "word_txt": lambda: load_word_txt(),
    "lexicon": lambda: load_lexicon(),
    "word_freq": lambda: han_only(load_word_freq()),
    "dict_txt": lambda: han_only(load_dict_txt()),
}


def lock_sentence(sentence, words, heads, min_len, min_freq, max_len):
    """Forward maximum matching, earliest start then longest — the same
    selection select_exact() makes. A char is locked only when covered by a
    complete word of at least min_len chars and at least min_freq frequency."""
    n = len(sentence)
    owner = [None] * n
    locked = 0
    i = 0
    top = min(max_len, n)
    while i < n:
        hit = 0
        if sentence[i] in heads:
            for length in range(min(top, n - i), min_len - 1, -1):
                count = words.get(sentence[i:i + length])
                if count is not None and count >= min_freq:
                    hit = length
                    break
        if not hit:
            i += 1
            continue
        word = sentence[i:i + hit]
        for k in range(i, i + hit):
            owner[k] = word
        locked += hit
        i += hit
    return owner, locked


def build_locks(sentences, words, min_len, min_freq):
    max_len = max(len(w) for w in words)
    heads = set(w[0] for w in words)
    owners = []
    locked_chars = 0
    han_chars = 0
    for sentence in sentences:
        owner, locked = lock_sentence(sentence, words, heads, min_len, min_freq, max_len)
        owners.append(owner)
        locked_chars += locked
        han_chars += sum(1 for ch in sentence if is_han(ch))
    return owners, locked_chars, han_chars


def load_case(records_path):
    """Dump rows grouped by split, joined to the sentences they came from."""
    rows = collections.defaultdict(list)
    for line in io.open(records_path, encoding="utf-8"):
        record = json.loads(line)
        if record["status"] == "ac_locked" or record["matched"] == record["repl"]:
            continue
        rows[record["split"]].append(record)
    case = {}
    for split in TEST:
        if split not in rows:
            continue
        split_rows = cached_pairs(split)
        starts = [0]
        for source, _ in split_rows:
            starts.append(starts[-1] + len(source) + 1)
        case[split] = (split_rows, starts, rows[split])
    return case


def _apply(source, records):
    result = list(source)
    for record in records:
        result[record["_off"]:record["_off"] + record["_len"]] = list(record["repl"])
    return "".join(result)


def best_free_run(flags):
    """Longest run of not-locked chars inside a blocked window (re-selection
    exposure: a run of >= 2 can still host a shorter candidate window)."""
    best = current = 0
    for locked in flags:
        if locked:
            current = 0
        else:
            current += 1
            best = max(best, current)
    return best


def simulate(case, words, min_len, min_freq, max_dist=2):
    totals = collections.Counter()
    blocked = collections.Counter()
    tp_killers = collections.Counter()
    fp_killers = collections.Counter()
    src_lines = []
    tgt_lines = []
    out_all = []
    out_surv = []

    for split, (split_rows, starts, records) in case.items():
        by_sentence = collections.defaultdict(list)
        for record in records:
            if record["distance"] > max_dist:
                continue
            index = bisect.bisect_right(starts, record["begin"]) - 1
            record["_off"] = record["begin"] - starts[index]
            record["_len"] = record["end"] - record["begin"]
            by_sentence[index].append(record)

        owners, locked_chars, han_chars = build_locks(
            [source for source, _ in split_rows], words, min_len, min_freq)
        totals["locked_chars"] += locked_chars
        totals["han_chars"] += han_chars

        for index, (source, target) in enumerate(split_rows):
            totals["sentences"] += 1
            gold = [k for k in range(len(source)) if source[k] != target[k]]
            totals["gold_positions"] += len(gold)
            owner = owners[index]
            totals["gold_locked"] += sum(1 for k in gold if owner[k] is not None)

            all_records = by_sentence.get(index, [])
            survivors = []
            for record in all_records:
                lo = record["_off"]
                hi = lo + record["_len"]
                if hi > len(source) or len(record["repl"]) != record["_len"]:
                    continue
                totals["all_" + record["kind"]] += 1
                totals["all_d%d_%s" % (record["distance"], record["kind"])] += 1
                flags = [owner[k] is not None for k in range(lo, hi)]
                if not any(flags):
                    survivors.append(record)
                    continue
                blocked[record["kind"]] += 1
                totals["blk_d%d_%s" % (record["distance"], record["kind"])] += 1
                # Re-selection exposure: a blocked window that still contains a
                # free run of >= 2 chars could be rewritten by a shorter
                # candidate, so the block would not fully remove the rewrite.
                run = best_free_run(flags)
                if run >= 2:
                    totals["mutable_" + record["kind"]] += 1
                label = "%s->%s  锁=%s" % (record["matched"], record["repl"],
                                           next(owner[k] for k in range(lo, hi)
                                                if owner[k] is not None))
                if record["kind"] == "tp":
                    tp_killers[label] += 1
                elif record["kind"] == "fp":
                    fp_killers[label] += 1

            src_lines.append(source)
            tgt_lines.append(target)
            out_all.append(_apply(source, all_records))
            out_surv.append(_apply(source, survivors))

    totals["tp_killers"] = tp_killers
    totals["fp_killers"] = fp_killers
    totals["char_base"] = score(src_lines, out_all, tgt_lines)
    totals["char_after"] = score(src_lines, out_surv, tgt_lines)
    return blocked, totals


def evaluate(case, source_name, min_len, min_freq, max_dist=2):
    words = SOURCES[source_name]()
    blocked, totals = simulate(case, words, min_len, min_freq, max_dist)
    fp0, tp0, wr0 = totals["all_fp"], totals["all_tp"], totals["all_wrong"]
    fp, tp = fp0 - blocked["fp"], tp0 - blocked["tp"]
    base, aft = totals["char_base"], totals["char_after"]
    dist = {}
    for d in (0, 1, 2):
        dist[d] = dict(fp_all=totals["all_d%d_fp" % d],
                       fp_blk=totals["blk_d%d_fp" % d],
                       tp_all=totals["all_d%d_tp" % d],
                       tp_blk=totals["blk_d%d_tp" % d],
                       wrong_all=totals["all_d%d_wrong" % d],
                       wrong_blk=totals["blk_d%d_wrong" % d])
    return dict(source=source_name, entries=len(words), min_len=min_len,
                min_freq=min_freq,
                lock_pct=100.0 * totals["locked_chars"] / max(1, totals["han_chars"]),
                block_fp=blocked["fp"], block_wrong=blocked["wrong"],
                block_tp=blocked["tp"],
                mut_fp=totals["mutable_fp"], mut_tp=totals["mutable_tp"],
                dist=dist,
                fp_pct=100.0 * blocked["fp"] / max(1, fp0),
                tp_pct=100.0 * blocked["tp"] / max(1, tp0),
                sel=blocked["fp"] / max(1, blocked["tp"]),
                ratio_before=fp0 / max(1, tp0),
                ratio_after=fp / max(1, tp),
                keep_tp=100.0 * tp / max(1, tp0),
                gold_locked_pct=100.0 * totals["gold_locked"] / max(1, totals["gold_positions"]),
                fixed_before=base["sent_ok"], fixed_after=aft["sent_ok"],
                sentences=totals["sentences"],
                char_base=base, char_after=aft,
                _killers=totals["tp_killers"], _fpkillers=totals["fp_killers"])


WINDOW_HEADER = ("%-9s %4s %6s %6s %8s %8s %8s %7s %7s %6s %6s %6s %6s %6s %6s %6s" %
                 ("source", "len", "freq", "lock%", "blkFP", "blkWr", "blkTP",
                  "mutFP", "mutTP", "FP%", "TP%", "sel", "r:aft", "keepT", "goldL", "fixA"))

CHAR_HEADER = ("%-9s %4s %6s %7s %7s %7s %8s %8s %8s %6s %6s %6s %6s %6s %6s %6s" %
               ("source", "len", "freq", "detTPb", "detTPa", "dTP", "detFPb",
                "detFPa", "dFP", "detPb", "detPa", "corPb", "corPa", "F05b",
                "F05a", "dsent"))

DIST_HEADER = ("%-9s %4s %6s %3s %7s %7s %6s %7s %7s %6s %6s" %
               ("source", "len", "freq", "d", "fpAll", "fpBlk", "fpBlk%",
                "tpAll", "tpBlk", "tpBlk%", "sel"))


def window_fmt(row):
    return ("%-9s %4d %6d %6.1f %8d %8d %8d %7d %7d %6.1f %6.1f %6.2f %6.2f %6.1f %6.1f %6d" % (
        row["source"], row["min_len"], row["min_freq"], row["lock_pct"],
        row["block_fp"], row["block_wrong"], row["block_tp"], row["mut_fp"],
        row["mut_tp"], row["fp_pct"], row["tp_pct"], row["sel"], row["ratio_after"],
        row["keep_tp"], row["gold_locked_pct"], row["fixed_after"]))


def char_fmt(row):
    b, a = row["char_base"], row["char_after"]
    return ("%-9s %4d %6d %7d %7d %+7d %8d %8d %+8d %6.4f %6.4f %6.4f %6.4f %6.4f %6.4f %+6d" % (
        row["source"], row["min_len"], row["min_freq"], b["det_tp"], a["det_tp"],
        a["det_tp"] - b["det_tp"], b["det_fp"], a["det_fp"], a["det_fp"] - b["det_fp"],
        b["det_p"], a["det_p"], b["cor_p"], a["cor_p"], b["cor_f05"], a["cor_f05"],
        a["sent_ok"] - b["sent_ok"]))


def dist_rows(row):
    out = []
    for d in (0, 1, 2):
        g = row["dist"][d]
        out.append("%-9s %4d %6d %3d %7d %7d %6.1f %7d %7d %6.1f %6.2f" % (
            row["source"], row["min_len"], row["min_freq"], d,
            g["fp_all"], g["fp_blk"], 100.0 * g["fp_blk"] / max(1, g["fp_all"]),
            g["tp_all"], g["tp_blk"], 100.0 * g["tp_blk"] / max(1, g["tp_all"]),
            g["fp_blk"] / max(1, g["tp_blk"])))
    return out


def variants():
    for source in ("word_txt", "lexicon", "word_freq", "dict_txt"):
        for min_len in (2, 3):
            for min_freq in (0, 1000):
                yield source, min_len, min_freq
    for min_freq in (100, 10000, 100000):
        yield "word_freq", 2, min_freq
    yield "dict_txt", 4, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["matrix", "detail"])
    ap.add_argument("--records", default=DEFAULT_RECORDS)
    ap.add_argument("--source", default="word_freq")
    ap.add_argument("--min-len", type=int, default=2)
    ap.add_argument("--min-freq", type=int, default=0)
    ap.add_argument("--max-dist", type=int, default=2,
                    help="drop records with distance > N before scoring, i.e. "
                         "measure the lock combined with a distance cap")
    ap.add_argument("--json", default=None)
    ap.add_argument("--show-killers", type=int, default=12)
    args = ap.parse_args()

    case = load_case(args.records)
    print("records:", args.records)

    if args.cmd == "detail":
        row = evaluate(case, args.source, args.min_len, args.min_freq, args.max_dist)
        print("max_dist:", args.max_dist)
        print(WINDOW_HEADER)
        print(window_fmt(row))
        print(CHAR_HEADER)
        print(char_fmt(row))
        print(DIST_HEADER)
        for line in dist_rows(row):
            print(line)
        print("\nTP killed by the lock (count, window, which word locked it):")
        for label, count in row["_killers"].most_common(args.show_killers):
            print("  %6d  %s" % (count, label))
        print("\nFP blocked:")
        for label, count in row["_fpkillers"].most_common(args.show_killers):
            print("  %6d  %s" % (count, label))
        return

    rows = []
    print("== window level (one row = one rewrite window the run applied) ==")
    print(WINDOW_HEADER)
    print("-" * len(WINDOW_HEADER))
    for source, min_len, min_freq in variants():
        row = evaluate(case, source, min_len, min_freq, args.max_dist)
        rows.append(row)
        print(window_fmt(row))
    print()
    print("== char-level CSC, same definition as csc_eval.py (b=baseline, a=after lock, dsent=delta sentences fixed) ==")
    print(CHAR_HEADER)
    print("-" * len(CHAR_HEADER))
    for row in rows:
        print(char_fmt(row))
    print()
    print("== blocked share by pinyin distance (rows with >=1000 FP blocked) ==")
    print(DIST_HEADER)
    print("-" * len(DIST_HEADER))
    for row in rows:
        if row["block_fp"] >= 1000:
            for line in dist_rows(row):
                print(line)

    if args.json:
        io.open(args.json, "w", encoding="utf-8").write(json.dumps(
            [{k: v for k, v in row.items() if not k.startswith("_")}
             for row in rows], ensure_ascii=False, indent=1))
        print("wrote", args.json)


if __name__ == "__main__":
    main()
