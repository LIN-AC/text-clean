#!/usr/bin/env python3
"""同一批 140 道题，问 V1 自己做得到什么程度（给 LLM 的 92% 找参照物）。

口径：正例看 V1 有没有把那段改成真值（改对/漏改/改成第三个字），
负例看 V1 有没有动那段（没动＝守住，动了＝误改）。V1 只跑一次每篇，结果按位点查表。
"""
import collections, json, pathlib, subprocess, sys

R = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(R / 'experiments/E024/scripts'))
sys.stdout.reconfigure(encoding='utf-8')
from align_lib import align

d = json.loads((R / 'experiments/E051/results/llm_ab.json').read_text('utf-8'))
bodies = {}
for video in sorted({x['video'] for x in d['items']}):
    name = video[:-3] if video.endswith('.gt') else video      # 题库里存的是文件主名（含 .gt）
    keep = [r for r in (json.loads(s) for s in (R / ('asr/%s.gt.jsonl' % name)).read_text('utf-8').splitlines()
                        if s.strip()) if not r.get('discard')]
    body = '\n'.join(r['text'] for r in keep) + '\n'
    out = subprocess.run([str(R / 'build/e035/text_clean.exe'), '--no-index-cache'],
                         input=body.encode('utf-8'), capture_output=True, check=True, cwd=R).stdout.decode('utf-8')
    starts, pos = [], 0
    for r in keep:
        starts.append(pos)
        pos += len(r['text']) + 1
    bodies[video] = (out, starts)

cell = collections.Counter()
detail = []
for x in d['items']:
    out, starts = bodies[x['video']]
    b = starts[x['cue']] + x['begin']
    e = starts[x['cue']] + x['end']
    seg = out[b:e]
    if x['kind'] == '该改':
        k = 'V1改对' if seg == x['other'] else 'V1漏改' if seg == x['source'] else 'V1改成第三个字'
    else:
        k = 'V1守住' if seg == x['source'] else 'V1误改'
    cell[k] += 1
    detail.append((x['kind'], k, x['source'], x['other'], seg, x['llm']))
pos = sum(1 for x in d['items'] if x['kind'] == '该改')
neg = len(d['items']) - pos
print('==== 同 140 道题，V1（默认设置）的表现 ====')
for k, v in sorted(cell.items()):
    print('  %-12s %d 条' % (k, v))
print('  正例 %d 条里 V1 改对 %d＝%.1f%%（LLM 同题 %d/%d＝%.1f%%）' % (
    pos, cell['V1改对'], 100.0 * cell['V1改对'] / pos,
    sum(1 for x in d['items'] if x['kind'] == '该改' and x['verdict_ok']), pos,
    100.0 * sum(1 for x in d['items'] if x['kind'] == '该改' and x['verdict_ok']) / pos))
print('  负例 %d 条里 V1 误改 %d＝%.1f%%（LLM 同题被带跑 %d 条）' % (
    neg, cell['V1误改'], 100.0 * cell['V1误改'] / neg,
    sum(1 for x in d['items'] if x['kind'] == '不该改' and not x['verdict_ok'])))
cross = collections.Counter()
for x, (kind, v1, src, other, seg, llm) in zip(d['items'], detail):
    ok_v1 = v1 in ('V1改对', 'V1守住')
    cross['%s｜V1%s｜LLM%s' % (kind, '对' if ok_v1 else '错',
                              '对' if x['verdict_ok'] else ('弃权' if x['llm'] == '都行' else '错'))] += 1
print('  V1 × LLM 同题交叉：')
for k in sorted(cross):
    print('    %-34s %d 条' % (k, cross[k]))
(OUT := R / 'experiments/E051/results/v1_same_items.json').write_text(json.dumps(dict(
    cells=dict(cell), positives=pos, negatives=neg,
    per_item=[dict(kind=a, v1=b, source=c, other=dd, v1_seg=e, llm=f) for a, b, c, dd, e, f in detail]),
    ensure_ascii=False, indent=2), encoding='utf-8')
print('写出 experiments/E051/results/v1_same_items.json')
