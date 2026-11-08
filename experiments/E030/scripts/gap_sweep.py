#!/usr/bin/env python3
"""E030 gap 敏感性：历史域证据强度从小到大，看精确率是否在召回崩掉之前恢复。

只报曲线，不从中挑最好看的当结论（那等于用七篇真值调参）。
"""
import collections, json, pathlib, subprocess, sys

R = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(R / 'experiments/E024/scripts'))
import align_lib as A
sys.stdout.reconfigure(encoding='utf-8')

dom = set()
for l in (R / 'build/e030_evidence/words.tsv').read_text(encoding='utf-8').splitlines():
    if l and not l.startswith('#'):
        p = l.split('\t')
        if p[0] != 'text':
            dom.add(p[0])
SPECIAL = {('魏清', '卫青'), ('桑红阳', '桑弘羊'), ('丧红阳', '桑弘羊'),
           ('填富', '田赋'), ('填付', '田赋'), ('现关', '县官')}
vids = {}
for f in sorted((R / 'asr').glob('*.gt.jsonl')):
    kept = [json.loads(l) for l in f.read_text(encoding='utf-8').splitlines() if l.strip()]
    kept = [r for r in kept if not r.get('discard')]
    body = '\n'.join(r['text'] for r in kept) + '\n'
    labels, off = {}, 0
    for r in kept:
        lab, _ = A.align(r['text'], r['gt'])
        labels.update({off + k: v for k, v in lab.items()})
        off += len(r['text']) + 1
    vids[f.stem] = (body, labels, kept)

base = ['--missing-evidence', 'char', '--missing-cap', '0.6']
for gap in ('0', '0.3', '0.45', '0.8', '1.5'):
    tp = fp = wr = dist = 0
    sp = collections.Counter()
    for stem, (body, labels, kept) in vids.items():
        extra = base + (['--evidence-dir', str(R / 'build/e030_evidence'), '--domain-freq',
                         '--domain-gap', gap] if gap != '0' else [])
        p = subprocess.run(['build/e025/text_clean.exe', '--no-index-cache', '-v'] + extra,
                           input=body.encode('utf-8'), capture_output=True, cwd=str(R))
        out, err = p.stdout.decode(), p.stderr.decode()
        tp += sum(1 for i, v in labels.items() if out[i] != body[i] and out[i] == v)
        fp += sum(1 for i, v in labels.items() if out[i] != body[i] and body[i] == v)
        wr += sum(1 for i, v in labels.items() if out[i] != body[i] and out[i] != v and body[i] != v)
        dist += sum(A.align(l, r['gt'])[1] for l, r in zip(out.splitlines(), kept))
        for m in A.rx.finditer(err):
            kind, a, b, src, dst, d, sc, zc, zo = m.groups()
            if (src, dst) in SPECIAL:
                sp['改对' if out[int(a):int(b)] == dst else '未改'] += 1
    print('gap=%-5s 改对字=%-4d 误改字=%-4d 错到错=%-4d 总错误量=%-5d 卫青族改对实例=%d' % (
        gap, tp, fp, wr, dist, sp['改对']), flush=True)
