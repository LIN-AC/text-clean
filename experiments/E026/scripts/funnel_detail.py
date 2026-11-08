#!/usr/bin/env python3
"""E026 深拆：S1（池外）能不能靠扩池救、S5（进了评分却被否）差多少。

只统计，不改评分参数：S5 的"差多少"只是把复算分数报出来，不构成调参建议。
"""
import collections, json, pathlib, sys

R = pathlib.Path(__file__).resolve().parents[3]
O = R / 'experiments/E026/results'
sys.path.insert(0, str(R / 'experiments/E026/scripts'))
import replica as RP
sys.stdout.reconfigure(encoding='utf-8')

errors = json.loads((O / 'errors.json').read_text(encoding='utf-8'))
rows = {ARM: json.loads((O / ('funnel_%s.json' % ARM)).read_text(encoding='utf-8')) for ARM in ('Z1', 'Z2')}

# ---------- A) S1 池外实例的成分 ----------
out1 = [r for r in rows['Z2'] if r['stage'].startswith('S1')]
comp = collections.Counter()
pinyin_recoverable = []
for e in errors:
    o, t = e['original'], e['truth']
    if t in RP.TARGETS:
        continue
    comp['实例'] += 1
    comp['长度%d' % len(o)] += 1
    if len(o) != len(t):
        comp['等长以外(插入/删除)'] += 1
        continue
    d = RP.aligned_distance(o, t)
    near = RP.near_ok(o, t)
    if d is None or d > RP.MAXD or not near:
        comp['非拼音型(距离>2 或近音门不过)'] += 1
    else:
        comp['拼音型(扩池后才可能命中)'] += 1
        pinyin_recoverable.append(dict(video=e['video'], begin=e['begin'], o=o, t=t, d=d))
print('=== S1 池外 1,141 个实例的成分 ===')
for k, v in sorted(comp.items(), key=lambda x: -x[1]):
    print('  %-26s %d' % (k, v))
dc = collections.Counter(x['d'] for x in pinyin_recoverable)
print('  其中可按拼音命中(d=0/1/2): %s' % dict(sorted(dc.items())))

# ---------- B) S5 差多少 ----------
print('\n=== S5 进入评分但分数≤0（臂 Z2）===')
s5 = [r for r in rows['Z2'] if r['stage'].startswith('S5')]
bins = collections.Counter()
byd = collections.Counter()
examples = collections.defaultdict(list)
for r in s5:
    sc = r['score']
    b = '(-0.1,0]' if sc > -0.1 else '(-0.5,-0.1]' if sc > -0.5 else '(-1,-0.5]' if sc > -1 else '≤-1'
    bins[b] += 1
    byd[r['d']] += 1
    examples[b].append(r)
print('  实例数=%d 字数=%d' % (len(s5), sum(r['len'] for r in s5)))
print('  分数区间分布:', dict(sorted(bins.items(), key=lambda x: -x[1])))
print('  拼音距离分布:', dict(sorted(byd.items())))
for b in ('(-0.1,0]', '(-0.5,-0.1]'):
    print('  %s 样本:' % b)
    for r in examples[b][:6]:
        zt, zo = RP.ZIPF.get(r['t']), RP.ZIPF.get(r['o'])
        print('    %s:%d %s->%s d=%s 复算分=%+.3f  zipf目标=%s zipf原文=%s 原文有无词级证据=%s' % (
            r['video'], r['begin'], r['o'], r['t'], r['d'], r['score'], zt, zo, zo is not None))

# 原文缺证据 vs 两侧都有证据
kinds = collections.Counter()
for r in s5:
    kinds['原文有词级证据(真方向相反)' if RP.ZIPF.get(r['o']) else '原文缺证据(靠封顶仍不够)'] += 1
print('  按证据形态:', dict(kinds))

# ---------- C) 两臂对照 ----------
print('\n=== Z1 vs Z2 各关差异（实例数）===')
stages = sorted({r['stage'][:2] for r in rows['Z1']} | {r['stage'][:2] for r in rows['Z2']})
c1 = collections.Counter(r['stage'][:2] for r in rows['Z1'])
c2 = collections.Counter(r['stage'][:2] for r in rows['Z2'])
for k in stages:
    print('  %-4s Z1=%-5d Z2=%-5d 差=%+d' % (k, c1[k], c2[k], c2[k] - c1[k]))
moved = [r for r in rows['Z2'] if r['stage'].startswith('S0') and
         next(x for x in rows['Z1'] if x['video'] == r['video'] and x['begin'] == r['begin'])['stage'].startswith(('S4', 'S5'))]
print('  M1+M2 从 S4/S5 救回的实例：%d 个 / %d 字' % (len(moved), sum(r['len'] for r in moved)))
json.dump(dict(s1_components=dict(comp), s1_pinyin_recoverable=len(pinyin_recoverable),
               s5_bins=dict(bins), s5_by_distance=dict(byd), s5_kinds=dict(kinds),
               z1=dict(c1), z2=dict(c2), rescued_by_m1m2=len(moved)),
          (O / 'detail_summary.json').open('w', encoding='utf-8'), ensure_ascii=False, indent=1)
