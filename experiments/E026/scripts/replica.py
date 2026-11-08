#!/usr/bin/env python3
"""E026 复算器：用冻结词库复刻 C++ 的候选读音、拼音距离、近音门、证据与分数。

先验证再使用：对二进制实际打印出来的每一处编辑，比较复刻的 distance / logR / score；
只有与真值口径一致才允许用于"未发生"的实例判因。Zipf 两臂（Z1/Z2）要求逐条一致；
旧次数臂 C2 的字频基线口径不同，只作方向参考，不用于判因。
"""
import collections, json, math, pathlib, re, sys

R = pathlib.Path(__file__).resolve().parents[3]
O = R / 'experiments/E026/results'
LN10, LAM, MU, MAXD, K_CAP = 2.302585, 0.65, 0.70, 2, 0.6
sys.stdout.reconfigure(encoding='utf-8')


def lines(path):
    return (l for l in path.read_text(encoding='utf-8').splitlines() if l and not l.startswith('#'))


def split_syllables(pinyin):
    return re.findall(r'[a-zA-Z]+[0-5]?', pinyin)


def base_of(syl):
    return re.sub(r'[0-5]', '', syl).lower()


def tone_of(syl):
    m = re.search(r'([0-5])', syl)
    return m.group(1) if m else '5'


CHAR_READS = collections.defaultdict(set)          # char -> {toned syllable}
for l in lines(R / 'data/pronunciation/pronunciation_char.tsv'):
    f = l.split('\t')
    if len(f) < 2 or f[0] == 'char' or f[1] in ('', '-'):
        continue
    for s in re.split(r'[|\s]+', f[1]):
        if s and s != '-':
            CHAR_READS[f[0]].add(s.lower())

WORD_READS = {}                                     # canonical -> declared toned syllables
ALIAS_OF = collections.defaultdict(set)
TARGETS = set()
for l in lines(R / 'data/correction/candidates.tsv'):
    f = l.rstrip('\n').split('\t')
    if len(f) < 5 or f[0] == 'canonical' or f[4] != '1':
        continue
    TARGETS.add(f[0])
    if f[1] not in ('', '-'):
        WORD_READS.setdefault(f[0], split_syllables(f[1]))
    for a in [x for x in f[2].split('|') if x]:
        ALIAS_OF[a].add(f[0])

ZIPF, CHAR_ZIPF = {}, {}
for l in lines(R / 'data/frequency/word_freq.tsv'):
    f = l.split('\t')
    if len(f) > 1 and f[0] != 'word':
        try:
            v = float(f[1])
        except ValueError:
            continue
        if v > 0:
            ZIPF[f[0]] = v
for l in lines(R / 'data/frequency/char_freq.tsv'):
    f = l.split('\t')
    if len(f) > 1 and f[0] != 'char':
        try:
            v = float(f[1])
        except ValueError:
            continue
        if v > 0:
            CHAR_ZIPF[f[0]] = v

OLD_COUNTS = {}
for l in lines(R / 'data/old/word_freq.txt'):
    m = re.match(r'(.+?)[\t ](\d+)\s*$', l)
    if m and m.group(1) != 'word':
        OLD_COUNTS[m.group(1)] = int(m.group(2))


def levenshtein_bounded(a, b, cap=1):
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def candidate_variants(target):
    """候选侧：只保留声明词级拼音的基音，声调取该字表里同基音的全部读音（同 C++ 约束）。"""
    declared = WORD_READS.get(target)
    if declared is None or len(declared) != len(target):
        declared = None
    out = []
    for k, ch in enumerate(target):
        reads = CHAR_READS.get(ch, set())
        if declared:
            b = base_of(declared[k])
            keep = {s for s in reads if base_of(s) == b} or {declared[k]}
        else:
            keep = reads
        out.append(keep)
    return out


def input_readings(original):
    return [CHAR_READS.get(ch, set()) for ch in original]


def aligned_distance(original, target):
    """逐音节：同基音同调 0 / 同基音不同调 1 / 不同基音 2；取两侧全部读音的最小值。"""
    if len(original) != len(target):
        return None
    inp, cand = input_readings(original), candidate_variants(target)
    total = 0
    for a, b in zip(inp, cand):
        best = 3
        for x in a:
            for y in b:
                best = min(best, 0 if x == y else (1 if base_of(x) == base_of(y) else 2))
        if not a or not b:
            return None
        total += best
    return total


def near_ok(original, target):
    """每个位置都必须存在基音编辑距离≤1 的读音对（硬限制）。"""
    inp, cand = input_readings(original), candidate_variants(target)
    if len(inp) != len(cand):
        return False
    for a, b in zip(inp, cand):
        if not any(levenshtein_bounded(base_of(x), base_of(y), 1) <= 1 for x in a for y in b):
            return False
    return True


def char_estimate(text):
    if any(ch not in CHAR_ZIPF for ch in text):
        return None
    return sum(CHAR_ZIPF[ch] for ch in text) - 9.0 * (len(text) - 1)


def score(original, target, arm):
    """返回 (distance, 是否通过硬门, 是否进入评分, 分数, 拒绝原因)。"""
    d = aligned_distance(original, target)
    if d is None:
        return None, '长度不等', None, None, None
    if d > MAXD:
        return d, '拼音距离>2', None, None, None
    if d > 0 and len(original) < 2:
        return d, '短于模糊下限', None, None, None
    if not near_ok(original, target):
        return d, '近音门(基音编辑距离>1)', None, None, None
    if arm == 'C2':
        fc, fo = OLD_COUNTS.get(target), OLD_COUNTS.get(original, 0)
        if fc is None:
            return d, '未进入评分', None, None, '目标词不在旧次数表'
        s = math.log((1.0 + fc) / (1.0 + fo)) - LAM * d - MU
        return d, '进入评分', (original in OLD_COUNTS), s, None
    zc = ZIPF.get(target)
    if zc is None:
        return d, '未进入评分', None, None, '目标词缺词级证据(弃权)'
    zo = ZIPF.get(original)
    missing = zo is None
    if missing:
        if arm == 'Z1':
            return d, '未进入评分', True, None, '原文缺词级证据(整窗弃权)'
        est = char_estimate(original)
        if est is None:
            return d, '未进入评分', True, None, '原文字频证据不完整'
        zo = max(est, zc - K_CAP)
    s = LN10 * (zc - zo) - LAM * d - MU
    return d, '进入评分', missing, s, None


if __name__ == '__main__':
    # ---- 校准：拿二进制真打印的编辑逐条比对 ----
    applied = json.loads((O / 'applied.json').read_text(encoding='utf-8'))
    tally = collections.Counter()
    bad = []
    for arm in ('Z1', 'Z2'):
        for stem, v in applied[arm].items():
            for x in v['applied']:
                if x['kind'] != 'pinyin':
                    tally[(arm, 'AC/非拼音，跳过')] += 1
                    continue
                res = score(x['src'], x['dst'], arm)
                d, stage, missing, s, why = res
                tally[(arm, '距离一致' if d == x['d'] else '距离不一致')] += 1
                if s is not None and abs(s - x['score']) < 1e-3:
                    tally[(arm, '分数一致')] += 1
                else:
                    tally[(arm, '分数不一致/未评分')] += 1
                    bad.append((arm, stem, x['src'], x['dst'], x['d'], x['score'], d, s, stage, why))
        print(arm, dict((k[1], v) for k, v in tally.items() if k[0] == arm))
    print('\n不一致样本 %d 条（前 12）:' % len(bad))
    for b in bad[:12]:
        print('  ', b)
