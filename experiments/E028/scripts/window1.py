#!/usr/bin/env python3
"""E028｜窗口最短长度从 2 放开到 1，有没有收益。

只加诊断开关 --min-window（默认 2，不改现有行为）。对比同一二进制下
Z1 默认臂与 Z2 控制臂各自"窗2 vs 窗1"的改对字/误改字/错到错/总错误量，
并数一下单字窗口到底产出了几条编辑。
"""
import collections, json, pathlib, subprocess, sys

R = pathlib.Path(__file__).resolve().parents[3]
O = R / 'experiments/E028/results'
O.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(R / 'experiments/E024/scripts'))
import align_lib as A
sys.stdout.reconfigure(encoding='utf-8')

EXE = 'build/e025/text_clean.exe'
ARMS = [('基准 窗2 Z1默认', []),
        ('改后 窗1 Z1默认', ['--min-window', '1']),
        ('基准 窗2 Z2控制臂', ['--missing-evidence', 'char', '--missing-cap', '0.6']),
        ('改后 窗1 Z2控制臂', ['--missing-evidence', 'char', '--missing-cap', '0.6', '--min-window', '1'])]

vids = {}
for p in sorted((R / 'asr').glob('*.gt.jsonl')):
    rows = [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]
    kept = [r for r in rows if not r.get('discard')]
    body = '\n'.join(r['text'] for r in kept) + '\n'
    labels, off = {}, 0
    for r in kept:
        lab, _ = A.align(r['text'], r['gt'])
        labels.update({off + k: v for k, v in lab.items()})
        off += len(r['text']) + 1
    vids[p.stem] = (body, labels, kept)

res, one_char = {}, collections.Counter()
for name, extra in ARMS:
    tp = fp = wr = dist = 0
    for stem, (body, labels, kept) in vids.items():
        p = subprocess.run([EXE, '--no-index-cache', '-v'] + extra, input=body.encode('utf-8'),
                           capture_output=True, cwd=str(R))
        assert p.returncode == 0, p.stderr.decode('utf-8', 'replace')[:300]
        out, err = p.stdout.decode('utf-8'), p.stderr.decode('utf-8')
        for m in A.rx.finditer(err):
            kind, a, b, src, dst, d, sc, zc, zo = m.groups()
            if len(src) == 1:
                one_char[name] += 1
                one_char[(name, src, dst, kind)] = 1
        tp += sum(1 for i, v in labels.items() if out[i] != body[i] and out[i] == v)
        fp += sum(1 for i, v in labels.items() if out[i] != body[i] and body[i] == v)
        wr += sum(1 for i, v in labels.items() if out[i] != body[i] and out[i] != v and body[i] != v)
        dist += sum(A.align(l, r['gt'])[1] for l, r in zip(out.splitlines(), kept))
    res[name] = dict(tp=tp, fp=fp, wrong=wr, distance=dist)
    print('%-20s 改对字=%-4d 误改字=%-4d 错到错=%-4d 总错误量=%-5d 单字窗口产出编辑=%d' % (
        name, tp, fp, wr, dist, one_char[name]))

for new, ref in (('改后 窗1 Z1默认', '基准 窗2 Z1默认'), ('改后 窗1 Z2控制臂', '基准 窗2 Z2控制臂')):
    a, b = res[new], res[ref]
    print('%s vs %s: 改对%+d 误改%+d 错到错%+d 总错误量%+d' % (
        new, ref, a['tp'] - b['tp'], a['fp'] - b['fp'], a['wrong'] - b['wrong'], a['distance'] - b['distance']))

# 候选池里到底有没有单字目标词（决定窗1 是否可能命中）
rows = [l.split('\t') for l in (R / 'data/correction/candidates.tsv').read_text(encoding='utf-8').splitlines()
        if l and not l.startswith('#')][1:]
targets = {r[0] for r in rows if r[-1] == '1'}
print('启用目标词=%d 个，其中长度 1 的=%d 个' % (len(targets), sum(1 for t in targets if len(t) == 1)))
json.dump(dict(arms=res, one_char_edits={k: v for k, v in one_char.items() if isinstance(k, str)},
               single_char_targets=sum(1 for t in targets if len(t) == 1)),
          (O / 'window1.json').open('w', encoding='utf-8'), ensure_ascii=False, indent=1)
