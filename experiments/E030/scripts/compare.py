#!/usr/bin/env python3
"""E030 对照：仅历史词频 / 仅上下文 / 两者结合，与冻结基线比。

规矩：
  * 每臂都跑满 7 篇，先断言控制臂复现冻结基准（147/100/27/1977），对不上就停。
  * 同时报"本来写对的位置被改错"的数量（E029 的教训：只数未修复样本会低估代价）。
  * --domain-gap 的不同取值只作为敏感性报告，不挑最好看的当结论。
"""
import collections, json, pathlib, subprocess, sys

R = pathlib.Path(__file__).resolve().parents[3]
O = R / 'experiments/E030/results'
O.mkdir(parents=True, exist_ok=True)
EV = str(R / 'build/e030_evidence')
sys.path.insert(0, str(R / 'experiments/E024/scripts'))
import align_lib as A
sys.stdout.reconfigure(encoding='utf-8')

EXE = 'build/e025/text_clean.exe'
CTRL = ['--missing-evidence', 'char', '--missing-cap', '0.6']
ARMS = [
    ('B0 冻结控制臂', CTRL),
    ('H1 仅历史词频', CTRL + ['--evidence-dir', EV, '--domain-freq']),
    ('H2 历史词频 gap=1.0', CTRL + ['--evidence-dir', EV, '--domain-freq', '--domain-gap', '1.0']),
    ('H3 历史词频 gap=2.0', CTRL + ['--evidence-dir', EV, '--domain-freq', '--domain-gap', '2.0']),
    ('X1 仅邻接上下文', CTRL + ['--evidence-dir', EV, '--ctx-evidence']),
    ('X2 上下文 权重0.5', CTRL + ['--evidence-dir', EV, '--ctx-evidence', '--ctx-weight', '0.5']),
    ('HX 历史词频+上下文', CTRL + ['--evidence-dir', EV, '--domain-freq', '--ctx-evidence']),
    ('P0 默认生产臂', []),
    ('PH 默认臂+历史词频', ['--evidence-dir', EV, '--domain-freq']),
]
FROZEN = {'B0 冻结控制臂': (147, 100, 1977), 'P0 默认生产臂': (64, 87, 2047)}

# 专项：历史上冷门但正确的词（E026 漏斗里死在评分那一关的代表）
SPECIAL = {('魏清', '卫青'), ('桑红阳', '桑弘羊'), ('丧红阳', '桑弘羊'), ('填富', '田赋'),
           ('填付', '田赋'), ('现关', '县官'), ('清姚伯父', '轻徭薄赋'), ('轻咬伯父', '轻徭薄赋'),
           ('卖关于绝', '卖官鬻爵'), ('独口政绩修复', '堵口赈济修复'), ('用下滑线标注', '用下划线标注'),
           ('师生付货', '士绅富户'), ('纳苏二十', '纳粟二石'), ('在降服决口', '在祥符决口')}

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

rows_out, special_table = {}, collections.defaultdict(dict)
for name, extra in ARMS:
    tp = fp = wr = dist = 0
    for stem, (body, labels, kept) in vids.items():
        p = subprocess.run([EXE, '--no-index-cache', '-v'] + extra, input=body.encode('utf-8'),
                           capture_output=True, cwd=str(R))
        assert p.returncode == 0, p.stderr.decode('utf-8', 'replace')[:400]
        out, err = p.stdout.decode('utf-8'), p.stderr.decode('utf-8')
        tp += sum(1 for i, v in labels.items() if out[i] != body[i] and out[i] == v)
        fp += sum(1 for i, v in labels.items() if out[i] != body[i] and body[i] == v)
        wr += sum(1 for i, v in labels.items() if out[i] != body[i] and out[i] != v and body[i] != v)
        dist += sum(A.align(l, r['gt'])[1] for l, r in zip(out.splitlines(), kept))
        for m in A.rx.finditer(err):
            kind, a, b, src, dst, d, sc, zc, zo = m.groups()
            if (src, dst) in SPECIAL:
                special_table[(src, dst)][name] = '改对' if out[int(a):int(b)] == dst else '未改'
    rows_out[name] = dict(tp=tp, fp=fp, wrong=wr, distance=dist)
    if name in FROZEN:
        assert (tp, fp, dist) == FROZEN[name], ('冻结基准对不上，停止: %s %s' % (name, (tp, fp, dist)))
    print('%-22s 改对字=%-4d 误改字=%-4d 错到错=%-4d 总错误量=%-5d 相对冻结控制臂=%+d' % (
        name, tp, fp, wr, dist, dist - rows_out['B0 冻结控制臂']['distance']), flush=True)

print('\n=== 专项冷门正确词（各臂是否改对）===')
keys = list(rows_out)
print('  %-22s %s' % ('原文→真值', ' '.join('%-22s' % k for k in keys)))
for pair, per in sorted(special_table.items()):
    print('  %-22s %s' % ('%s→%s' % pair, ' '.join('%-22s' % per.get(k, '没出现') for k in keys)))
missing = [p for p in SPECIAL if p not in special_table]
if missing:
    print('  本轮完全没有产生这些候选编辑的词对：%d 组（例：%s）' % (len(missing), '、'.join('%s→%s' % m for m in list(missing)[:5])))

json.dump(dict(arms=rows_out, special={('%s→%s' % k): v for k, v in special_table.items()},
               no_edit_pairs=['%s→%s' % m for m in missing]),
          (O / 'compare.json').open('w', encoding='utf-8'), ensure_ascii=False, indent=1)
