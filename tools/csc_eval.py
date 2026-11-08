#!/usr/bin/env python3
"""CTCDataset -> text_clean evaluation corpus.

Chinese spell-checking datasets (CTCDataset, academic-use-only licence) provide
error/correct sentence pairs, which the repo previously had no way to score.
This tool classifies each diff as phonetic / visual / other, keeps the
homophone-type rows that match ASR error shape, builds a Replace lexicon from
the TRAIN splits only, and scores text_clean on held-out TEST splits with the
standard char-level detection/correction P/R/F0.5 metrics.

  python tools/csc_eval.py stats          classify every dataset
  python tools/csc_eval.py build-lex      write datasets/ctc_probe_lexicon.txt
  python tools/csc_eval.py run            score text_clean (both lexicons)
"""
import argparse, collections, json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "datasets", "CTCDataset")
OUT = os.path.join(ROOT, "datasets")
# TC_EXE lets a run target another build without touching this default, so
# several binaries can be scored against the same splits. TC_TMP moves the
# transient input/output files (they are deleted immediately).
EXE = os.environ.get("TC_EXE") or os.path.join(ROOT, "build-probe", "text_clean.exe")
TMP = os.environ.get("TC_TMP") or OUT

TRAIN = ["sighan/sighan13_train", "sighan/sighan14_train", "sighan/sighan15_train",
         "MCSCSet/valid", "ECSpell/ec_law", "ECSpell/ec_med", "ECSpell/ec_odw"]
TEST = ["sighan/sighan13_test", "sighan/sighan14_test", "sighan/sighan15_test",
        "MCSCSet/test", "cscd-ns/test", "cscd-ns/dev",
        "lemon/car", "lemon/cot", "lemon/enc", "lemon/gam", "lemon/mec",
        "lemon/new", "lemon/nov"]

PINYIN = {}
FREQ = {}


def load_tables():
    for line in open(os.path.join(ROOT, "data", "pinyin_dict.txt"), encoding="utf-8"):
        if line.startswith("#") or "\t" not in line:
            continue
        k, v = line.rstrip("\n").split("\t", 1)
        try:
            PINYIN[chr(int(k, 16))] = v.split(",")
        except ValueError:
            pass
    for line in open(os.path.join(ROOT, "data", "word_freq.txt"), encoding="utf-8"):
        p = line.split()
        if len(p) >= 2:
            try:
                FREQ[p[0]] = int(p[1])
            except ValueError:
                FREQ[p[0]] = 0


def base(r):
    return r.rstrip("0123456789")


def tone(r):
    t = r[-1]
    return t if t.isdigit() else "0"


def classify(a, b):
    """wrong char a -> correct char b"""
    ra, rb = PINYIN.get(a) or [], PINYIN.get(b) or []
    if not ra or not rb:
        return "unknown"
    if any(base(x) == base(y) and tone(x) == tone(y) for x in ra for y in rb):
        return "homophone"
    if any(base(x) == base(y) for x in ra for y in rb):
        return "tone"
    if any(levenshtein(base(x), base(y), 1) <= 1 for x in ra for y in rb):
        return "near"
    return "visual"


def levenshtein(a, b, maxd):
    if abs(len(a) - len(b)) > maxd:
        return maxd + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def rows(names):
    for n in names:
        path = os.path.join(DATA, n + ".jsonl")
        if not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8"):
            d = json.loads(line)
            yield n, d["source"], d["target"]


def diff_positions(src, tgt):
    return [i for i in range(min(len(src), len(tgt))) if src[i] != tgt[i]] if len(src) == len(tgt) else None


def is_han(c):
    o = ord(c)
    return 0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF


def stats():
    per = collections.defaultdict(collections.Counter)
    for name, src, tgt in rows(TRAIN + TEST):
        pos = diff_positions(src, tgt)
        if pos is None:
            per[name]["len_mismatch"] += 1
            continue
        kinds = [classify(src[i], tgt[i]) for i in pos]
        c = per[name]
        c["rows"] += 1
        c["clean_rows"] += (1 if not pos else 0)
        c["err_chars"] += len(kinds)
        for k in kinds:
            c[k] += 1
        if pos and all(k in ("homophone", "tone", "near") for k in kinds):
            c["asr_fit_rows"] += 1
            c["asr_fit_spans"] += len({(src[i], tgt[i]) for i in pos})
        if pos and all(k == "homophone" for k in kinds):
            c["pure_homophone_rows"] += 1
    print("%-26s %7s %7s %8s %7s %7s %6s %6s %10s %9s" % (
        "dataset", "rows", "clean", "err_char", "homo", "tone", "near", "visual", "asr_fit", "span_pairs"))
    tot = collections.Counter()
    for name in sorted(per):
        c = per[name]
        print("%-26s %7d %7d %8d %7d %7d %6d %6d %10d %9d" % (
            name, c["rows"], c["clean_rows"], c["err_chars"], c["homophone"], c["tone"],
            c["near"], c["visual"], c["asr_fit_rows"], c["asr_fit_spans"]))
        tot.update(c)
    print("%-26s %7d %7d %8d %7d %7d %6d %6d %10d" % (
        "TOTAL", tot["rows"], tot["clean_rows"], tot["err_chars"], tot["homophone"], tot["tone"],
        tot["near"], tot["visual"], tot["asr_fit_rows"]))
    print("\nphonetic share of all error chars: %.1f%%" % (
        100 * (tot["homophone"] + tot["tone"] + tot["near"]) / max(1, tot["err_chars"])))


def build_lex():
    """canonical = longest correct word around the error, alias = same span with the wrong char"""
    entries = {}
    for name, src, tgt in rows(TRAIN):
        pos = diff_positions(src, tgt)
        if pos is None:
            continue
        for i in pos:
            if not (is_han(src[i]) and is_han(tgt[i])):
                continue
            if classify(src[i], tgt[i]) not in ("homophone", "tone", "near"):
                continue
            for ln in (4, 3, 2):
                for st in range(max(0, i - ln + 1), i + 1):
                    en = st + ln
                    if en > len(tgt) or not all(is_han(c) for c in tgt[st:en]):
                        continue
                    canon, alias = tgt[st:en], src[st:en]
                    if canon == alias or FREQ.get(canon, 0) <= 0:
                        continue
                    e = entries.setdefault(canon, set())
                    if len(e) < 8:
                        e.add(alias)
    path = os.path.join(OUT, "ctc_probe_lexicon.txt")
    with open(path, "w", encoding="utf-8") as f:
        for canon, aliases in sorted(entries.items()):
            f.write("%s\t-\t%s\treplace\n" % (canon, ",".join(sorted(aliases))))
    print("lexicon entries=%d alias_total=%d -> %s" % (
        len(entries), sum(len(v) for v in entries.values()), path))


def score(src_lines, out_lines, tgt_lines):
    """standard CSC char-level metrics: detection then correction"""
    det_tp = det_fp = det_fn = 0
    cor_tp = cor_fp = cor_fn = 0
    sent_fixed = sent_err = 0
    for src, out, tgt in zip(src_lines, out_lines, tgt_lines):
        out = out if len(out) == len(src) else src  # length change == failed edit; treat as untouched
        for i in range(len(src)):
            error = src[i] != tgt[i]
            changed = out[i] != src[i]
            if error and changed:
                det_tp += 1
                if out[i] == tgt[i]:
                    cor_tp += 1
                else:
                    cor_fp += 1
                    cor_fn += 1
            elif error:
                det_fn += 1
                cor_fn += 1
            elif changed:
                det_fp += 1
                cor_fp += 1
        sent_err += 1 if src != tgt else 0
        sent_fixed += 1 if src != tgt and out == tgt else 0
    def prf(tp, fp, fn):
        p = tp / max(1, tp + fp)
        r = tp / max(1, tp + fn)
        return p, r, (0 if p + r == 0 else 1.25 * p * r / (2 * p + r))
    dp, dr, df = prf(det_tp, det_fp, det_fn)
    cp, cr, cf = prf(cor_tp, cor_fp, cor_fn + det_fn)
    return dict(det_tp=det_tp, det_fp=det_fp, det_fn=det_fn, cor_tp=cor_tp, cor_fp=cor_fp,
                det_p=dp, det_r=dr, det_f05=df, cor_p=cp, cor_r=cr, cor_f05=cf,
                sent=sent_err, sent_ok=sent_fixed)


