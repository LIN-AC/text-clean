#!/usr/bin/env python3
"""给 E025 的「正确修复消失位置」逐条判因（只用冻结词库与公式，不重跑二进制）。

  R1 目标词在该口径没有词频证据
  R2 原文在该口径没有词频证据 —— 次数口径落 fO=0 拿 ln(1+fC) 大礼，Zipf 口径整窗弃权
  R3 双侧都有证据，但两口径的跨越性不同（次数 fO=0 的额度远大于 K 封顶；或 Δz 不够门槛）
  R4 原文本身是合法词（vocabulary 命中）
  R5 原文首字的全部读音都不在候选表首音节集（首音节锚点门）
R4/R5 两口径同设，列出来是为了说明这些条目即使换公式也照样被挡。
"""
import json, pathlib, re, sys

R = pathlib.Path(__file__).resolve().parents[3]
sys.stdout.reconfigure(encoding='utf-8')
LAM, MU = 0.65, 0.70
LN10 = 2.302585


def lines(path):
    return (l for l in path.read_text(encoding='utf-8').splitlines() if l and not l.startswith('#'))


def load_zipf():
    out = {}
    for l in lines(R / 'data/frequency/word_freq.tsv'):
        p = l.split('\t')
        if len(p) < 2 or p[0] == 'word':
            continue
        try:
            z = float(p[1])
        except ValueError:
            continue
        if z > 0:
            out[p[0]] = z
    return out


def load_counts(path):
    out = {}
    for l in lines(path):
        m = re.match(r'(.+?)[\t ](\d+)\s*$', l)
        if m and m.group(1) != 'word':
            out[m.group(1)] = int(m.group(2))
    return out


def load_vocab():
    v = set()
    for name in ('vocabulary/vocabulary.tsv', 'vocabulary/extvocabulary.tsv'):
        for l in lines(R / 'data' / name):
            w = l.split('\t')[0]
            if w != 'word':
                v.add(w)
    return v


def load_char_readings():
    out = {}
    for l in lines(R / 'data/pronunciation/pronunciation_char.tsv'):
        p = l.split('\t')
        if len(p) < 2 or p[0] == 'char' or p[1] in ('', '-'):
            continue
        out.setdefault(p[0], set()).update(re.sub(r'\d', '', x) for x in re.split(r'[|\s]+', p[1]) if x and x != '-')
    return out


ZIPF = load_zipf()
DERIVED = load_counts(R / 'build/e025_data/derived_from_zipf.txt')
OLD = load_counts(R / 'data/old/word_freq.txt')
VOCAB = load_vocab()
READS = load_char_readings()
FIRST_BASES = set()
for l in lines(R / 'data/correction/candidates.tsv'):
    p = l.split('\t')
    if len(p) > 1 and p[1] not in ('', '-', 'pinyin') and p[-1] == '1':
        syl = re.findall(r'[a-z]+\d?', p[1])
        if syl:
            FIRST_BASES.add(re.sub(r'\d', '', syl[0]))

d = json.loads((R / 'experiments/E025/results/attribute.json').read_text(encoding='utf-8'))


def reasons(x, arm):
    src, dst, dist = x['src'], x['dst'], x['d']
    out = []
    if arm.startswith('Z'):
        if dst not in ZIPF:
            out.append('R1 目标词缺词级证据')
        if src not in ZIPF:
            out.append('R2 原文缺词级证据(Zipf 整窗弃权)')
        if dst in ZIPF and src in ZIPF:
            need = (MU + LAM * dist) / LN10
            gap = ZIPF[dst] - ZIPF[src]
            if gap <= need:
                out.append('R3 双侧有证据但 Δz=%.2f ≤ 门槛 %.2f' % (gap, need))
    else:
        if dst not in OLD:
            out.append('R1 目标词不在旧次数表')
        if src not in OLD:
            out.append('R2 原文不在旧次数表(fO=0 → ln(1+fC) 大礼)')
        elif dst in OLD and OLD[dst] <= OLD[src]:
            out.append('R3 双侧有次数但比值不足')
    if src in VOCAB:
        out.append('R4 原文是合法词')
    if not (READS.get(src[0], set()) & FIRST_BASES):
        out.append('R5 原文首字读音全不在候选首音节集')
    return out or ['R6 其他(窗口/竞争/锁定)']


for arm, lst in d['vanish'].items():
    print('\n=== %s：消失 %d 条' % (arm, len(lst)))
    tally = {}
    for x in sorted(lst, key=lambda t: (t['stem'], t['begin'])):
        rs = reasons(x, arm)
        tally[rs[0]] = tally.get(rs[0], 0) + 1
        print('  %-15s %4d..%4d %s->%s d=%d 旧口径分=%+.2f | %s' % (
            x['stem'][:15], x['begin'], x['end'], x['src'], x['dst'], x['d'], x['score'], ' ; '.join(rs)))
    print('  --- 首要原因分布:', json.dumps(tally, ensure_ascii=False))
print('\n表规模: zipf有证据=%d 派生次数=%d 旧次数=%d 合法词=%d 候选首音节=%d' % (
    len(ZIPF), len(DERIVED), len(OLD), len(VOCAB), len(FIRST_BASES)))
