#!/usr/bin/env python3
"""E044 结果拆解：① 检索是否真的逐字没用；② 94 个改对与 V1 的 152 个重叠多少；③ D≠0 的窗口有多少。"""
import collections, json, pathlib, subprocess, sys

R = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(R / 'tools'))
sys.path.insert(0, str(R / 'experiments/E024/scripts'))
sys.stdout.reconfigure(encoding='utf-8')
from align_lib import align     # noqa: E402
TR = R / 'build/e044_probe/traces'


def rows_of(v):
    rr = [json.loads(s) for s in (R / 'asr' / (v + '.gt.jsonl')).read_text('utf-8').splitlines() if s.strip()]
    return [r for r in rr if not r.get('discard')]


def labels(rows):
    lab, off = {}, 0
    for r in rows:
        l, _ = align(r['text'], r['gt'])
        lab.update({off + i: x for i, x in l.items()})
        off += len(r['text']) + 1
    return lab, '\n'.join(r['text'] for r in rows) + '\n'


vids = sorted(p.stem[:-3] for p in (R / 'asr').glob('*.gt.jsonl'))
same_text = same_edits = diff_v = 0
tp_rag, tp_v1 = set(), set()
d_windows = d_events = 0
off_global = 0
for v in vids:
    rows = rows_of(v)
    lab, body = labels(rows)
    a = json.loads((TR / ('full.rag.%s.gt.json' % v)).read_text('utf-8'))
    b = json.loads((TR / ('full.rag_no_retrieval.%s.gt.json' % v)).read_text('utf-8'))
    if a['text'] == b['text']:
        same_text += 1
    else:
        diff_v += 1
    ea = {(e['begin'], e['end'], e['target']) for e in a['edits']}
    eb = {(e['begin'], e['end'], e['target']) for e in b['edits']}
    same_edits += (ea == eb)
    for i, x in lab.items():
        if a['text'][i] != body[i] and a['text'][i] == x:
            tp_rag.add((v, i))
    for w in a['windows']:
        if any(abs(h.get('D', 0)) > 1e-12 for h in w.get('H', [])):
            d_windows += 1
            d_events += sum(1 for h in w['H'] if abs(h.get('D', 0)) > 1e-12)
    # V1 位点
    out = subprocess.run([str(R / 'build/e035/text_clean.exe'), '--no-index-cache'],
                         input=body.encode('utf-8'), capture_output=True, check=True,
                         cwd=R).stdout.decode('utf-8')
    for i, x in lab.items():
        if out[i] != body[i] and out[i] == x:
            tp_v1.add((v, i))
print('① 有检索 vs 无检索：七篇输出逐字相同的篇数 %d/7，编辑集合相同 %d/7，不同 %d' % (same_text, same_edits, diff_v))
print('   新入口改对位点 %d，V1 改对位点 %d，交集 %d，新入口独占 %d，V1 独占 %d' % (
    len(tp_rag), len(tp_v1), len(tp_rag & tp_v1), len(tp_rag - tp_v1), len(tp_v1 - tp_rag)))
print('② 合并包里 D≠0 的窗口 %d 个，D≠0 的候选条目 %d 条（总窗口约 1,174）' % (d_windows, d_events))
json.dump(dict(tp_rag=len(tp_rag), tp_v1=len(tp_v1), overlap=len(tp_rag & tp_v1),
               rag_only=len(tp_rag - tp_v1), v1_only=len(tp_v1 - tp_rag),
               identical_outputs=same_text, identical_edits=same_edits,
               windows_with_D=d_windows, entries_with_D=d_events),
          open(R / 'experiments/E044/results/split_full.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print('写出 experiments/E044/results/split_full.json')
