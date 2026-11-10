#!/usr/bin/env python3
"""E033 第一步：只改一件事——上下文表要不要保留句内边界。

背景：E031 建表时把非汉字替成空格，随后 `chars = [c for c in seg if c != ' ']` 又把空格删掉，
等于让标点/空格两侧的字直接相邻；`seq`（保留边界的写法）算出来却没用于计数。
本脚本用**同一份语料、同一套阈值**建两张表，只差这一个变量：
  repro   —— 复现旧行为（删空格，两侧相连）
  bounded —— 保留边界（非汉字就是边界，串不跨边界生成）
输出放 build/，正式词库 data/ 一字不动。
"""
import collections, json, math, pathlib, re, sys

R = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(R / 'experiments/E024/scripts'))
sys.stdout.reconfigure(encoding='utf-8')

CEDICT = R / 'data/raw/cedict_ts.u8'
MODERN_TSV = R / 'build/e031_corpus/cmn_sentences.tsv'
MIN_COUNT, MAX_N = 2, 4


def trad_simp_map():
    pairs = collections.defaultdict(collections.Counter)
    for line in CEDICT.read_text(encoding='utf-8').splitlines():
        if line.startswith('#'):
            continue
        m = re.match(r'(\S+)\s+(\S+)\s+\[', line)
        if not m:
            continue
        t, s = m.group(1), m.group(2)
        if len(t) == len(s) and t:
            for a, b in zip(t, s):
                if a != b and '一' <= a <= '鿿':
                    pairs[a][b] += 1
    return {a: c.most_common(1)[0][0] for a, c in pairs.items()}


TS = trad_simp_map()


def to_simp(text):
    out = []
    for ch in text:
        if ch in TS:
            out.append(TS[ch])
        elif '一' <= ch <= '鿿':
            out.append(ch)
        else:
            out.append(' ')
    return ''.join(out)


def sentences():
    raw = MODERN_TSV.read_text(encoding='utf-8', errors='replace')
    out = []
    for line in raw.split('\n'):
        parts = line.split('\t')
        if len(parts) >= 3:
            out.append(to_simp(parts[2]))
    return out


def count(segs, bounded):
    ngrams, unis, pairs, positions = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
    for seg in segs:
        runs = seg.split(' ') if bounded else [''.join(seg.split(' '))]
        for run in runs:
            for c in run:
                unis[c] += 1
            for a, b in zip(run, run[1:]):
                pairs[(a, b)] += 1
            for n in range(2, MAX_N + 1):
                positions[n] += max(0, len(run) - n + 1)
                for i in range(len(run) - n + 1):
                    ngrams[run[i:i + n]] += 1
    return ngrams, unis, pairs, positions


def write(out, ngrams, unis, pairs, note):
    out.mkdir(parents=True, exist_ok=True)
    kept = {g: c for g, c in ngrams.items() if c >= MIN_COUNT}
    with (out / 'ngrams.tsv').open('w', encoding='utf-8', newline='\n') as f:
        f.write('# E033 邻接 n-gram 计数（%s，2~%d 字串，次数>=%d）\n' % (note, MAX_N, MIN_COUNT))
        f.write('text\tcount\tlength\n')
        for g, c in sorted(kept.items(), key=lambda x: -x[1]):
            f.write('%s\t%d\t%d\n' % (g, c, len(g)))
    with (out / 'unis.tsv').open('w', encoding='utf-8', newline='\n') as f:
        f.write('char\tcount\n')
        for c, k in unis.most_common():
            f.write('%s\t%d\n' % (c, k))
    with (out / 'pairs.tsv').open('w', encoding='utf-8', newline='\n') as f:
        f.write('left\tright\tcount\n')
        for (a, b), k in pairs.most_common():
            if k >= 3:
                f.write('%s\t%s\t%d\n' % (a, b, k))
    return kept


def main():
    segs = sentences()
    print('语料 %s，句数 %d' % (MODERN_TSV.name, len(segs)), flush=True)
    reps = []
    bounds = []
    for bounded in (False, True):
        ng, un, pr, pos = count(segs, bounded)
        kept = write(R / ('build/e033_ctx_' + ('bounded' if bounded else 'repro')), ng, un, pr,
                     '保留句内边界' if bounded else '复现旧行为：删空格')
        reps.append(kept)
        print('%-8s n-gram 行 %d（2字%d／3字%d／4字%d） 单字 %d 相邻对 %d' % (
            'bounded' if bounded else 'repro', len(kept),
            sum(1 for g in kept if len(g) == 2), sum(1 for g in kept if len(g) == 3),
            sum(1 for g in kept if len(g) == 4), len(un), sum(1 for v in pr.values() if v >= 3)), flush=True)
    old, new = reps
    only_old = [g for g in old if g not in new]
    tot_old = sum(old[g] for g in only_old)
    print('\n只在旧表里出现、保留边界后就消失的串：%d 条，累计出现 %d 次' % (len(only_old), tot_old))
    for g in sorted(only_old, key=lambda x: -old[x])[:12]:
        print('   %r 旧计数 %d' % (g, old[g]))
    shipped = {}
    p = R / 'data/context/modern/ngrams.tsv'
    for line in p.read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#') or line.startswith('text'):
            continue
        f = line.split('\t')
        shipped[f[0]] = int(f[1])
    print('\n正式表 data/context/modern/ngrams.tsv 行数 %d；与 repro 复现表比较：共有 %d，只有正式表有 %d，只有复现表有 %d' % (
        len(shipped), len(set(shipped) & set(old)), len(set(shipped) - set(old)), len(set(old) - set(shipped))))
    diff = [(g, shipped[g], old[g]) for g in list(set(shipped) & set(old)) if shipped[g] != old[g]]
    print('共有串里计数不一致的：%d 条，最大差 %s' % (len(diff), max((abs(a - b) for _, a, b in diff), default=0)))
    (R / 'experiments/E033/results/table_diff.json').write_text(json.dumps(dict(
        sentences=len(segs), repro_rows=len(old), bounded_rows=len(new),
        lost_by_boundary=len(only_old), lost_occurrences=tot_old,
        shipped_rows=len(shipped), shipped_vs_repro_common=len(set(shipped) & set(old)),
        count_mismatch=len(diff)), ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
