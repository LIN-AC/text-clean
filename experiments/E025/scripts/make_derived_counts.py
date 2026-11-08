#!/usr/bin/env python3
"""把 Zipf 词库换算成次数表，用于「只换公式、不换证据」的对照臂。

count = SCALE * 10^zipf，于是 ln((1+fC)/(1+fO)) ≈ ln10 * (zipfC - zipfO) = 2.302585*Δz，
与 Zipf 公式在双侧都有证据时数学相同；SCALE 取 1e6 是为了让公式里的 +1 平滑可忽略
（最小档 zipf≈1 → count≈1e7）。general<=0（wordfreq 的"查无此词"标记）直接不落行，
因为次数口径本来就把缺失当 0。
"""
import pathlib, sys

R = pathlib.Path(__file__).resolve().parents[3]
OUT = R / 'build/e025_data/derived_from_zipf.txt'
OUT.parent.mkdir(parents=True, exist_ok=True)
SCALE = 1e6

rows = [l.split('\t') for l in (R / 'data/frequency/word_freq.tsv').read_text(encoding='utf-8').splitlines() if l]
hdr = next(r for r in rows if r and r[0] == 'word')
gi = hdr.index('general')
kept = dropped = 0
with OUT.open('w', encoding='utf-8', newline='\n') as f:
    f.write('# derived_from: data/frequency/word_freq.tsv (general 列, wordfreq 3.1.1 zipf)\n')
    f.write('# formula: count = 1e6 * 10**zipf ; 见 experiments/E025/scripts/make_derived_counts.py\n')
    for r in rows:
        if not r or r[0].startswith('#') or r[0] == 'word' or len(r) <= gi:
            continue
        try:
            z = float(r[gi])
        except ValueError:
            dropped += 1
            continue
        if z <= 0:
            dropped += 1
            continue
        f.write('%s\t%d\n' % (r[0], int(round(SCALE * 10 ** z))))
        kept += 1
print('写入 %d 行，丢弃 general<=0 %d 行 -> %s' % (kept, dropped, OUT))
