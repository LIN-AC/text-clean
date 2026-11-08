#!/usr/bin/env python3
"""E025 归因矩阵：冻结同一份词库/候选池/真值/代码，只切换评分口径与保护规则。

三组问题分别对应：
  (a) 公式换算——同一份证据先用 Zipf 公式再用次数公式跑（派生次数表，见 make_derived_counts.py）。
  (b) 词频证据——同一公式换证据来源（派生表 vs 旧 SUBTLEX/lexicon 次数表）。
  (c) 保护规则——单独关 E021 静态否决限制（--no-admission-guard）与首音节锚点保护
      （--no-first-syllable-gate），元数据组用「只从 ASR 文本 + 正式候选表推导的合成标题」放大 bonus。
指标口径逐字沿用 E022/E023/E024（数字归一化 + 全最优路径唯一对齐 + 排除 discard 行）。
"""
import collections, json, os, pathlib, re, subprocess, sys

R = pathlib.Path(__file__).resolve().parents[3]
E = R / 'experiments/E025'
O = E / 'results'
O.mkdir(parents=True, exist_ok=True)
TMP = R / 'build/e025_tmp'
TMP.mkdir(parents=True, exist_ok=True)
EXE = str(R / 'build/e025/text_clean.exe')
DERIVED = str(R / 'build/e025_data/derived_from_zipf.txt')

sys.path.insert(0, str(R / 'experiments/E024/scripts'))
import align_lib as A  # 复用 E024 的数字归一化 + 唯一最优对齐，保证口径逐字相同

COUNTS = ['--word-freq']
ARMS = [
    ('Z1 zipf默认veto', [], None),
    ('Z2 zipf+M1M2 K0.6', ['--missing-evidence', 'char', '--missing-cap', '0.6'], None),
    ('C1 次数公式+同一证据(派生表)', ['--word-freq', DERIVED, '--no-char-baseline'], None),
    ('C2 次数公式+旧证据(旧表)', ['--word-freq', 'data/old/word_freq.txt', '--char-freq', 'data/old/dict.txt'], None),
    ('C3 次数公式+旧表+无字频基线', ['--word-freq', 'data/old/word_freq.txt', '--no-char-baseline'], None),
    ('G1 Z1关静态否决限制', ['--no-admission-guard'], None),
    ('G2 C1关静态否决限制', ['--word-freq', DERIVED, '--no-char-baseline', '--no-admission-guard'], None),
    ('G3 Z1关首音节锚点保护', ['--no-first-syllable-gate'], None),
    ('G4 Z2关首音节锚点保护', ['--missing-evidence', 'char', '--missing-cap', '0.6', '--no-first-syllable-gate'], None),
    ('G5 C1关首音节锚点保护', ['--word-freq', DERIVED, '--no-char-baseline', '--no-first-syllable-gate'], None),
    ('M1 Z1+合成标题', [], 'meta'),
    ('M2 Z1+合成标题+关限制', ['--no-admission-guard'], 'meta'),
    ('M3 C1+合成标题', ['--word-freq', DERIVED, '--no-char-baseline'], 'meta'),
    ('M4 C1+合成标题+关限制', ['--word-freq', DERIVED, '--no-char-baseline', '--no-admission-guard'], 'meta'),
    ('M5 C2+合成标题', ['--word-freq', 'data/old/word_freq.txt', '--char-freq', 'data/old/dict.txt'], 'meta'),
    ('M6 C2+合成标题+关限制', ['--word-freq', 'data/old/word_freq.txt', '--char-freq', 'data/old/dict.txt',
                              '--no-admission-guard'], 'meta'),
]

# ---- 合成标题：只用 ASR 文本 + 正式候选表推导（不读 gt 字段），把 bonus 推到上限 ----
targets_by_alias = {}
for line in (R / 'data/correction/candidates.tsv').read_text(encoding='utf-8').splitlines():
    if not line or line.startswith('#'):
        continue
    row = line.rstrip('\n').split('\t')
    if len(row) < 5 or row[4] != '1':
        continue
    for alias in [row[0]] + ([x for x in row[2].split('|') if x] if row[2] else []):
        targets_by_alias.setdefault(alias, set()).add(row[0])

videos = []
for path in sorted((R / 'asr').glob('*.gt.jsonl')):
    rows = [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]
    assert not any(r.get('pending') for r in rows)
    kept = [r for r in rows if not r.get('discard')]
    body = '\n'.join(r['text'] for r in kept) + '\n'
    labels, offset, distance = {}, 0, 0
    for row in kept:
        lab, dist = A.align(row['text'], row['gt'])
        labels.update({offset + k: v for k, v in lab.items()})
        offset += len(row['text']) + 1
        distance += dist
    hit = set()
    for row in kept:
        for i in range(len(row['text'])):
            for size in (6, 5, 4, 3, 2):
                for t in targets_by_alias.get(row['text'][i:i + size], ()):
                    hit.add(t)
    title_file = TMP / ('title_%s.txt' % path.stem)
    title_file.write_text('\n'.join(sorted(hit) * 2) + '\n', encoding='utf-8')
    videos.append((path.stem, body, labels, kept, str(title_file.relative_to(R)).replace('\\', '/')))
    print('%s 合成标题词数=%d' % (path.stem, len(hit)), file=sys.stderr)

