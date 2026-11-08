#!/usr/bin/env python3
"""E027｜确认首音节保护确实生效，并把七篇结果冻结成对照基准。

本轮不动任何代码、词库、公式和参数：只跑现默认配置，并用已有的诊断开关
`--no-first-syllable-gate` 做一次 A/B，证明保护不是空转。
指标口径与 E022–E026 完全相同（`align_lib.py`）。
"""
import collections, hashlib, json, pathlib, re, subprocess, sys

R = pathlib.Path(__file__).resolve().parents[3]
O = R / 'experiments/E027/results'
O.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(R / 'experiments/E024/scripts'))
sys.path.insert(0, str(R / 'experiments/E026/scripts'))
import align_lib as A
import replica as RP
sys.stdout.reconfigure(encoding='utf-8')

EXE = str(R / 'build/e025/text_clean.exe')
ARMS = [
    ('Z1 默认(生产口径)', []),
    ('Z1+关首音节保护', ['--no-first-syllable-gate']),
    ('Z2 控制臂 M1M2 K=0.6', ['--missing-evidence', 'char', '--missing-cap', '0.6']),
    ('Z2+关首音节保护', ['--missing-evidence', 'char', '--missing-cap', '0.6', '--no-first-syllable-gate']),
]

videos = []
for path in sorted((R / 'asr').glob('*.gt.jsonl')):
    rows = [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]
    kept = [r for r in rows if not r.get('discard')]
    assert not any(r.get('pending') for r in rows)
    body = '\n'.join(r['text'] for r in kept) + '\n'
    labels, off = {}, 0
    for row in kept:
        lab, _ = A.align(row['text'], row['gt'])
        labels.update({off + k: v for k, v in lab.items()})
        off += len(row['text']) + 1
    videos.append((path.stem, body, labels, kept))

# ---- 1. 保护的实际拦截面：窗口起点有多少能通过 first_bases ----
bases = RP.FIRST_BASES if hasattr(RP, 'FIRST_BASES') else {RP.base_of(v[0]) for v in RP.WORD_READS.values() if v}
pos_total = pos_pass = 0
per_video = {}
for stem, body, labels, kept in videos:
    t = p = 0
    for i, ch in enumerate(body):
        reads = RP.CHAR_READS.get(ch)
        if not reads:
            continue
        t += 1
        if {RP.base_of(x) for x in reads} & bases:
            p += 1
    pos_total += t
    pos_pass += p
    per_video[stem] = dict(可作起点的汉字位=t, 通过=p, 拦截=t - p)
print('=== 保护拦截面（字符级，窗口起点的必要条件 has_base(字, first_bases)）===')
print('  first_bases 音节数=%d  可作起点的汉字位=%d  通过=%d (%.2f%%)  被拦=%d (%.2f%%)' % (
    len(bases), pos_total, pos_pass, 100.0 * pos_pass / pos_total, pos_total - pos_pass,
    100.0 * (pos_total - pos_pass) / pos_total))

# ---- 2. A/B 行为验证 + 基准数字 ----
res, edits = {}, {}
for name, extra in ARMS:
    agg = dict(tp=0, fp=0, wrong=0, distance=0, e_tp=0, e_fp=0, e_wrong=0)
    per = {}
    for stem, body, labels, kept in videos:
        p = subprocess.run([EXE, '--no-index-cache', '-v'] + extra, input=body.encode('utf-8'),
                           capture_output=True, cwd=str(R))
        assert p.returncode == 0, p.stderr.decode('utf-8', 'replace')[:300]
        out, err = p.stdout.decode('utf-8'), p.stderr.decode('utf-8')
        assert len(out) == len(body), stem
        lst = []
        for m in A.rx.finditer(err):
            kind, a, b, src, dst, d, score, zc, zo = m.groups()
            a, b, d = int(a), int(b), int(d)
            assert body[a:b] == src and out[a:b] == dst, (stem, src)
            changed = [k for k in range(len(src)) if src[k] != dst[k]]
            truth = [labels.get(a + k) for k in changed]
            label = ('excluded' if None in truth else 'TP' if all(dst[k] == v for k, v in zip(changed, truth))
                     else 'FP' if all(src[k] == v for k, v in zip(changed, truth)) else 'wrong')
            lst.append(dict(a=a, b=b, src=src, dst=dst, d=int(d), score=float(score), label=label,
                            kind=kind, chars=len(changed)))
        chars = collections.Counter()
        for i, v in labels.items():
            if out[i] != body[i]:
                chars['TP' if out[i] == v else 'FP' if body[i] == v else 'wrong'] += 1
        dist = sum(A.align(l, r['gt'])[1] for l, r in zip(out.splitlines(), kept))
        agg['tp'] += chars['TP']; agg['fp'] += chars['FP']; agg['wrong'] += chars['wrong']
        agg['distance'] += dist
        agg['e_tp'] += sum(1 for x in lst if x['label'] == 'TP')
        agg['e_fp'] += sum(1 for x in lst if x['label'] == 'FP')
        agg['e_wrong'] += sum(1 for x in lst if x['label'] == 'wrong')
        per[stem] = dict(chars=dict(chars), distance=dist, edits=lst)
        edits[(name, stem)] = lst
    res[name] = dict(total=agg, per=per)
    print('%-26s 改对字=%-4d 误改字=%-4d 错到错=%-4d 总错误量(编辑距离)=%-5d 改对编辑=%-4d 误改编辑=%-4d' % (
        name, agg['tp'], agg['fp'], agg['wrong'], agg['distance'], agg['e_tp'], agg['e_fp']))

