#!/usr/bin/env python3
"""E031 上下文证据表：现代句库（Tatoeba，CC-BY）与历史语料各自建表。

表内容（放 build/，不进正式词库）：
  words.tsv  词级 Zipf（沿用 E030 口径，供 --domain-freq 使用；本实验多数臂不开）
  ngrams.tsv <串><TAB><次数>，2~6 字串，供跨度 2 的邻接证据使用
  pairs.tsv / unis.tsv  单字锚点（跨度 1）
关键约束：n-gram 表按"出现次数阈值"裁剪，不按候选词裁剪——如果只保留含候选词的串，
原文一侧的计数会被系统性压低，等于变相偏袒目标词（违反"片段不可自证"）。
"""
import collections, json, math, pathlib, re, sys

R = pathlib.Path('.').resolve()
sys.stdout.reconfigure(encoding='utf-8')

CEDICT = R / 'data/raw/cedict_ts.u8'
HIST = R / 'build/e030_corpus/history_raw_han.txt'
MODERN_TSV = R / 'build/e031_corpus/cmn_sentences.tsv'
MIN_COUNT = {'modern': 2, 'classic': 3}
MAX_N = 4   # 跨度 2 只查 2 字锚点与 4 字串，不再往上扩，避免表爆炸


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
print('繁→简映射 %d 对' % len(TS))


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


def modern_segments():
    raw = MODERN_TSV.read_text(encoding='utf-8', errors='replace')
    segs = []
    for line in raw.split('\n'):
        parts = line.split('\t')
        if len(parts) < 3:
            continue
        segs.append(to_simp(parts[2]))
    return segs


def classic_segments():
    text = HIST.read_text(encoding='utf-8')
    # 历史语料已按卷分块，这里按每 400 字切段，段界不参与跨段 n-gram
    chunks = []
    pos = 0
    while pos < len(text):
        window = text[pos:pos + 400]
        chunk = ''.join(ch if '一' <= ch <= '鿿' else ' ' for ch in to_simp(window))
        chunks.append(chunk)
        pos += 400
    return chunks


def build(name, segments, min_count, extra_from=None):
    ngrams = collections.Counter()
    unis = collections.Counter()
    pairs = collections.Counter()
    positions = collections.Counter()
    for seg in segments:
        seq = seg.replace(' ', '\u3000')          # 段内保留，段间已切开
        chars = [c for c in seg if c != ' ']
        for c in chars:
            unis[c] += 1
        for a, b in zip(chars, chars[1:]):
            pairs[(a, b)] += 1
        for n in range(2, MAX_N + 1):
            positions[n] += max(0, len(chars) - n + 1)
            for i in range(len(chars) - n + 1):
                g = chars[i:i + n]
                if len(g) == n:
                    ngrams[''.join(g)] += 1
    kept = {g: c for g, c in ngrams.items() if c >= min_count}
    out = R / ('build/e031_ctx_' + name)
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'ngrams.tsv').open('w', encoding='utf-8', newline='\n') as f:
        f.write('# E031 邻接 n-gram 计数（2~%d 字串，次数>=%d）\n' % (MAX_N, min_count))
        f.write('text\tcount\tlength\n')
        for g, c in sorted(kept.items(), key=lambda x: -x[1]):
            f.write('%s\t%d\t%d\n' % (g, c, len(g)))
    with (out / 'unis.tsv').open('w', encoding='utf-8', newline='\n') as f:
        f.write('char\tcount\n')
        for c, k in unis.most_common():
            f.write('%s\t%d\n' % (c, k))
    with (out / 'pairs.tsv').open('w', encoding='utf-8', newline='\n') as f:
        f.write('left\tright\tcount\n')
        for (a, b), k in pairs.most_common(1500000):
            if k >= 3:
                f.write('%s\t%s\t%d\n' % (a, b, k))
    # words.tsv：词级 zipf（只放 2~6 字串，口径与 E030 一致，便于需要时开 --domain-freq）
    with (out / 'words.tsv').open('w', encoding='utf-8', newline='\n') as f:
        f.write('text\tzipf\tcount\tlength\n')
        for n in range(2, MAX_N + 1):
            rows = [(g, c) for g, c in kept.items() if len(g) == n]
            rows.sort(key=lambda x: -x[1])
            tot = positions[n] or 1
            for g, c in rows[:400000]:
                f.write('%s\t%.3f\t%d\t%d\n' % (g, 9.0 + math.log10(c / tot), c, n))
    stat = dict(segments=len(segments), han=sum(len([c for c in s if c != ' ']) for s in segments),
                ngram_rows=len(kept), min_count=min_count, uni_rows=len(unis), pair_rows=len(pairs),
                by_len={n: sum(1 for g in kept if len(g) == n) for n in range(2, MAX_N + 1)})
    (out / 'manifest.json').write_text(json.dumps(stat, ensure_ascii=False, indent=2), encoding='utf-8')
    print('%s 表: %s' % (name, json.dumps(stat, ensure_ascii=False)))
    return out, kept, unis, pairs


mo, kept_m, _, _ = build('modern', modern_segments(), MIN_COUNT['modern'])
cl, kept_c, _, _ = build('classic', classic_segments(), MIN_COUNT['classic'])

# 合并表（两份语料的计数相加）
merged = collections.Counter(kept_m)
merged.update(kept_c)
out = R / 'build/e031_ctx_both'
out.mkdir(parents=True, exist_ok=True)
for src in ('ngrams.tsv', 'unis.tsv', 'pairs.tsv', 'words.tsv'):
    (out / src).write_bytes((cl / src).read_bytes())
with (out / 'ngrams.tsv').open('w', encoding='utf-8', newline='\n') as f:
    f.write('# E031 合并邻接表（现代句库 + 历史语料，计数相加）\n')
    f.write('text\tcount\tlength\n')
    for g, c in sorted(merged.items(), key=lambda x: -x[1]):
        if c >= 2:
            f.write('%s\t%d\t%d\n' % (g, c, len(g)))
(out / 'manifest.json').write_text(json.dumps(dict(merged_rows=sum(1 for c in merged.values() if c >= 2)),
                                              ensure_ascii=False, indent=2), encoding='utf-8')
print('both 表: 合并行数=%d' % (out / 'ngrams.tsv').open(encoding='utf-8').read().count('\n'))
