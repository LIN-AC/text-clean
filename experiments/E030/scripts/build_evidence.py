#!/usr/bin/env python3
"""E030 领域证据表生成：历史语料 → zipf 词表 + 相邻字共现表。

只在实验目录里产出，不覆盖正式词库。词频尺度沿用 wordfreq 口径：
    zipf = 9 + log10(该串出现概率)，概率按该长度的位置数计。
繁→简映射取自本项目已有的 CC-CEDICT（CC BY-SA 4.0），逐字映射；
一个繁体字对应多个简体字时合并计数（保守，会略高估），映射不到的字保留原样，
覆盖率在日志里报出。
"""
import collections, hashlib, json, math, pathlib, re, sys

R = pathlib.Path(__file__).resolve().parents[3]
SRC = R / 'build/e030_corpus'
OUT = R / 'build/e030_evidence'
OUT.mkdir(parents=True, exist_ok=True)
sys.stdout.reconfigure(encoding='utf-8')

MIN_COUNT = {1: 1, 2: 4, 3: 3, 4: 3, 5: 2, 6: 2}
MAX_ROWS = {1: 0, 2: 600000, 3: 600000, 4: 500000, 5: 300000, 6: 200000}   # 0=不截断

# ---------- 繁→简逐字映射 ----------
t2s = {}
cedict = R / 'data/raw/cedict_ts.u8'
for line in cedict.read_text(encoding='utf-8').splitlines():
    if line.startswith('#'):
        continue
    m = re.match(r'(\S+)\s+(\S+)\s+\[(.*?)\]', line)
    if not m:
        continue
    trad, simp = m.group(1), m.group(2)
    if len(trad) != len(simp) or not trad:
        continue
    for a, b in zip(trad, simp):
        if a != b and '一' <= a <= '鿿':
            t2s.setdefault(a, collections.Counter())[b] += 1
mapping = {a: c.most_common(1)[0][0] for a, c in t2s.items()}
print('CEDICT 逐字繁简映射: %d 对' % len(mapping))

# ---------- 读语料并转简 ----------
files = sorted((SRC / 'txt').glob('*.txt'))
assert files, '还没有语料，先跑 fetch_corpus.py'
corpus = []
hit = miss = 0
for f in files:
    text = f.read_text(encoding='utf-8')
    conv = []
    for ch in text:
        if ch in mapping:
            conv.append(mapping[ch]); hit += 1
        elif '㐀' <= ch <= '䶿' or '一' <= ch <= '鿿':
            conv.append(ch); miss += 1
        else:
            conv.append(' ')      # 非汉字切分边界
    corpus.append(''.join(conv))
total_han = sum(len(re.findall('[一-鿿]', c)) for c in corpus)
print('语料文件=%d 汉字=%d 繁→简命中=%d 未映射=%d (%.2f%%)' % (
    len(files), total_han, hit, miss, 100.0 * miss / max(1, hit + miss)))

# ---------- n-gram 计数 ----------
counts = {n: collections.Counter() for n in MIN_COUNT}
positions = {n: 0 for n in MIN_COUNT}
for c in corpus:
    for n in MIN_COUNT:
        for i in range(len(c) - n + 1):
            g = c[i:i + n]
            if len(g) != n or ' ' in g:
                continue
            counts[n][g] += 1
            positions[n] += 1
print('位置数:', {n: positions[n] for n in sorted(positions)})

# ---------- 写表 ----------
rows_total = 0
with (OUT / 'words.tsv').open('w', encoding='utf-8', newline='\n') as f:
    f.write('# E030 实验用历史领域词频（来源=维基文库二十四史类公开文本，繁已转简）\n')
    f.write('# 尺度与 wordfreq 一致：zipf = 9 + log10(count/positions)\n')
    f.write('text\tzipf\tcount\tlength\n')
    for n in sorted(counts):
        items = [(g, c) for g, c in counts[n].items() if c >= MIN_COUNT[n]]
        items.sort(key=lambda x: -x[1])
        if MAX_ROWS[n]:
            items = items[:MAX_ROWS[n]]
        for g, c in items:
            f.write('%s\t%.3f\t%d\t%d\n' % (g, 9.0 + math.log10(c / positions[n]), c, n))
        rows_total += len(items)
        print('  %d 字串: 落表 %d 行' % (n, len(items)))
pairs = collections.Counter()
unis = collections.Counter()
for c in corpus:
    seq = [ch for ch in c if ch != ' ']
    for ch in seq:
        unis[ch] += 1
    for a, b in zip(seq, seq[1:]):
        pairs[(a, b)] += 1
with (OUT / 'unis.tsv').open('w', encoding='utf-8', newline='\n') as f:
    f.write('char\tcount\n')
    for ch, c in unis.most_common():
        f.write('%s\t%d\n' % (ch, c))
with (OUT / 'pairs.tsv').open('w', encoding='utf-8', newline='\n') as f:
    f.write('left\tright\tcount\n')
    for (a, b), c in pairs.most_common(1500000):
        if c >= 3:
            f.write('%s\t%s\t%d\n' % (a, b, c))

raw = (OUT / 'words.tsv').read_bytes()
manifest = dict(corpus_files=len(files), han=total_han, trad_map_size=len(mapping),
                words_rows=rows_total, pair_rows=len(pairs), uni_rows=len(unis),
                corpus_sha256=hashlib.sha256((SRC / 'history_raw_han.txt').read_bytes()).hexdigest()[:16]
                if (SRC / 'history_raw_han.txt').exists() else '未完成合并',
                words_sha256=hashlib.sha256(raw).hexdigest()[:16], min_count=MIN_COUNT, max_rows=MAX_ROWS)
(OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(manifest, ensure_ascii=False, indent=2))

# ---------- 专项词自检 ----------
probe = ['卫青', '魏清', '桑弘羊', '桑红阳', '田赋', '填富', '县官', '现关', '轻徭薄赋', '清姚伯父',
         '卖官鬻爵', '卖关于绝', '微信', '威信', '转账', '转帐', '洪武型', '红五星']
print('\n=== 专项词在历史语料里的档位（zipf；查不到=未出现）===')
lookup = {}
for line in (OUT / 'words.tsv').read_text(encoding='utf-8').splitlines():
    if line.startswith('#') or not line:
        continue
    p = line.split('\t')
    if p[0] != 'text':
        lookup[p[0]] = (float(p[1]), int(p[2]))
for w in probe:
    z, c = lookup.get(w, (None, 0))
    print('  %-6s zipf=%-7s 次数=%-6d' % (w, ('%.2f' % z) if z else '查无', c))
