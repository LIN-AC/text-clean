#!/usr/bin/env python3
"""控制组 M1M2_K=0.6 与 M3（M1M2M3_K=0.6）的逐条编辑差集。

M3 给缺词级证据的目标词补字频兜底，理论上只新增候选，但新候选会在同分/重叠比较里
挤掉原本已经成立的编辑，所以两个方向都要列出来。
"""
import json, pathlib, collections

R = pathlib.Path(__file__).resolve().parents[3]
d = json.loads((R / 'experiments/E024/results/arms.json').read_text(encoding='utf-8'))
CTRL, M3 = 'M1M2_K=0.6', 'M1M2M3_K=0.6'


def key(x):
    return (x['begin'], x['src'], x['dst'])


added, removed, same = [], [], 0
for stem in d['cases'].get(CTRL, {}):
    c = {key(x): x for x in d['cases'][CTRL][stem]}
    m = {key(x): x for x in d['cases'].get(M3, {}).get(stem, [])}
    for k, x in m.items():
        if k in c:
            same += 1
        else:
            added.append((stem, x))
    for k, x in c.items():
        if k not in m:
            removed.append((stem, x))

for tag, lst in (('M3 新增', added), ('M3 挤掉', removed)):
    lab = collections.Counter(x['label'] for _, x in lst)
    print('%s：%d 条（TP %d / FP %d）' % (tag, len(lst), lab['TP'], lab['FP']))
    for stem, x in sorted(lst, key=lambda t: (t[1]['label'], t[0], t[1]['begin'])):
        print('  %-4s %-5s %s->%s d=%s zipfC=%s zipfO=%s  …%s…' % (
            x['label'], stem[:12], x['src'], x['dst'], x['d'], x['zipfC'], x['zipfO'], x['ctx']))
print('两组共有：%d 条' % same)

print('\n=== 汇总 ===')
for m in (CTRL, M3, 'M1M3_无上限'):
    v = d['arms'][m]
    print('%-16s 改对字=%-4d 误改字=%-4d 错到错=%-4d 改对编辑=%-4d 误改编辑=%-4d 总距离=%-5d' % (
        m, v['改对字'], v['误改字'], v['错到错字'], v['改对编辑'], v['误改编辑'], v['总编辑距离']))
base = d['arms']['noop']['总编辑距离']
for m in (CTRL, M3, 'M1M3_无上限'):
    print('%-16s 相对不纠错：%+d' % (m, d['arms'][m]['总编辑距离'] - base))
