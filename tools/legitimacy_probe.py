#!/usr/bin/env python3
"""Which signal actually separates "this span is legitimate Chinese" from "this span is an ASR error"?

text_clean's only legitimacy test for the ORIGINAL text is an exact lookup:
WordFrequency::count(span) from data/word_freq.txt (0 = unseen), plus a
membership veto against data/dict.txt (Vocabulary, whose own frequency column is
documented as ignored). Scoring then floors the CANDIDATE frequency at 3, so
fO=0, distance<=1, fC>=3 gives dS = ln4 - 0.65 - 0.70 = 0.036 > 0: a rewrite
needs no positive evidence at all. This tool measures candidate replacement
signals on labelled data to see which one is worth promoting.

Usage:
  python tools/legitimacy_probe.py collect [--limit N]   # run CLI, cache spans
  python tools/legitimacy_probe.py analyze               # score signals on cache
"""
import argparse, collections, glob, json, math, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "datasets", "CTCDataset")
LEX = os.path.join(ROOT, "datasets", "ctc_probe_lexicon.txt")
EXE = os.environ.get("TC_EXE") or os.path.join(ROOT, "build-probe", "text_clean.exe")
TMP = os.environ.get("TC_TMP") or os.path.join(ROOT, "log")
CACHE = os.environ.get("TC_CACHE") or os.path.join(ROOT, "log", "_legit_spans.json")
TRAIN_SPLITS = ["sighan/sighan13_train", "sighan/sighan14_train", "sighan/sighan15_train",
                "MCSCSet/valid", "ECSpell/ec_law", "ECSpell/ec_med", "ECSpell/ec_odw"]
TEST_SPLITS = ["sighan/sighan13_test", "sighan/sighan14_test", "sighan/sighan15_test",
               "MCSCSet/test", "cscd-ns/test", "cscd-ns/dev",
               "lemon/car", "lemon/cot", "lemon/enc", "lemon/gam", "lemon/mec",
               "lemon/new", "lemon/nov"]
HAN = re.compile(r"[㐀-鿿]")


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


def vocab():
    V = set()
    for line in open(os.path.join(ROOT, "data", "dict.txt"), encoding="utf-8"):
        p = line.split()
        if p:
            V.add(p[0])
    return V


def load_pairs(split, limit=0):
    out = []
    for line in open(os.path.join(DATA, split + ".jsonl"), encoding="utf-8"):
        d = json.loads(line)
        if len(d["source"]) == len(d["target"]):
            out.append((d["source"], d["target"]))
        if limit and len(out) >= limit:
            break
    return out


def collect(limit, exe=None):
    exe = exe or EXE
    """run the CLI per split; recover rewritten spans by positional diff (length-preserving)"""
    spans = []
    for split in TEST_SPLITS:
        pairs = load_pairs(split, limit)
        if not pairs:
            continue
        inp = os.path.join(TMP, "_legit_in.txt")
        outp = os.path.join(TMP, "_legit_out.txt")
        open(inp, "w", encoding="utf-8").write("\n".join(s for s, _ in pairs))
        with open(outp, "wb") as fo:
            subprocess.run([exe, "--input-file", inp, "--lexicon", LEX], stdout=fo,
                           stderr=subprocess.DEVNULL, cwd=ROOT)
        outs = open(outp, encoding="utf-8").read().split("\n")
        os.unlink(inp); os.unlink(outp)
        n_changed = 0
        for si, (src, tgt) in enumerate(pairs):
            if si >= len(outs) or len(outs[si]) != len(src):
                continue
            o = outs[si]
            j = 0
            while j < len(src):
                if o[j] == src[j]:
                    j += 1
                    continue
                k = j
                while k < len(src) and o[k] != src[k]:
                    k += 1
                spans.append(dict(split=split, src=src[j:k], dst=o[j:k], gold=tgt[j:k],
                                  before=src[max(0, j - 2):j], after=src[k:k + 2]))
                n_changed += 1
                j = k
        print("%-26s rows=%-6d rewritten_spans=%d" % (split, len(pairs), n_changed))
    json.dump(spans, open(os.environ.get("LEGIT_CACHE", CACHE), "w", encoding="utf-8"), ensure_ascii=False)
    print("cached %d spans -> %s" % (len(spans), CACHE))


def char_unigram():
    """character frequency from text only (targets of train splits + local ASR corpus);
    deliberately not from labels"""
    c = collections.Counter()
    for split in TRAIN_SPLITS:
        for src, tgt in load_pairs(split):
            c.update(ch for ch in tgt if HAN.match(ch))
    for f in glob.glob(os.path.join(ROOT, "whisper_txt", "*.txt")):
        c.update(ch for ch in open(f, encoding="utf-8").read() if HAN.match(ch))
    return c


def bigram_counts():
    b = collections.Counter()
    for split in TRAIN_SPLITS:
        for src, tgt in load_pairs(split):
            for i in range(len(tgt) - 1):
                if HAN.match(tgt[i]) and HAN.match(tgt[i + 1]):
                    b[tgt[i:i + 2]] += 1
    for f in glob.glob(os.path.join(ROOT, "whisper_txt", "*.txt")):
        t = open(f, encoding="utf-8").read()
        for i in range(len(t) - 1):
            if HAN.match(t[i]) and HAN.match(t[i + 1]):
                b[t[i:i + 2]] += 1
    return b


