#!/usr/bin/env python3
"""Measure how much of the false-positive mass comes from minority readings.

Motivation: text_clean scores a candidate against EVERY reading a character has
in data/pinyin_dict.txt, so a literary/rare reading (e.g. 有 = wei3) opens a
near-homophone path that lets correct text be rewritten. CyIME's
tools/ime_lab/reading_table.py penalises a reading by ln(reading evidence /
main-reading evidence of that SAME word entry) instead of trusting all readings
equally. This probe rebuilds that evidence from our own tables -- pypinyin's
word-level reading table weighted by data/word_freq.txt -- and replays the
matches text_clean produced on a labelled corpus to ask: at threshold tau, how
many false positives die and how many true positives die with them.

Read-only: it does not touch src/. Requires a built text_clean.exe and
datasets/ctc_probe_lexicon.txt (see tools/csc_eval.py build-lex).

  python tools/reading_freq_probe.py [--only cscd-ns/test] [--limit 2000]
"""
import argparse, json, math, os, re, subprocess, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "datasets", "CTCDataset")
LEX = os.path.join(ROOT, "datasets", "ctc_probe_lexicon.txt")
EXE = os.path.join(ROOT, "build-probe", "text_clean.exe")
DIAG = re.compile(r"\s*\[(\w+)\] status=(\S+) (\d+)\.\.(\d+) \"(.*?)\" -> \"(.*?)\" "
                  r"entry=\d+ distance=(\d+) score=([-\d.e+]+)")
HAN = re.compile(r"[㐀-鿿]+")


def char_readings():
    """our table, exactly as the C++ sees it: char -> [syllable with tone digit]"""
    out = {}
    for line in open(os.path.join(ROOT, "data", "pinyin_dict.txt"), encoding="utf-8"):
        if line.startswith("#") or "\t" not in line:
            continue
        k, v = line.rstrip("\n").split("\t", 1)
        try:
            out[chr(int(k, 16))] = [r.strip() for r in v.split(",") if r.strip()]
        except ValueError:
            pass
    return out


def word_freq():
    f = {}
    for line in open(os.path.join(ROOT, "data", "word_freq.txt"), encoding="utf-8"):
        p = line.split()
        if len(p) >= 2:
            try:
                f[p[0]] = int(p[1])
            except ValueError:
                pass
    return f


def reading_evidence(freq):
    """(char, reading) -> word frequency, over EVERY reading the word table attests.

    heteronym=True is the point: a word contributes to all of its attested
    readings, weighted by the word's own frequency, so 行走 and 银行 both feed
    行. Collapsing each word to its single default reading degenerates the
    relative frequency into a plain membership test.
    """
    from pypinyin import pinyin, Style
    ev = collections.defaultdict(float)
    words = [w for w in freq if len(w) >= 1 and HAN.fullmatch(w)]
    for w in words:
        syl = pinyin(w, style=Style.TONE3, heteronym=True)
        if len(syl) != len(w):
            continue
        weight = max(freq[w], 1)
        for ch, variants in zip(w, syl):
            for sy in set(variants):
                ev[(ch, sy)] += weight
    top = collections.defaultdict(float)
    for (ch, r), v in ev.items():
        top[ch] = max(top[ch], v)
    return ev, top


def log_share(ch, reading, ev, top):
    """ln(max(evidence,1) / main-reading evidence) -- <= 0, more negative = rarer"""
    if ch not in top:
        return None
    return math.log(max(ev.get((ch, reading), 0.0), 1.0) / top[ch])


def base(r):
    return r.rstrip("0123456789")


def lev(a, b, maxd=1):
    if abs(len(a) - len(b)) > maxd:
        return maxd + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def canonical_syllables(word, cache):
    if word not in cache:
        from pypinyin import pinyin, Style
        cache[word] = [s[0] for s in pinyin(word, style=Style.TONE3)]
    return cache[word] if len(cache[word]) == len(word) else None


