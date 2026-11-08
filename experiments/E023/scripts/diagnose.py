#!/usr/bin/env python3
"""E023 诊断：Zipf 接入退步的漏斗定位 + 最小消融。

指标口径逐字复制 experiments/E022/scripts/regression.py（E19 数字归一化 + 全最优路径唯一对齐），
并在开始时断言自己的 noop/counts/zipf 三臂与 E022 已保存 summary 完全一致，防止口径漂移。
只读运行，不写真值、不改生产码；消融用 experiments/E023/probe 编译出的独立二进制。
"""
import collections, decimal, hashlib, json, os, pathlib, re, subprocess, sys

R = pathlib.Path(__file__).resolve().parents[3]
E = R / 'experiments/E023'
E022 = R / 'experiments/E022'
O = E / 'results'
O.mkdir(parents=True, exist_ok=True)
DATA = R / 'data'

# ---------- 指标（复制自 E022，未改动） ----------
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


rx = re.compile(r'\[(\w+)\] status=\w+ (\d+)\.\.(\d+) "([^"]*)" -> "([^"]*)" entry=\d+ distance=(\d+) score=([\d.e+-]+).*?action=replace')
rx_zipf = re.compile(r'zipfC=(\S+) zipfO=(\S+)')


def save(name, obj):
    (O / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def run(exe, body, args, env=None):
    p = subprocess.run([str(exe), *args], input=body.encode('utf-8'), capture_output=True, cwd=str(R),
                       env={**os.environ, **(env or {})})
    assert p.returncode == 0, p.stderr.decode('utf-8', 'replace')[:400]
    return p.stdout.decode('utf-8'), p.stderr.decode('utf-8')


BASE = ['--no-index-cache']
ARMS = {
    'noop': None,
    'counts': (R / 'build/current/text_clean.exe', BASE + ['--word-freq', str(DATA / 'old/word_freq.txt'), '--char-freq', str(DATA / 'old/dict.txt')]),
    'zipf': (R / 'build/current/text_clean.exe', list(BASE)),
    'zipfB_旧缺频策略': (E / 'build/text_clean_B.exe', list(BASE)),
    'zipfC_旧字符补偿': (E / 'build/text_clean_C.exe', list(BASE)),
}
ARM_ENV = {'zipfC_旧字符补偿': {'TC_CHAR_FREQ': str(DATA / 'frequency/char_freq.tsv')}}

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
    videos.append((path.stem, body, labels, kept, distance))

summary = {}
funnels = {}
lost = []
details = {}
for stem, body, labels, kept, distance in videos:
    per = {}
    for mode, spec in ARMS.items():
        if spec is None:
            output, stderr = body, ''
        else:
            exe, args = spec
            output, stderr = run(exe, body, ['-v'] + args, env=ARM_ENV.get(mode))
        assert len(output) == len(body), (stem, mode)
        edits = []
        for m in rx.finditer(stderr):
            kind, a, b, src, dst, d, score = m.groups()
            a, b, d = int(a), int(b), int(d)
            assert body[a:b] == src and output[a:b] == dst
            changed = [k for k in range(len(src)) if src[k] != dst[k]]
            truth = [labels.get(a + k) for k in changed]
            label = 'excluded' if None in truth else 'TP' if all(dst[k] == v for k, v in zip(changed, truth)) else 'FP' if all(src[k] == v for k, v in zip(changed, truth)) else 'wrong'
            edits.append(dict(a=a, b=b, src=src, dst=dst, d=d, score=float(score), label=label))
        chars = collections.Counter()
        for i, v in labels.items():
            if output[i] != body[i]: chars['TP' if output[i] == v else 'FP' if body[i] == v else 'wrong'] += 1
        after = sum(align(line, row['gt'])[1] for line, row in zip(output.splitlines(), kept))
        per[mode] = dict(edits=collections.Counter(x['label'] for x in edits),
                         characters=dict(chars), remaining=chars['TP'], distance=after, edit_list=edits)
    # 漏斗：zipf 模式与 counts 模式各跑一次探针
    for tag, exe, extra in (('zipf', E / 'build/text_clean_F.exe', []),
                            ('counts', E / 'build/text_clean_F.exe', ['--word-freq', str(DATA / 'old/word_freq.txt'), '--char-freq', str(DATA / 'old/dict.txt')])):
        _, stderr = run(exe, body, ['-v'] + extra, env={'TC_FUNNEL': '1'})
        line = [l for l in stderr.splitlines() if l.startswith('#FUNNEL')][0]
        fields = dict(kv.split('=') for kv in line.split()[1:])
        funnels.setdefault(tag, {})
        for k, v in fields.items(): funnels[tag][k] = funnels[tag].get(k, 0) + int(v)
    # 归因：counts 臂改对但 zipf 臂没改的编辑
    zmap = {(x['a'], x['b'], x['dst']): x for x in per['zipf']['edit_list']}
    for x in per['counts']['edit_list']:
        if x['label'] != 'TP': continue
        key = (x['a'], x['b'], x['dst'])
        if key in zmap: continue
        lost.append(dict(video=stem, src=x['src'], dst=x['dst'], d=x['d'], counts_score=x['score'],
                         changed=sum(1 for k in range(len(x['src'])) if x['src'][k] != x['dst'][k])))
    details[stem] = {m: {k: v for k, v in d.items() if k != 'edit_list'} for m, d in per.items()}
    summary_video = {m: (d['characters'].get('TP', 0), d['characters'].get('FP', 0), d['distance']) for m, d in per.items()}
    print(stem, summary_video, flush=True)
    for m, d in per.items():
        agg = summary.setdefault(m, dict(edits=collections.Counter(), chars=collections.Counter(), distance=0, remaining=0))
        agg['edits'].update(d['edits']); agg['chars'].update(d['characters'])
        agg['distance'] += d['distance']; agg['remaining'] += d['characters'].get('TP', 0)

# ---------- 词库侧核对（缺证据判定） ----------
zipf_word = {}
for line in (DATA / 'frequency/word_freq.tsv').read_text(encoding='utf-8').splitlines():
    if not line or line.startswith('#'): continue
    f = line.split('\t')
    if f[0] == 'word' or 'wordfreq' not in f[4]: continue
    v = float(f[1])
    if v > 0: zipf_word[f[0]] = v
enabled = {}
for line in (DATA / 'correction/candidates.tsv').read_text(encoding='utf-8').splitlines():
    if not line or line.startswith('#'): continue
    f = line.split('\t')
    if f[0] == 'canonical' or f[4] != '1': continue
    enabled.setdefault(f[0], []).append(f[2])

for item in lost:
    o, c = item['src'], item['dst']
    if c not in zipf_word: item['cause'] = '目标词无Zipf证据'
    elif o not in zipf_word: item['cause'] = '原文无Zipf证据（缺频保护弃权）'
    else:
        need = (0.7 + 0.65 * item['d']) / 2.302585
        item['cause'] = '两侧都有证据但差额不够'
        item['zipf_gap'] = round(zipf_word[c] - zipf_word[o], 3)
        item['zipf_needed'] = round(need, 3)
cause_stat = collections.Counter(x['cause'] for x in lost)
lost_chars = collections.Counter()
for x in lost: lost_chars[x['cause']] += x['changed']

out = dict(arms={m: dict(edits=dict(v['edits']), characters=dict(v['chars']), normalized_distance_after=v['distance'])
                 for m, v in summary.items()},
           funnel=funnels, lost_tp_count=len(lost), lost_tp_causes=dict(cause_stat),
           lost_tp_characters=dict(lost_chars), lost_cases=lost[:80],
           enabled_targets=len(enabled), zipf_evidence_words=len(zipf_word))
save('diagnosis.json', out)
print('\n=== 各臂汇总 ===')
for m, v in out['arms'].items():
    print('%-16s 改对字=%-4d 误改字=%-4d 错到错=%-4d 改对编辑=%-4d 误改编辑=%-4d 总编辑距离=%d' % (
        m, v['characters'].get('TP', 0), v['characters'].get('FP', 0), v['characters'].get('wrong', 0),
        v['edits'].get('TP', 0), v['edits'].get('FP', 0), v['normalized_distance_after']))
print('漏斗(zipf):', funnels['zipf'])
print('漏斗(counts):', funnels['counts'])
print('counts 改对而 zipf 丢掉的编辑 %d 个，原因分布 %s，字符数 %s' % (len(lost), dict(cause_stat), dict(lost_chars)))