def run(lexicon=None, only=None, limit=0, extra=(), bin=None):
    """one CLI call per dataset; sentences are newline-joined so \n acts as a run boundary"""
    exe = bin or (EXE if os.path.exists(EXE) else os.path.join(ROOT, "build", "Debug", "text_clean.exe"))
    overall = collections.Counter()
    print("%-22s %8s %8s %8s %8s %8s %8s" % ("dataset", "det_P", "det_R", "det_F.5", "cor_P", "cor_R", "cor_F.5"))
    tests = [t for t in TEST if not only or only in t]
    for t in tests:
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
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8", dir=TMP) as tf:
            tf.write(body)
            inpath = tf.name
        outpath = inpath + ".out"
        cmd = [exe, "--input-file", inpath, "--word-freq", os.path.join(ROOT, "data", "word_freq.txt"),
               "--pinyin-dict", os.path.join(ROOT, "data", "pinyin_dict.txt"),
               "--vocabulary", os.path.join(ROOT, "data", "dict.txt"), *extra]
        if lexicon:
            cmd += ["--lexicon", lexicon]
        with open(outpath, "wb") as fo:
            subprocess.run(cmd, stdout=fo, stderr=subprocess.DEVNULL, cwd=ROOT)
        outs = open(outpath, encoding="utf-8").read().split("\n")
        os.unlink(inpath); os.unlink(outpath)
        r = score(body.split("\n"), outs, [t for _, t in pairs])
        for k in ("det_tp", "det_fp", "det_fn", "cor_tp", "cor_fp", "sent", "sent_ok"):
            overall[k] += r[k]
        print("%-22s %8.3f %8.3f %8.3f %8.3f %8.3f %8.3f  sent_fixed=%d/%d" % (
            t, r["det_p"], r["det_r"], r["det_f05"], r["cor_p"], r["cor_r"],
            r["cor_f05"], r["sent_ok"], r["sent"]))
    def f05(p, r):
        return 0 if p + r == 0 else 1.25 * p * r / (2 * p + r)
    dp = overall["det_tp"] / max(1, overall["det_tp"] + overall["det_fp"])
    dr = overall["det_tp"] / max(1, overall["det_tp"] + overall["det_fn"])
    cp = overall["cor_tp"] / max(1, overall["cor_tp"] + overall["cor_fp"])
    cr = overall["cor_tp"] / max(1, overall["cor_tp"] + overall["cor_fp"] + overall["det_fn"])
    print("\nAGGREGATE det_P=%.4f det_R=%.4f det_F.5=%.4f | cor_P=%.4f cor_R=%.4f cor_F.5=%.4f"
          " | tp=%d fp=%d fn=%d fixed_sent=%d/%d" % (
              dp, dr, f05(dp, dr), cp, cr, f05(cp, cr), overall["det_tp"], overall["det_fp"],
              overall["det_fn"], overall["sent_ok"], overall["sent"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["stats", "build-lex", "run"])
    ap.add_argument("--lexicon", default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--set", default="", help="extra CLI knobs, e.g. '--mu 1.2 --lambda 1.0'")
    ap.add_argument("--bin", default=None, help="text_clean executable to score")
    a = ap.parse_args()
    load_tables()
    if a.cmd == "stats":
        stats()
    elif a.cmd == "build-lex":
        build_lex()
    else:
        run(a.lexicon, a.only, a.limit, tuple(a.set.split()) if a.set else (), a.bin)
