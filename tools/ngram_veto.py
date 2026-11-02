"""Offline character 2/3-gram boundary veto experiment. Never rewrites text.
Input cases JSONL: text, begin, end (code points), replacement, valid (bool).
Usage: python tools/ngram_veto.py --train corpus.txt --cases cases.jsonl --output report.json
Training documents must be independent of evaluation; exact sentence leakage is rejected.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

class BoundaryModel:
    def __init__(self, texts):
        self.counts = {n: Counter() for n in (1, 2, 3)}
        for text in texts:
            for run in re.findall(r"[\u3400-\u9fff]+", text):
                for n in (1, 2, 3):
                    self.counts[n].update(run[i:i+n] for i in range(len(run)-n+1))
        self.vocab = max(1, len(self.counts[1])) + 1

    def evaluate(self, case, threshold=1.0):
        text, b, e, replacement = case['text'], case['begin'], case['end'], case['replacement']
        if not (0 <= b < e <= len(text)) or len(replacement) != e-b:
            raise ValueError('only valid equal-length spans are supported')
        changed = text[:b] + replacement + text[e:]
        delta, supported = 0.0, 0
        for i in range(b, min(len(text), e+2)):
            for n in (3, 2):
                start = i-n+1
                if start < 0 or not (start < b or i >= e):
                    continue  # boundary evidence only, no internal word popularity
                old, new = text[start:i+1], changed[start:i+1]
                if old == new or not re.fullmatch(r"[\u3400-\u9fff]+", old+new):
                    continue
                counts = self.counts[n]
                if max(counts[old], counts[new]) < 2:
                    continue
                def score(g):
                    return math.log((counts[g]+0.1)/(self.counts[n-1][g[:-1]]+0.1*self.vocab))
                delta += score(new)-score(old)
                supported += 1
                break
        return dict(delta=delta, supported=supported,
                    veto=supported >= 2 and delta < -threshold)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--train',type=Path,nargs='+',required=True)
    p.add_argument('--cases',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    texts=[f.read_text(encoding='utf-8-sig') for f in args.train]
    cases=[json.loads(line) for line in args.cases.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    for case in cases:
        truth=case['text'][:case['begin']]+case['replacement']+case['text'][case['end']:]
        if any(case['text'] in t or truth in t for t in texts):
            raise ValueError('evaluation sentence present in training corpus')
    model=BoundaryModel(texts)
    rows=[dict(case, **model.evaluate(case)) for case in cases]
    report=dict(mode='offline_only_no_rewrites', cases=rows,
                train_sha256={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in args.train},
                cases_sha256=hashlib.sha256(args.cases.read_bytes()).hexdigest(),
                valid_candidates=sum(r['valid'] for r in rows),
                invalid_candidates=sum(not r['valid'] for r in rows),
                invalid_vetoed=sum(r['veto'] and not r['valid'] for r in rows),
                valid_vetoed=sum(r['veto'] and r['valid'] for r in rows))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__': main()
