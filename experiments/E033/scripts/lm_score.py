#!/usr/bin/env python3
"""字符 4-gram 打分开封：同一段真实上下文里，正确词形与错误词形谁概率更高。

打分范围只累计"替换会影响的项"：目标词每个字的转移 + 词右侧最多 3 字的转移，
句内其他项两边相同、自动抵消。查不到就降阶（stupid backoff α=0.4），整条都查不到记为弃权。

必须说清这条测法是什么：上下文取自**人工真值**（干净文本），所以它测的是"这张表有没有区分词形的能力"，
不是生产环境表现，也不含 ASR 错字干扰；接进判决前要另做含噪实验。
"""
import json, math, pathlib, sys

R = pathlib.Path(__file__).resolve().parents[3]
sys.stdout.reconfigure(encoding='utf-8')
ALPHA = 0.4


class LM:
    def __init__(self, name):
        d = R / 'build/e033_lm' / name
        self.c = {}
        for n in (4, 3, 2, 1):
            t = {}
            for line in (d / ('counts%d.tsv' % n)).read_text(encoding='utf-8').splitlines():
                if not line or line.startswith('gram'):
                    continue
                g, _, c = line.partition('\t')
                t[g] = int(c)
            self.c[n] = t
        self.tot = {n: sum(t.values()) for n, t in self.c.items()}
        self.uni_total = max(sum(self.c[1].values()), 1)
        self.hit = self.miss = 0

    def logp(self, gram):
        """P(最后一字 | 前 3 字)，逐级降阶。"""
        for n in range(len(gram), 1, -1):
            g = gram[-n:]
            num = self.c[n].get(g)
            if num:
                den = self.c[n - 1].get(g[:-1])
                if den:
                    self.hit += 1
                    return __import__('math').log(num / den)
            if n == 2:
                break
        base = self.c[1].get(gram[-1]) or 0
        if not base:
            self.miss += 1
        return math.log(max(base, 0.1) / self.uni_total)

    def score(self, left, word, right):
        s, used = 0.0, 0
        ctx = ('^^^' + left)[-3:]
        for ch in word:
            s += self.logp(ctx + ch); ctx = (ctx + ch)[-3:]; used += 1
        for ch in right[:3]:
            s += self.logp(ctx + ch); ctx = (ctx + ch)[-3:]; used += 1
        return s, used


def contexts_of(word, limit=3, only=None):
    """从人工真值里取该词的真实上下文。only='hist'/'mod' 用来按片子拆开统计。"""
    out = []
    for f in sorted((R / 'asr').glob('*.gt.jsonl')):
        if only == 'hist' and f.stem[:-3] != 'BV1uUak6pEdK':
            continue
        if only == 'mod' and f.stem[:-3] == 'BV1uUak6pEdK':
            continue
        rows = [r for r in (json.loads(l) for l in f.read_text(encoding='utf-8').splitlines() if l.strip())
                if not r.get('discard')]
        t = ''.join(''.join(r['gt'].split()) for r in rows)
        i = t.find(word)
        while i >= 0 and len(out) < limit:
            if i >= 3 and i + len(word) + 3 <= len(t):
                out.append((f.stem[:-3], t[i - 3:i], t[i + len(word):i + len(word) + 3]))
            i = t.find(word, i + 1)
    return out


def main():
    lines = [l.rstrip('\n').split('\t') for l in (R / 'data/correction/candidates.tsv').read_text(encoding='utf-8')
             .splitlines() if l.strip() and not l.startswith('#')]
    head, body = lines[0], lines[1:]
    ci, ai, si = head.index('canonical'), head.index('alias'), head.index('status')
    pairs = {(r[ci], r[ai]) for r in body if r[si] == '1' and len(r[ci]) == len(r[ai]) and r[ci] != r[ai]}
    lms = {n: LM(n) for n in ('modern', 'history')}
    stat = {n: dict(可测=0, 目标胜=0, 别名胜=0, 平=0, 无上下文=0) for n in lms}
    grp = {(n, g): dict(可测=0, 目标胜=0, 别名胜=0) for n in lms for g in ('hist', 'mod')}
    detail = []
    for target, alias in sorted(pairs, key=lambda x: -len(x[0])):
        cs = contexts_of(target, 3)
        if not cs:
            continue
        for only in ('hist', 'mod'):
            cs2 = [c for c in contexts_of(target, 3, only)]
            if not cs2:
                continue
            for name, lm in lms.items():
                for stem, left, right in cs2:
                    a, _ = lm.score(left, target, right); b, _ = lm.score(left, alias, right)
                    k = (name, only); grp[k]['可测'] += 1
                    grp[k]['目标胜' if a > b else '别名胜'] += 1 if abs(a - b) > 1e-9 else 0
                    grp[k]['别名胜'] += 0
        for name, lm in lms.items():
            win = lose = tie = 0
            for stem, left, right in cs:
                a, _ = lm.score(left, target, right)
                b, _ = lm.score(left, alias, right)
                if abs(a - b) < 1e-9:
                    tie += 1
                elif a > b:
                    win += 1
                else:
                    lose += 1
            stat[name]['可测'] += len(cs); stat[name]['目标胜'] += win
            stat[name]['别名胜'] += lose; stat[name]['平'] += tie
            if name == 'history':
                detail.append(dict(target=target, alias=alias, ctxs=len(cs), 历史库目标胜=win, 历史库别名胜=lose, 平=tie))
    print('\n=== 按领域拆开（历史专项片 vs 其余六片，同一批词对）===')
    for name in ('modern', 'history'):
        for only, lab in (('hist', '历史片'), ('mod', '现代片')):
            g = grp[(name, only)]
            n = max(1, g['可测'])
            print('  %-8s %s：可测 %4d ｜目标词形胜 %.1f%%｜别名胜 %.1f%%' % (
                name, lab, g['可测'], 100.0 * g['目标胜'] / n, 100.0 * g['别名胜'] / n))
    print('=== 4-gram 底座对词形的区分力（上下文取自人工真值，成对比较目标词 vs 表内错误别名）===')
    for name in ('modern', 'history'):
        s = stat[name]
        n = max(1, s['可测'])
        print('  %-8s 可测 %5d 次：目标词形胜 %5d（%.1f%%）｜别名胜 %5d（%.1f%%）｜平 %d' % (
            name, s['可测'], s['目标胜'], 100.0 * s['目标胜'] / n, s['别名胜'], 100.0 * s['别名胜'] / n, s['平']))
        print('           转移查表命中 %d / 落空 %d → 弃权率 %.1f%%' % (
            lms[name].hit, lms[name].miss, 100.0 * lms[name].miss / max(1, lms[name].hit + lms[name].miss)))
    print('\n=== 重点词对（历史库逐对）===')
    for d in detail:
        if d['target'] in ('卫青', '桑弘羊', '田赋', '县官', '豪强', '贞观', '赈济', '赋役', '轻徭薄赋'):
            print('  %-6s ← %-6s 上下文 %d 次：目标胜 %d／别名胜 %d／平 %d' % (
                d['target'], d['alias'], d['ctxs'], d['历史库目标胜'], d['历史库别名胜'], d['平']))
    (R / 'experiments/E033/results/lm_pairs.json').write_text(
        json.dumps(dict(stat=stat, detail=detail), ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
