#!/usr/bin/env python3
"""E029｜单字纠错实测：单字目标词改走单字频率表，和上一轮的离线估算对不对得上。

做法（全部在实验目录里做，正式 data/ 一个字节都不改）：
  1) 只用读音表 + 字频表生成一份单字候选池（不看真值）：把同一读音下字频最高的 K 个字
     各作为一条"目标词=单字、别称空"的启用候选，追加到 data 副本里。
  2) 四臂对照，隔离出各因素的贡献：
     R0 正式池，窗口下限 2                     —— 冻结基准
     R1 正式池，窗口下限 1 + 单字频率开关       —— 池里没有单字词，预期仍然 0
     R2 单字池，窗口下限 1，不开单字频率开关     —— 目标查不到证据即弃权，预期 0
     R3 单字池，窗口下限 1 + 单字频率开关       —— 真正的单字纠错
     R4 单字池，窗口下限 2，不开开关            —— 控制"加词把首音节门放宽"带来的副作用
"""
import collections, json, pathlib, re, shutil, subprocess, sys

R = pathlib.Path(__file__).resolve().parents[3]
O = R / 'experiments/E029/results'
O.mkdir(parents=True, exist_ok=True)
POOL = R / 'build/e029_data'
K = 10
sys.path.insert(0, str(R / 'experiments/E024/scripts'))
import align_lib as A
sys.stdout.reconfigure(encoding='utf-8')
EXE = 'build/e025/text_clean.exe'


def lines(path):
    return (l for l in (R / path).read_text(encoding='utf-8').splitlines() if l and not l.startswith('#'))


# ---------- 1. 生成单字候选池（只读表，不看真值） ----------
char_zipf = {}
for l in lines('data/frequency/char_freq.tsv'):
    f = l.split('\t')
    if len(f) > 1 and f[0] != 'char':
        try:
            v = float(f[1])
        except ValueError:
            continue
        if v > 0:
            char_zipf[f[0]] = v
groups = collections.defaultdict(set)
for l in lines('data/pronunciation/pronunciation_char.tsv'):
    f = l.split('\t')
    if len(f) < 2 or f[0] == 'char' or f[1] in ('', '-'):
        continue
    for syl in re.split(r'[|\s]+', f[1]):
        if syl and syl != '-' and syl != f[0] and len(syl) > 1 and syl[-1].isdigit():
            groups[syl.lower()].add(f[0])
rows = []
for syl, chars in groups.items():
    chars = [c for c in chars if c in char_zipf]
    if len(chars) < 2:
        continue
    top = sorted(chars, key=lambda c: -char_zipf[c])[:K]
    for ch in top:
        rows.append((ch, syl))
unique = sorted({ch for ch, _ in rows})
print('单字候选池：按读音分组 %d 组，每组取字频前 %d → 去重后 %d 个单字目标词' % (len(groups), K, len(unique)))

if POOL.exists():
    shutil.rmtree(POOL)
shutil.copytree(R / 'data', POOL, ignore=shutil.ignore_patterns('raw', 'generated'))
with (POOL / 'correction/candidates.tsv').open('a', encoding='utf-8', newline='\n') as f:
    f.write('# E029 实验追加：单字候选（来源=读音表+字频表前K，不看真值）\n')
    for ch, syl in sorted(set(rows)):
        f.write('%s\t%s\t\tE029实验\t1\n' % (ch, syl))

# ---------- 2. 四臂对照 ----------
vids = {}
for p in sorted((R / 'asr').glob('*.gt.jsonl')):
    kept = [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]
    kept = [r for r in kept if not r.get('discard')]
    body = '\n'.join(r['text'] for r in kept) + '\n'
    labels, off = {}, 0
    for r in kept:
        lab, _ = A.align(r['text'], r['gt'])
        labels.update({off + k: v for k, v in lab.items()})
        off += len(r['text']) + 1
    vids[p.stem] = (body, labels, kept)