aggregate, vanish, per_video, scale = {}, {}, {}, set()
for stem, body, labels, kept, title_file in videos:
    row_result = {}
    edits_by_arm = {}
    # 真·不纠错臂：不调用二进制，直接按同一口径量原文与真值的距离（第一版误把它当成
    # 一次默认运行，得到 2047 而非 2024；其余臂不依赖该臂，只需修正相对列）。
    noop_chars = collections.Counter()
    noop_dist = sum(A.align(r['text'], r['gt'])[1] for r in kept)
    agg = aggregate.setdefault('noop 不纠错', dict(chars=collections.Counter(), edits=collections.Counter(), distance=0))
    agg['chars'].update(noop_chars)
    agg['distance'] += noop_dist
    row_result['noop 不纠错'] = dict(tp=0, fp=0, wrong=0, distance=noop_dist, edits_tp=0, edits_fp=0)
    for mode, extra, meta in ARMS:
        cmd = [EXE, '--no-index-cache', '-v'] + extra
        if meta:
            cmd += ['--title-file', title_file]
        p = subprocess.run(cmd, input=body.encode('utf-8'), capture_output=True, cwd=str(R))
        assert p.returncode == 0, p.stderr.decode('utf-8', 'replace')[:400]
        output, stderr = p.stdout.decode('utf-8'), p.stderr.decode('utf-8')
        locks = stderr.count('status=ac_locked')
        scale.add((stem, locks))
        assert locks == dict(scale)[stem], '候选池/AC 规模在臂间不一致: %s' % stem
        assert len(output) == len(body), (stem, mode)
        edits = []
        for m in A.rx.finditer(stderr):
            kind, a, b, src, dst, d, score, zc, zo = m.groups()
            a, b, d = int(a), int(b), int(d)
            changed = [i for i in range(len(src)) if src[i] != dst[i]]
            truth = [labels.get(a + i) for i in changed]
            label = ('excluded' if None in truth else 'TP' if all(dst[i] == v for i, v in zip(changed, truth))
                     else 'FP' if all(src[i] == v for i, v in zip(changed, truth)) else 'wrong')
            edits.append(dict(begin=a, end=b, src=src, dst=dst, d=d, score=float(score),
                              zipfC=zc, zipfO=zo, label=label, chars=len(changed)))
        edits_by_arm[mode] = edits
        chars = collections.Counter()
        for i, v in labels.items():
            if output[i] != body[i]:
                chars['TP' if output[i] == v else 'FP' if body[i] == v else 'wrong'] += 1
        after = sum(A.align(line, r['gt'])[1] for line, r in zip(output.splitlines(), kept))
        agg = aggregate.setdefault(mode, dict(chars=collections.Counter(), edits=collections.Counter(), distance=0))
        agg['chars'].update(chars)
        agg['edits'].update(x['label'] for x in edits)
        agg['distance'] += after
        row_result[mode] = dict(tp=chars['TP'], fp=chars['FP'], wrong=chars['wrong'], distance=after,
                                 edits_tp=sum(1 for x in edits if x['label'] == 'TP'),
                                 edits_fp=sum(1 for x in edits if x['label'] == 'FP'))
    per_video[stem] = row_result

    # 消失位置：以「旧次数公式 + 同一证据」(C1) 为参照，看 Zipf 口径丢了哪些正确编辑
    ref = {(x['begin'], x['dst']): x for x in edits_by_arm['C1 次数公式+同一证据(派生表)'] if x['label'] == 'TP'}
    for arm in ('Z1 zipf默认veto', 'Z2 zipf+M1M2 K0.6'):
        cur = {(x['begin'], x['dst']) for x in edits_by_arm[arm] if x['label'] == 'TP'}
        for k, x in ref.items():
            if k not in cur:
                vanish.setdefault(arm, []).append(dict(stem=stem, **x))
    # 旧证据 vs 同证据（都走次数公式）：C2 有而 C1 没有的
    c1 = {(x['begin'], x['dst']) for x in edits_by_arm['C1 次数公式+同一证据(派生表)'] if x['label'] == 'TP'}
    for x in edits_by_arm['C2 次数公式+旧证据(旧表)']:
        if x['label'] == 'TP' and (x['begin'], x['dst']) not in c1:
            vanish.setdefault('C2 旧证据独有', []).append(dict(stem=stem, **x))

out = {'arms': {m: dict(改对字=v['chars']['TP'], 误改字=v['chars']['FP'], 错到错字=v['chars']['wrong'],
                        改对编辑=v['edits']['TP'], 误改编辑=v['edits']['FP'], 错到错编辑=v['edits']['wrong'],
                        总编辑距离=v['distance']) for m, v in aggregate.items()},
       'per_video': per_video, 'vanish': vanish}
(O / 'attribute.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
base = out['arms']['noop 不纠错']['总编辑距离']
print('\n=== 汇总（不纠错=%d）===' % base)
for m, v in out['arms'].items():
    print('%-30s 改对字=%-4d 误改字=%-4d 错到错=%-4d 改对编辑=%-4d 误改编辑=%-4d 总距离=%-5d 相对不纠错=%+d' % (
        m, v['改对字'], v['误改字'], v['错到错字'], v['改对编辑'], v['误改编辑'], v['总编辑距离'],
        v['总编辑距离'] - base))
print('\n=== 正确编辑消失计数 ===')
for arm, lst in vanish.items():
    print('%-22s %d 条（涉及 %d 个视频）' % (arm, len(lst), len({x['stem'] for x in lst})))
