#!/usr/bin/env python3
"""E024 消融矩阵：M1（字频补原文证据）、M2（缺证据额度上限 K）、M1+M2。

指标口径逐字沿用 E022/E023（E19 数字归一化 + 全最优路径唯一对齐 + 排除三处 discard）。
对照二进制：build/current = HEAD 基线；build/ablation = 新分支（默认 veto 已验证与基线逐字节相同）。
只读运行：不改真值、不改词库、不新增特例。
"""
import collections, decimal, json, os, pathlib, re, subprocess

R = pathlib.Path(__file__).resolve().parents[3]
E = R / 'experiments/E024'
O = E / 'results'
O.mkdir(parents=True, exist_ok=True)
DATA = R / 'data'

D = {c: i for i, c in enumerate('零一二三四五六七八九')}; D.update({'〇': 0, '两': 2})
U = {'十': 10, '百': 100, '千': 1000, '万': 10000, '亿': 100000000}


def number(s):
    scale = 1
    if ('.' in s or '点' in s) and s[-1:] in ('万', '亿'): scale = U[s[-1]]; s = s[:-1]
    if '.' in s or '点' in s:
        a, b = re.split('[.点]', s)
        v = decimal.Decimal(number(a) + '.' + ''.join(str(D.get(c, c)) for c in b)) * scale
        return format(v, 'f').rstrip('0').rstrip('.') if '.' in format(v, 'f') else str(v)
    if not any(c in U for c in s): return str(int(''.join(str(D.get(c, c)) for c in s)))
    total = section = n = 0
    for c in s:
        if c not in U: n = n * 10 + int(D.get(c, c)); continue
        u = U[c]
        if u < 10000: section += (n or 1) * u; n = 0
        else:
            section += n
            if u == 100000000: total = (total + section) * u
            else: total += section * u
            section = n = 0
    return str(total + section + n)


NUM = re.compile('[0-9零〇一二两三四五六七八九十百千万亿]+(?:[.点][0-9零〇一二两三四五六七八九]+)?[万亿]?')


def tokens(s):
    out = []; i = 0
    while i < len(s):
        m = NUM.match(s, i)
        if m and (len(m[0]) > 1 or m[0].isascii() or m[0] in U): out.append(('#' + number(m[0]), i, m.end(), True)); i = m.end()
        elif re.match('[一-鿿A-Za-z0-9]', s[i]): out.append((s[i], i, i + 1, False)); i += 1
        else: i += 1
    return out


def align(src, tgt):
    a, b = tokens(src), tokens(tgt); n, m = len(a), len(b)
    def eq(i, j):
        x, y = a[i][0], b[j][0]
        return x == y or (x in D and y == '#' + str(D[x])) or (y in D and x == '#' + str(D[y]))
    f = [[0] * (m + 1) for _ in range(n + 1)]; q = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1): f[i][0] = i; q[i][m] = n - i
    for j in range(m + 1): f[0][j] = j; q[n][j] = m - j
    for i in range(1, n + 1):
        for j in range(1, m + 1): f[i][j] = min(f[i - 1][j] + 1, f[i][j - 1] + 1, f[i - 1][j - 1] + (not eq(i - 1, j - 1)))
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1): q[i][j] = min(q[i + 1][j] + 1, q[i][j + 1] + 1, q[i + 1][j + 1] + (not eq(i, j)))
    labels = {}
    for i, x in enumerate(a):
        if x[3]: continue
        possible = set()
        for j in range(m + 1):
            if f[i][j] + 1 + q[i + 1][j] == f[n][m]: possible.add(None)
            if j < m and f[i][j] + (not eq(i, j)) + q[i + 1][j + 1] == f[n][m]: possible.add(j)
        if len(possible) == 1 and None not in possible:
            y = b[next(iter(possible))]
            if not y[3]: labels[x[1]] = y[0]
    return labels, f[n][m]


# zipfC/zipfO 设为可选：旧次数模式不打印这两个字段，编辑级计数也必须能统计到
rx = re.compile(r'\[(\w+)\] status=\w+ (\d+)\.\.(\d+) "([^"]*)" -> "([^"]*)" entry=\d+ distance=(\d+) '
                r'score=([\d.e+-]+).*?action=replace(?:.*?zipfC=(\S+) zipfO=(\S+))?')

NEW = str(R / 'build/ablation/text_clean.exe')
OLD = str(R / 'build/current/text_clean.exe')
# 第一轮 K={1.0,1.5,2.0,3.0} 四档结果逐字节相同：该区间已饱和。原因是旧口径
# 的缺证据额度 ln(1+fC)≈1.4 换成 zipf 档要除以 ln10，即 Δzipf≈0.61，
# 所以有效区间在 0.1~1.0，而不是 E023 建议的 1~3（那是我的换算漏项）。
KS = [0.45, 0.6, 0.9]   # 0.15/0.3 已证明与 veto 数学等价（K 小于 d=0 门槛），不再重复跑
ARMS = [('noop', None, None)]
ARMS.append(('旧次数counts(上限参照)', OLD, ['--word-freq', str(DATA / 'old/word_freq.txt'), '--char-freq', str(DATA / 'old/dict.txt')]))
ARMS.append(('zipf基线veto', NEW, []))
ARMS.append(('M1_字频补证据', NEW, ['--missing-evidence','char']))
for k in KS:
    ARMS.append(('M2_上限K=%s' % k, NEW, ['--missing-evidence','fixed','--missing-cap', str(k)]))
