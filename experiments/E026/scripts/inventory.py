#!/usr/bin/env python3
"""E026 第一步：固定真值错误实例清单 + 三臂运行 + 校准断言。

配置声明（避免与 E024/E025 混用）：
  Z1 = zipf 默认 veto                     期望 64/87/2047（E025 记录）
  Z2 = zipf + M1M2 K=0.6（控制臂）        期望 147/100/1977（E024/E025 记录）
  C2 = 旧次数公式 + 旧次数表 + 旧字频表   期望 196/97/1925（E025 记录）
三臂都用同一个冻结二进制、同一 data/ 候选池与 AC、同一 asr/ 真值；断言不通过就停止，
不允许拿不同评分臂的数字拼在一起比。

错误实例 = 一行内连续的对齐不一致位置（唯一对齐才计入，歧义位置整条排除，口径同 E022-E025）。
"""
import collections, hashlib, json, pathlib, re, subprocess, sys

R = pathlib.Path(__file__).resolve().parents[3]
O = R / 'experiments/E026/results'
O.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(R / 'experiments/E024/scripts'))
import align_lib as A

EXE = str(R / 'build/e025/text_clean.exe')
ARMS = {
    'Z1': [],
    'Z2': ['--missing-evidence', 'char', '--missing-cap', '0.6'],
    'C2': ['--word-freq', 'data/old/word_freq.txt', '--char-freq', 'data/old/dict.txt'],
}
EXPECT = {'Z1': (64, 87, 2047), 'Z2': (147, 100, 1977), 'C3': (0, 0, 0), 'C2': (196, 97, 1925)}

# 启用候选池：目标词 -> 别称集合；以及别称 -> 目标词
targets, alias_owner = set(), collections.defaultdict(set)
for line in (R / 'data/correction/candidates.tsv').read_text(encoding='utf-8').splitlines():
    if not line or line.startswith('#'):
        continue
    f = line.rstrip('\n').split('\t')
    if len(f) < 5 or f[0] == 'canonical' or f[4] != '1':
        continue
    targets.add(f[0])
    for a in [x for x in f[2].split('|') if x]:
        alias_owner[a].add(f[0])