ARMS = [
    ('R0 正式池 窗2（基准）', 'data', []),
    ('R1 正式池 窗1+字频开关', 'data', ['--min-window', '1', '--target-char-freq']),
    ('R2 单字池 窗1 不开开关', 'e029', ['--min-window', '1']),
    ('R3 单字池 窗1+字频开关', 'e029', ['--min-window', '1', '--target-char-freq']),
    ('R4 单字池 窗2 不开开关', 'e029', []),
    ('R5 单字池 窗1 控制臂 不开开关', 'e029', ['--min-window', '1', '--missing-evidence', 'char', '--missing-cap', '0.6']),
    ('R6 单字池 窗1 控制臂+字频开关', 'e029', ['--min-window', '1', '--missing-evidence', 'char', '--missing-cap', '0.6', '--target-char-freq']),
    ('R7 正式池 窗1 控制臂+字频开关', 'data', ['--min-window', '1', '--missing-evidence', 'char', '--missing-cap', '0.6', '--target-char-freq']),
]
summary, one_char_edits = {}, {}
for name, which, extra in ARMS:
    ddir = str(R / 'build/e029_data') if which == 'e029' else 'data'
    tp = fp = wr = dist = 0
    o1 = collections.Counter()
    samples = []
    for stem, (body, labels, kept) in vids.items():
        p = subprocess.run([EXE, '--data-dir', ddir, '--no-index-cache', '-v'] + extra,
                           input=body.encode('utf-8'), capture_output=True, cwd=str(R))
        assert p.returncode == 0, p.stderr.decode('utf-8', 'replace')[:300]
        out, err = p.stdout.decode('utf-8'), p.stderr.decode('utf-8')
        for m in A.rx.finditer(err):
            kind, a, b, src, dst, d, sc, zc, zo = m.groups()
            a = int(a)
            if len(src) == 1:
                truth = labels.get(a)
                lab = 'TP' if truth == dst else 'FP' if truth is None or src == truth and dst != truth else 'wrong'
                o1[lab] += 1
                if len(samples) < 14:
                    samples.append((stem, a, src, dst, truth, sc))
        tp += sum(1 for i, v in labels.items() if out[i] != body[i] and out[i] == v)
        fp += sum(1 for i, v in labels.items() if out[i] != body[i] and body[i] == v)
        wr += sum(1 for i, v in labels.items() if out[i] != body[i] and out[i] != v and body[i] != v)
        dist += sum(A.align(l, r['gt'])[1] for l, r in zip(out.splitlines(), kept))
    summary[name] = dict(tp=tp, fp=fp, wrong=wr, distance=dist, single_char=o1['TP'],
                         single_fp=o1['FP'], single_wrong=o1['wrong'])
    one_char_edits[name] = samples
    print('%-24s 改对字=%-4d 误改字=%-4d 错到错=%-4d 总错误量=%-5d | 其中单字编辑 对%d 错改%d 错到错%d' % (
        name, tp, fp, wr, dist, o1['TP'], o1['FP'], o1['wrong']))

print('\n=== 单字池样例（原文→候选，真值，分数）R3 ===')
for s in one_char_edits['R3 单字池 窗1+字频开关'][:12]:
    print('  %s:%d %s→%s 真值=%s score=%s' % (s[0][:14], s[1], s[2], s[3], s[4], s[5]))
base = summary['R0 正式池 窗2（基准）']
print('\n相对基准 R0 的变化：')
for name in summary:
    v = summary[name]
    print('  %-24s 改对%+d 误改%+d 错到错%+d 总错误量%+d' % (
        name, v['tp'] - base['tp'], v['fp'] - base['fp'], v['wrong'] - base['wrong'], v['distance'] - base['distance']))
json.dump(dict(arms=summary, single_pool_size=len(unique), samples=one_char_edits),
          (O / 'single_char_run.json').open('w', encoding='utf-8'), ensure_ascii=False, indent=1)