def collect(only, limit):
    """Recover (src span -> replacement) pairs by diffing stdout against the input.

    The CLI's -v span offsets are NOT code-point offsets into the input (verified:
    only 2 of 137 reported spans match the text at those offsets), so pairs are
    reconstructed positionally instead. That is safe because every Replace keeps
    length (candidate syllable count == window length), so runs of differing
    characters are exactly the rewritten spans.
    """
    rows = []
    targets = [f for f in sorted(glob_datasets()) if not only or only in f]
    for t in targets:
        pairs = []
        for line in open(os.path.join(DATA, t + ".jsonl"), encoding="utf-8"):
            d = json.loads(line)
            if len(d["source"]) == len(d["target"]):
                pairs.append((d["source"], d["target"]))
            if limit and len(pairs) >= limit:
                break
        if not pairs:
            continue
        body = "\n".join(s for s, _ in pairs)
        inp = os.path.join(ROOT, "log", "_rf_in.txt")
        open(inp, "w", encoding="utf-8").write(body)
        p = subprocess.run([EXE, "--input-file", inp, "--lexicon", LEX,
                            "--word-freq", os.path.join(ROOT, "data", "word_freq.txt"),
                            "--pinyin-dict", os.path.join(ROOT, "data", "pinyin_dict.txt"),
                            "--vocabulary", os.path.join(ROOT, "data", "dict.txt")],
                           capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
        outs = p.stdout.split("\n")
        for si, (s_src, s_tgt) in enumerate(pairs):
            if si >= len(outs) or len(outs[si]) != len(s_src):
                continue
            o = outs[si]
            j = 0
            while j < len(s_src):
                if o[j] == s_src[j]:
                    j += 1
                    continue
                k = j
                while k < len(s_src) and o[k] != s_src[k]:
                    k += 1
                rows.append(dict(dataset=t, src=s_src[j:k], dst=o[j:k],
                                 tgt=s_tgt[j:k], start=j, sentence=s_src))
                j = k
        os.unlink(inp)
    return rows


def glob_datasets():
    for d in sorted(os.listdir(DATA)):
        sub = os.path.join(DATA, d)
        if os.path.isdir(sub):
            for f in sorted(os.listdir(sub)):
                if f.endswith(".jsonl"):
                    yield "%s/%s" % (d, f[:-6])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="cscd-ns/test")
    ap.add_argument("--limit", type=int, default=2000)
    a = ap.parse_args()
    if not os.path.exists(EXE) or not os.path.exists(LEX):
        sys.exit("need build-probe/text_clean.exe and datasets/ctc_probe_lexicon.txt")
    CR, FREQ = char_readings(), word_freq()
    ev, top = reading_evidence(FREQ)
    poly = sum(1 for ch in CR if len({base(r) for r in CR[ch]}) > 1)
    print("reading evidence: %d (char,reading) cells over %d chars seen in word readings"
          % (len(ev), len(top)))
    print("chars in pinyin_dict with >1 base reading: %d / %d (%.1f%%)"
          % (poly, len(CR), 100 * poly / max(1, len(CR))))

    rows = collect(a.only, a.limit)
    cache = {}
    labelled = []
    for r in rows:
        cans = canonical_syllables(r["dst"], cache)
        if not cans:
            continue
        src, dst, tgt = r["src"], r["dst"], r["tgt"]
        if not (len(src) == len(dst) == len(tgt)):
            continue
        tags = []
        for i, (a_ch, b_ch) in enumerate(zip(src, dst)):
            if a_ch == b_ch or i >= len(cans):
                continue
            comp = [rd for rd in CR.get(a_ch, []) if lev(base(rd), base(cans[i]), 1) <= 1]
            if not comp:
                continue
            best = max(comp, key=lambda rd: ev.get((a_ch, rd), 0.0))
            ls = log_share(a_ch, best, ev, top)
            if ls is None:
                continue
            tags.append(dict(ch=a_ch, want=b_ch, gold=tgt[i], reading=best, log=ls,
                             ev=ev.get((a_ch, best), 0.0), top=top.get(a_ch, 0.0),
                             fp=(tgt[i] == a_ch), fixed=(tgt[i] == b_ch)))
        if not tags:
            continue
        labelled.append(dict(row=r, tags=tags, min_log=min(t["log"] for t in tags),
                             sum_log=sum(t["log"] for t in tags)))
    n_fp = sum(1 for x in labelled for t in x["tags"] if t["fp"])
    n_tp = sum(1 for x in labelled for t in x["tags"] if t["fixed"])
    print("replayed matches=%d  changed positions: fp=%d tp=%d" % (len(labelled), n_fp, n_tp))

    def auc():
        f = [t["log"] for x in labelled for t in x["tags"] if t["fp"]]
        g = [t["log"] for x in labelled for t in x["tags"] if not t["fp"]]
        if not f or not g:
            return float("nan")
        wins = sum(1 for a in f for b in g if a < b) + 0.5 * sum(1 for a in f for a2 in g if a == a2)
        return wins / (len(f) * len(g))
    print("AUC(rarity of best-compatible reading; fp vs tp) = %.3f" % auc())

    print("\n== kill a match when the evidence rule fires (tau in log units) ==")
    print("%-7s %10s %10s %10s %10s %10s" % ("tau", "fp_dies", "tp_dies", "fp_killed%", "tp_lost%", "match_dies"))
    for tau in (0.0, -0.5, -1.0, -2.0, -3.0, -4.0, -6.0):
        for rule, key in (("min-pos", "min_log"), ("sum", "sum_log")):
            die = [x for x in labelled if x[key] < tau]
            fpk = sum(1 for x in die for t in x["tags"] if t["fp"])
            tpl = sum(1 for x in die for t in x["tags"] if not t["fp"])
            print("%-7.1f %-9s %10d %10d %9.1f%% %9.1f%% %10d" % (
                tau, rule, fpk, tpl, 100 * fpk / max(1, n_fp), 100 * tpl / max(1, n_tp), len(die)))
    print("\nsample of the rarest readings that produced false positives:")
    worst = sorted((t for x in labelled for t in x["tags"] if t["fp"]), key=lambda t: t["log"])[:12]
    for t in worst:
        print("  %s wanted %s via %-6s log=%.2f ev=%.0f top=%.0f" % (
            t["ch"], t["want"], t["reading"], t["log"], t["ev"], t["top"]))


if __name__ == "__main__":
    main()