for k in KS:
    ARMS.append(('M1M2_K=%s' % k, NEW, ['--missing-evidence','char','--missing-cap', str(k)]))
# M3：目标词缺词级证据时用字频 Zipf 兜底。控制组是 M1M2_K=0.6。
ARMS.append(('M1M3_无上限', NEW, ['--missing-evidence','char','--target-fallback']))
for k in KS:
    ARMS.append(('M1M2M3_K=%s' % k, NEW, ['--missing-evidence','char','--missing-cap', str(k), '--target-fallback']))

videos = []
for path in sorted((R / 'asr').glob('*.gt.jsonl')):
    rows = [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]
    assert not any(r.get('pending') for r in rows)
    kept = [r for r in rows if not r.get('discard')]
    body = '\n'.join(r['text'] for r in kept) + '\n'
    labels = {}; offset = 0; distance = 0
    for row in kept:
        lab, dist = align(row['text'], row['gt'])
        labels.update({offset + k: v for k, v in lab.items()})
        offset += len(row['text']) + 1
        distance += dist
    videos.append((path.stem, body, labels, kept))

aggregate = {}
cases = {}
per_video = {}
for stem, body, labels, kept in videos:
    row_result = {}
    for mode, exe, extra in ARMS:
        if exe is None:
            output, stderr = body, ''
        else:
            p = subprocess.run([exe, '--no-index-cache', '-v'] + (extra or []), input=body.encode('utf-8'),
                               capture_output=True, cwd=str(R))
            assert p.returncode == 0, p.stderr.decode('utf-8', 'replace')[:300]
            output, stderr = p.stdout.decode('utf-8'), p.stderr.decode('utf-8')
        assert len(output) == len(body), (stem, mode)
        edits = []
        for m in rx.finditer(stderr):
            kind, a, b, src, dst, d, score, zc, zo = m.groups()
            a, b, d = int(a), int(b), int(d)
            changed = [i for i in range(len(src)) if src[i] != dst[i]]
            truth = [labels.get(a + i) for i in changed]
            label = ('excluded' if None in truth else 'TP' if all(dst[i] == v for i, v in zip(changed, truth))
                     else 'FP' if all(src[i] == v for i, v in zip(changed, truth)) else 'wrong')
            edits.append(dict(begin=a, end=b, src=src, dst=dst, d=d, zipfC=zc, zipfO=zo, label=label,
                              chars=len(changed)))
        chars = collections.Counter()
        for i, v in labels.items():
            if output[i] != body[i]: chars['TP' if output[i] == v else 'FP' if body[i] == v else 'wrong'] += 1
        after = sum(align(line, r['gt'])[1] for line, r in zip(output.splitlines(), kept))
        agg = aggregate.setdefault(mode, dict(chars=collections.Counter(), edits=collections.Counter(),
                                              distance=0, videos=0))
        agg['chars'].update(chars); agg['edits'].update(x['label'] for x in edits)
        agg['distance'] += after; agg['videos'] += 1
        row_result[mode] = dict(tp=chars['TP'], fp=chars['FP'], wrong=chars['wrong'],
                                distance=after, edits_tp=sum(1 for x in edits if x['label'] == 'TP'))
        if mode in ('M1M2_K=0.6', 'M1M2M3_K=0.6', 'M1M3_无上限', 'M1_字频补证据'):
            keep = []
            for x in edits:
                if x['label'] not in ('TP', 'FP'):
                    continue
                lo = max(0, x['begin'] - 10)
                keep.append(dict(x, ctx=body[lo:x['end'] + 10].replace('\n', '¦')))
            cases.setdefault(mode, {})[stem] = keep
    per_video[stem] = row_result
    print(stem, json.dumps(row_result, ensure_ascii=False), flush=True)

out = {'arms': {m: dict(改对字=v['chars']['TP'], 误改字=v['chars']['FP'], 错到错字=v['chars']['wrong'],
                        改对编辑=v['edits']['TP'], 误改编辑=v['edits']['FP'], 错到错编辑=v['edits']['wrong'],
                        总编辑距离=v['distance']) for m, v in aggregate.items()},
       'per_video': per_video, 'cases': cases}
(O / 'arms.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
print('\n=== 汇总 ===')
for m, v in out['arms'].items():
    print('%-22s 改对字=%-4d 误改字=%-4d 错到错=%-4d 改对编辑=%-4d 误改编辑=%-4d 总距离=%-5d 相对不纠错=%+d' % (
        m, v['改对字'], v['误改字'], v['错到错字'], v['改对编辑'], v['误改编辑'], v['总编辑距离'],
        v['总编辑距离'] - out['arms']['noop']['总编辑距离']))
