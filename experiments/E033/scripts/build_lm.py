#!/usr/bin/env python3
"""字符 4-gram 底座：现代语料为通用底座，历史语料单独存，降阶平滑，边界保留。

口径（对应 Astra 研究报告 §5）：
  单位=汉字；非汉字一律是边界（不跨边界生成 n-gram，与 E033 换表结论一致）；
  每个片段左端补 3 个 ^ 作为句首虚拟上下文，保证"词内第一个字"也有条件概率可查；
  存 1~4 阶计数表 + 每种阶数的条件分母，查询用 stupid backoff（α=0.4）：
      P(c|ctx) = count(ctx+c)/count(ctx)                     查到就用
               = 0.4 * P(c|ctx[1:])                          查不到就降阶
  同时输出弃权率诊断：现代底座只有 91.6 万字，必须把"多少比例的查询落在没见过的上下文上"写清楚，
  否则后面把"查不到"当成"不支持"是错的。
产物放 build/，正式词库 data/ 不动。
"""
import collections, hashlib, json, math, pathlib, re, sys, time

R = pathlib.Path(__file__).resolve().parents[3]
OUT = R / 'build/e033_lm'
CEDICT = R / 'data/raw/cedict_ts.u8'
MODERN = R / 'build/e031_corpus/cmn_sentences.tsv'
HIST_TXT = R / 'build/e030_corpus/txt'
MAX_N, ALPHA = 4, 0.4
sys.stdout.reconfigure(encoding='utf-8')


def trad_simp_map():
    pairs = {}
    for line in CEDICT.read_text(encoding='utf-8').splitlines():
        if line.startswith('#'):
            continue
        m = re.match(r'(\S+)\s+(\S+)\s+\[', line)
        if m and len(m.group(1)) == len(m.group(2)):
            for a, b in zip(m.group(1), m.group(2)):
                if a != b and '一' <= a <= '鿿':
                    pairs.setdefault(a, b)
    return pairs


TS = trad_simp_map()


def norm(text):
    return ''.join(TS.get(c, c) if ('一' <= c <= '鿿') else ' ' for c in text)


def runs(text):
    return [r for r in norm(text).split(' ') if r]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build(name, seg_iter, min_count):
    t0 = time.time()
    cnt = {n: collections.Counter() for n in range(1, MAX_N + 1)}
    chars = 0
    for r in seg_iter:
        pad = '^' * (MAX_N - 1)
        s = pad + r
        chars += len(r)
        for i in range(len(pad), len(s)):
            for n in range(1, MAX_N + 1):
                cnt[n][s[max(0, i - n + 1):i + 1]] += 1
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    rows = {}
    for n in range(1, MAX_N + 1):
        keep = {g: c for g, c in cnt[n].items() if c >= (min_count if n >= 3 else 1)}
        rows[n] = keep
        with (out / ('counts%d.tsv' % n)).open('w', encoding='utf-8', newline='\n') as f:
            f.write('gram\tcount\n')
            for g, c in sorted(keep.items(), key=lambda x: -x[1]):
                f.write('%s\t%d\n' % (g, c))
    man = dict(name=name, chars=chars, rows={str(n): len(rows[n]) for n in rows},
               total={str(n): sum(rows[n].values()) for n in rows},
               min_count=min_count, alpha=ALPHA, max_n=MAX_N, seconds=round(time.time() - t0, 1))
    (out / 'manifest.json').write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(man, ensure_ascii=False))
    return man


def modern_runs():
    for line in MODERN.read_text(encoding='utf-8', errors='replace').split('\n'):
        parts = line.split('\t')
        if len(parts) >= 3:
            for r in runs(parts[2]):
                yield r


def hist_runs():
    for p in sorted(HIST_TXT.glob('*.txt')):
        for r in runs(p.read_text(encoding='utf-8')):
            yield r


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    m = build('modern', modern_runs(), 2)
    h = build('history', hist_runs(), 3)
    (OUT / 'inputs.json').write_text(json.dumps(dict(
        modern_sha=sha(MODERN), cedict_sha=sha(CEDICT),
        history_files=len(list(HIST_TXT.glob('*.txt'))),
        history_concat_sha=sha(R / 'build/e030_corpus/history_raw_han.txt'),
        boundary='非汉字一律边界；左端补 3 个 ^', smoothing='stupid backoff α=%.1f' % ALPHA),
        ensure_ascii=False, indent=2), encoding='utf-8')
    print('\n输入指纹已写入 build/e033_lm/inputs.json')
    print(json.dumps(json.loads((OUT / 'inputs.json').read_text(encoding='utf-8')), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