videos, errors = [], []
for path in sorted((R / 'asr').glob('*.gt.jsonl')):
    rows = [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]
    assert not any(r.get('pending') for r in rows), path
    kept = [r for r in rows if not r.get('discard')]
    body = '\n'.join(r['text'] for r in kept) + '\n'
    labels = {}
    offset = 0
    for row in kept:
        lab, _ = A.align(row['text'], row['gt'])
        labels.update({offset + k: v for k, v in lab.items()})
        offset += len(row['text']) + 1
    videos.append((path.stem, body, labels, kept, offset))
    # 连续不一致位置成一条错误实例
    pos, line_off = 0, 0
    for li, row in enumerate(kept):
        text = row['text']
        i = 0
        while i < len(text):
            g = labels.get(line_off + i)
            if g is None or g == text[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(text) and labels.get(line_off + j + 1) not in (None,) and labels.get(line_off + j + 1) != text[j + 1]:
                j += 1
            seg = text[i:j + 1]
            truth = ''.join(labels.get(line_off + k) or text[k] for k in range(i, j + 1))
            if None not in [labels.get(line_off + k) for k in range(i, j + 1)]:
                errors.append(dict(video=path.stem, line=li, begin=line_off + i, end=line_off + j + 1,
                                   local=i, original=seg, truth=truth, line_text=text, line_truth=row['gt']))
            i = j + 1
        line_off += len(text) + 1

CACHE = O / 'run_cache.json'
key = hashlib.sha256(open(EXE, 'rb').read()).hexdigest() + json.dumps(ARMS, sort_keys=True)
run = {}
if CACHE.exists() and json.loads(CACHE.read_text(encoding='utf-8')).get('key') == key:
    raw = json.loads(CACHE.read_text(encoding='utf-8'))['run']
    for arm, per in raw.items():
        run[arm] = {s: dict(chars=collections.Counter(v['chars']), distance=v['distance'],
                            applied=v['applied'], out=v['out']) for s, v in per.items()}
    print('复用 run_cache（二进制+臂配置未变）')
for arm, extra in ARMS.items():
    if arm in run:
        continue
    per = {}
    for stem, body, labels, kept, _ in videos:
        p = subprocess.run([EXE, '--no-index-cache', '-v'] + extra, input=body.encode('utf-8'),
                           capture_output=True, cwd=str(R))
        assert p.returncode == 0, p.stderr.decode('utf-8', 'replace')[:300]
        out, err = p.stdout.decode('utf-8'), p.stderr.decode('utf-8')
        assert len(out) == len(body), stem
        applied = [dict(zip(('kind', 'a', 'b', 'src', 'dst', 'd', 'score', 'zc', 'zo'), m.groups()))
                   for m in A.rx.finditer(err)]
        for x in applied:
            x['a'], x['b'], x['d'], x['score'] = int(x['a']), int(x['b']), int(x['d']), float(x['score'])
            x['src_span'] = body[x['a']:x['b']]
            assert x['src_span'] == x['src'] and out[x['a']:x['b']] == x['dst'], (stem, x)
        chars = collections.Counter()
        for i, v in labels.items():
            if out[i] != body[i]:
                chars['TP' if out[i] == v else 'FP' if body[i] == v else 'wrong'] += 1
        dist = sum(A.align(l, r['gt'])[1] for l, r in zip(out.splitlines(), kept))
        per[stem] = dict(chars=chars, distance=dist, applied=applied, out=out)
    tp = sum(v['chars']['TP'] for v in per.values())
    fp = sum(v['chars']['FP'] for v in per.values())
    wr = sum(v['chars']['wrong'] for v in per.values())
    dt = sum(v['distance'] for v in per.values())
    print('%s 改对字=%d 误改字=%d 错到错=%d 总距离=%d  期望=%s' % (arm, tp, fp, wr, dt, EXPECT[arm]))
    assert (tp, fp, dt) == EXPECT[arm], ('臂配置与 E025 记录不一致，停止', arm, (tp, fp, wr, dt), EXPECT[arm])
    run[arm] = per

if not CACHE.exists() or json.loads(CACHE.read_text(encoding='utf-8')).get('key') != key:
    CACHE.write_text(json.dumps(dict(key=key, run={a: {s: dict(chars=dict(v['chars']), distance=v['distance'],
                                            applied=v['applied'], out=v['out']) for s, v in per.items()}
                                            for a, per in run.items()}), ensure_ascii=False), encoding='utf-8')

# 每条错误实例在各臂的状态
for e in errors:
    for arm, per in run.items():
        v = per[e['video']]
        hits = [x for x in v['applied'] if x['a'] == e['begin'] and x['b'] == e['end']]
        overlap = [x for x in v['applied'] if x['a'] < e['end'] and x['b'] > e['begin'] and not hits]
        e[arm] = dict(applied=(v['out'][e['begin']:e['end']] == e['truth']), hit=hits or None,
                      overlap=[dict(src=x['src'], dst=x['dst'], d=x['d'], score=x['score']) for x in overlap])
        e[arm + '_chars'] = sum(1 for i in range(e['begin'], e['end']) if v['out'][i] != e['original'][i - e['begin']])

# 汇总：错误实例规模与 S1 候选池覆盖
stat = collections.Counter()
for e in errors:
    stat['实例总数'] += 1
    stat['实例字数'] += len(e['original'])
    stat['S1_真值目标在启用候选池'] += (e['truth'] in targets)
    stat['S1_错串本身是某目标的启用别称'] += (e['truth'] in alias_owner.get(e['original'], ()))
    for arm in ARMS:
        stat['%s_已改对' % arm] += e[arm]['applied']
json.dump(dict(stat=dict(stat), n_errors=len(errors)), (O / 'inventory_summary.json').open('w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
(O / 'errors.json').write_text(json.dumps(errors, ensure_ascii=False, indent=1), encoding='utf-8')
(O / 'applied.json').write_text(json.dumps({a: {s: dict(chars=dict(v['chars']), distance=v['distance'], applied=v['applied'])
                                                for s, v in per.items()} for a, per in run.items()},
                                           ensure_ascii=False, indent=1), encoding='utf-8')
print('\n错误实例=%d 个 / %d 字；候选池覆盖真值目标=%d 个实例' % (
    len(errors), sum(len(e['original']) for e in errors), sum(1 for e in errors if e['truth'] in targets)))
print(json.dumps(dict(stat), ensure_ascii=False, indent=1))