def greedy_tokens(text, wordset, maxlen):
    toks, i = [], 0
    while i < len(text):
        L = 0
        for cand in range(min(maxlen, len(text) - i), 1, -1):
            if text[i:i + cand] in wordset:
                L = cand
                break
        if L:
            toks.append((i, i + L, True)); i += L
        else:
            b = i; i += 1
            while i < len(text) and not any(
                    text[i:i + c] in wordset for c in range(min(maxlen, len(text) - i), 1, -1)):
                i += 1
            toks.append((b, i, False))
    return toks


def auc(pos, neg):
    if not pos or not neg:
        return float("nan")
    wins = sum(1 for a in pos for b in neg if a < b) + 0.5 * sum(1 for a in pos for b in neg if a == b)
    return wins / (len(pos) * len(neg))


def analyze():
    spans = json.load(open(os.environ.get("LEGIT_CACHE", CACHE), encoding="utf-8"))
    F, V = word_freq(), vocab()
    uni = char_unigram()
    bi = bigram_counts()
    tot_uni = sum(uni.values())
    wordset = set(F)
    maxlen = max((len(w) for w in wordset), default=4)
    fp, tp, wrong = [], [], []
    for s in spans:
        if not (len(s["src"]) == len(s["dst"]) == len(s["gold"])):
            continue
        kind = 0 if s["src"] == s["gold"] else (1 if s["dst"] == s["gold"] else 2)
        (fp, tp, wrong)[kind].append(s)
    print("spans: fp=%d  tp=%d  wrong-repair=%d" % (len(fp), len(tp), len(wrong)))

    def feats(row):
        src = row["src"]
        f = {}
        f["freq0"] = 1 if F.get(src, 0) == 0 else 0
        f["in_vocab"] = 1 if src in V else 0
        r = [uni.get(c, 0) for c in src]
        f["min_char_unigram"] = min(r) if r else 0
        f["max_char_unigram"] = max(r) if r else 0
        # span bigram co-occurrence in text, and its PMI against unigram independence
        co = [bi.get(src[i:i + 2], 0) for i in range(len(src) - 1)]
        f["cooccur"] = min(co) if co else 0
        if co and len(src) == 2:
            p = max(bi.get(src, 0), 1) / tot_uni
            q1 = max(uni.get(src[0], 1), 1) / tot_uni
            q2 = max(uni.get(src[1], 1), 1) / tot_uni
            f["pmi"] = math.log(p / (q1 * q2))
        else:
            f["pmi"] = 0.0
        # does the span cut through a greedy dictionary token in its own sentence context?
        ctx = row["before"] + src + row["after"]
        off = len(row["before"])
        toks = greedy_tokens(ctx, wordset, maxlen)
        own = [t for t in toks if t[0] < off + len(src) and t[1] > off]
        f["splits_token"] = 1 if any(t[0] < off and t[1] > off for t in own) else 0
        f["all_known_tokens"] = 1 if own and all(t[2] for t in own) and not f["splits_token"] else 0
        f["span_len"] = len(src)
        f["dst_freq"] = F.get(row["dst"], 0)
        return f

    table = collections.defaultdict(lambda: {"fp": [], "tp": []})
    for row in fp:
        for k, v in feats(row).items():
            table[k]["fp"].append(v)
    for row in tp:
        for k, v in feats(row).items():
            table[k]["tp"].append(v)

    print("\n== separation of each signal (AUC over fp vs tp spans) ==")
    for k, d in table.items():
        if k in ("span_len",):
            continue
        a = auc(d["fp"], d["tp"])
        print("  %-18s AUC(fp<tp)=%.3f   fp_mean=%.4f tp_mean=%.4f" % (
            k, a, sum(d["fp"]) / len(d["fp"]), sum(d["tp"]) / len(d["tp"])))

    print("\n== hard-veto rules: share of spans each rule would protect from rewriting ==")
    print("%-34s %10s %10s %10s" % ("rule", "fp_kept%", "tp_kept%", "selectivity"))
    def rate(pred):
        f = 100 * sum(1 for r in fp if pred(feats(r))) / max(1, len(fp))
        t = 100 * sum(1 for r in tp if pred(feats(r))) / max(1, len(tp))
        return f, t
    rules = [
        ("cooccur == 0 (no bigram evidence)", lambda x: x["cooccur"] == 0),
        ("min_char_unigram >= 5000", lambda x: x["min_char_unigram"] >= 5000),
        ("pmi < 0 (chars co-occur less than chance)", lambda x: x.get("pmi", 0) < 0),
        ("splits_token (cuts a dictionary word)", lambda x: x["splits_token"] == 1),
        ("all_known_tokens and not splits_token", lambda x: x["all_known_tokens"] == 1),
        ("freq0 and in_vocab (legit word, no freq)", lambda x: x["freq0"] == 1 and x["in_vocab"] == 1),
        ("freq0 and not in_vocab", lambda x: x["freq0"] == 1 and x["in_vocab"] == 0),
        ("freq0 and cooccur==0 and min_uni>=5000",
         lambda x: x["freq0"] == 1 and x["cooccur"] == 0 and x["min_char_unigram"] >= 5000),
    ]
    for name, pred in rules:
        f, t = rate(pred)
        print("%-34s %9.1f%% %9.1f%% %10.2f" % (name, f, t, (f / t) if t else float("inf")))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["collect", "analyze"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--bin", default=None)
    a = ap.parse_args()
    if a.cmd == "collect":
        collect(a.limit, a.bin)
    else:
        if not os.path.exists(os.environ.get("LEGIT_CACHE", CACHE)):
            sys.exit("run collect first")
        analyze()
