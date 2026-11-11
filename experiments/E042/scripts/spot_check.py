#!/usr/bin/env python3
"""E042 人工复核取样：把每个目标词的实际上下文打出来，供判真用率。

为什么不自动判：中文没有词边界，"政务服务"里 政务/事务 是合法重叠，
而"慢易以犯节流湎以忘本"里的 节流 恰好是两个词的接缝——自动分词两头都判不准。
所以这里只做两件事：① 用本项目词表给一个启发式对齐标记；② 每个词最多取 N 条真实上下文，
交给人工判。启发式标记不是结论，README 里按人工判定写数。
"""
import argparse, collections, csv, json, pathlib, sqlite3, sys

R = pathlib.Path(__file__).resolve().parents[3]
sys.stdout.reconfigure(encoding='utf-8')
WORDS = R / 'data/frequency/word_freq.tsv'


def lexicon(max_len=6):
    out = set()
    with WORDS.open(encoding='utf-8') as f:
        for row in csv.DictReader((l for l in f if not l.startswith('#')), delimiter='\t'):
            w = row['word']
            if 2 <= len(w) <= max_len and all('一' <= c <= '鿿' for c in w):
                out.add(w)
    return out


def aligned(lex, text, i, j):
    """启发式：目标串左右各扩 1–2 字若能组成词表里的词，标 suspect（可能跨词接缝）。"""
    for k in (1, 2):
        if i - k >= 0 and text[i - k:i - k + k + 1] in lex:
            return False
        if text[j - 1:j - 1 + k + 1] in lex and len(text[j - 1:j - 1 + k + 1]) == k + 1:
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--per-word', type=int, default=12)
    ap.add_argument('--out', default=str(R / 'build/e042_corpus/coverage_samples_for_review.tsv'))
    a = ap.parse_args()
    lex = lexicon()
    print('词表 %d 词' % len(lex), flush=True)
    targets = [r['target'] for r in csv.DictReader((l for l in (R / 'docs/RAG_CORPUS_TARGETS.tsv')
                                                   .read_text(encoding='utf-8').splitlines()
                                                   if not l.startswith('#')), delimiter='\t')]
    taken = collections.Counter()
    rows = ['target\tdomain\tsource_family\taligned_heuristic\tcontext\turl']
    for p in [R / 'build/e036_corpus/corpus.sqlite', R / 'build/e042_corpus/corpus_supplement.sqlite']:
        db = sqlite3.connect(p.resolve().as_uri() + '?mode=ro', uri=True)
        for t in targets:
            if taken[t] >= a.per_word:
                continue
            for dom, fam, tn, url in db.execute(
                    'select domain, source_family, text_norm, url from docs where text_norm like ? limit 400',
                    ('%' + t + '%',)):
                i = tn.find(t)
                if i < 0:
                    continue
                ctx = tn[max(0, i - 16):i + len(t) + 16].replace(' ', '')
                ok = aligned(lex, tn, i, i + len(t))
                rows.append('%s\t%s\t%s\t%s\t%s\t%s' % (t, dom, fam, 'OK' if ok else 'SUSPECT', ctx, url))
                taken[t] += 1
                if taken[t] >= a.per_word:
                    break
        db.close()
    pathlib.Path(a.out).write_text('\n'.join(rows) + '\n', encoding='utf-8', newline='\n')
    print('取样 %d 条 → %s' % (len(rows) - 1, a.out), flush=True)
    stat = collections.defaultdict(lambda: collections.Counter())
    for l in rows[1:]:
        c = l.split('\t')
        stat[c[0]][c[3]] += 1
    for t in targets:
        if stat[t]:
            print('  %-10s OK %2d / SUSPECT %2d' % (t, stat[t]['OK'], stat[t]['SUSPECT']))


if __name__ == '__main__':
    main()