# ---- 3. 保护究竟拦住了什么：关掉后才出现的编辑清单 ----
print('\n=== 关掉保护后才出现的编辑（=保护拦下的东西）===')
for on, off_ in (('Z1 默认(生产口径)', 'Z1+关首音节保护'), ('Z2 控制臂 M1M2 K=0.6', 'Z2+关首音节保护')):
    blocked = collections.Counter()
    samples = []
    for stem, _, _, _ in videos:
        keys_on = {(x['a'], x['b'], x['dst']) for x in edits[(on, stem)]}
        for x in edits[(off_, stem)]:
            if (x['a'], x['b'], x['dst']) not in keys_on:
                blocked[x['label']] += 1
                samples.append((stem, x))
        keys_off = {(x['a'], x['b'], x['dst']) for x in edits[(off_, stem)]}
        for x in edits[(on, stem)]:
            if (x['a'], x['b'], x['dst']) not in keys_off:
                blocked['关掉后反而消失(竞争格局变化)'] += 1
    print('  %s → 关保护：新增编辑 %s' % (on, dict(blocked)))
    for stem, x in samples[:10]:
        print('    %-16s %s->%s d=%s score=%+.3f [%s]' % (stem[:16], x['src'], x['dst'], x['d'], x['score'], x['label']))

# ---- 4. 冻结基准 ----
base = dict(
    date='2026-11-08', purpose='首音节保护确认 + 七篇对照基准冻结',
    binary_sha256_16=hashlib.sha256(open(EXE, 'rb').read()).hexdigest()[:16],
    data_sha256_16={p: hashlib.sha256(open(R / p, 'rb').read()).hexdigest()[:16] for p in [
        'data/frequency/word_freq.tsv', 'data/frequency/char_freq.tsv', 'data/correction/candidates.tsv',
        'data/ac/ac_lock.tsv', 'data/vocabulary/vocabulary.tsv', 'data/vocabulary/extvocabulary.tsv',
        'data/pronunciation/pronunciation.tsv', 'data/pronunciation/pronunciation_char.tsv']},
    enforcement_points=[
        'src/text_cleaner.cpp:303 窗口起点门（受 --no-first-syllable-gate 控制，默认开）',
        'src/text_cleaner.cpp:311 索引首音节过滤 require_first（同一开关控制，默认开）',
        'src/text_cleaner.cpp:283 边缘窗口起点门（**不受开关控制，始终生效**）'],
    gate_reach=dict(first_bases=len(bases), positions=pos_total, passed=pos_pass, blocked=pos_total - pos_pass),
    arms={k: v['total'] for k, v in res.items()},
    per_video={k: {s: dict(chars=d['chars'], distance=d['distance']) for s, d in v['per'].items()}
               for k, v in res.items()},
    blocked_by_gate={on: dict(collections.Counter(
        x['label'] for stem, _, _, _ in videos for x in edits[(off_, stem)]
        if (x['a'], x['b'], x['dst']) not in {(y['a'], y['b'], y['dst']) for y in edits[(on, stem)]}))
        for on, off_ in (('Z1 默认(生产口径)', 'Z1+关首音节保护'), ('Z2 控制臂 M1M2 K=0.6', 'Z2+关首音节保护'))},
    command='build/e025/text_clean.exe --no-index-cache [-v] {见 arms 参数}',
    metric='experiments/E024/scripts/align_lib.py（E022 起口径，未改动）')
(O / 'baseline.json').write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding='utf-8')
json.dump({f'{k}|{s}': v for (k, s), v in edits.items()}, (O / 'edits.json').open('w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('\n基准写入 experiments/E027/results/baseline.json')
