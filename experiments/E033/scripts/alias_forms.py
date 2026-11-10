#!/usr/bin/env python3
"""古籍异写/简称自动派生（只用语料能证明的东西，不手写词表）。

桑羊那例的真因：史記集解与漢書里同一个人写成"桑羊"和"桑弘羊"，但**从不在同一卷出现**，
所以按卷（doc）算共现得到 P=0，规则收不下它。改成按"书名（work）"级共现，再加两条约束：
  形态：variant 必须是 target 的保序真子序列，长度 >=2（桑羊 ⊂ 桑弘羊 ✓）；
  稀有：df(variant) <= 2 × df(target)，避免把"司马"这种能独立成词的高频串收进来；
  同书：variant 与 target 至少共享一部书名。
派生结果整表落盘可审计（含每条的判定依据），误收的形如"司迁"由人工复核，不假装规则完美。
"""
import collections, itertools, json, pathlib, sqlite3, sys

R = pathlib.Path(__file__).resolve().parents[3]
DB = R / 'build/e033_kb/kb.sqlite'
OUT = R / 'build/e033_kb/alias_forms.tsv'
sys.stdout.reconfigure(encoding='utf-8')


def subseqs(word):
    out = set()
    for k in range(2, len(word)):
        for combo in itertools.combinations(range(len(word)), k):
            out.add(''.join(word[i] for i in combo))
    return sorted(out)


def main():
    db = sqlite3.connect(DB)
    # 目标词直接取正式候选表的启用行
    cpath = R / 'data/correction/candidates.tsv'
    lines = [l.rstrip('\n').split('\t') for l in cpath.read_text(encoding='utf-8').splitlines()
             if l.strip() and not l.startswith('#')]
    head, body = lines[0], lines[1:]
    ci, si = head.index('canonical'), head.index('status')
    targets = sorted({r[ci] for r in body if r[si] == '1' and len(r[ci]) >= 3}, key=len, reverse=True)

    def doc_stats(word):
        q = '"%s"' % (' '.join(word) if len(word) > 2 else word)
        rows = db.execute('select distinct segs.doc_id, docs.work from kb join segs on segs.seg_id=kb.rowid '
                          'join docs on docs.doc_id=segs.doc_id where kb match ?', (q,)).fetchall()
        return {d for d, _ in rows}, {w for _, w in rows}, len(rows)

    cache = {}
    got = collections.Counter()
    out_rows = []
    for t in targets:
        if t not in cache:
            cache[t] = doc_stats(t)
        dt, wt, _ = cache[t]
        if not dt:
            continue
        for v in subseqs(t):
            if v not in cache:
                cache[v] = doc_stats(v)
            dv, wv, _ = cache[v]
            if not dv or len(dv) > 2 * len(dt):
                continue                       # 子形比目标还常见，多半是独立成词，不能当简称
            shared = wv & wt
            if not shared:
                continue                       # 不同书里出现，没有同书证据
            out_rows.append((t, v, len(dt), len(dv), len(dv & dt), len(shared), '、'.join(sorted(shared))[:60]))
            got['接受'] += 1
    with OUT.open('w', encoding='utf-8', newline='\n') as f:
        f.write('# E033 古籍异写/简称派生表（自动规则，全表可审计）\n')
        f.write('target\tvariant\tdocs_target\tdocs_variant\tdocs_shared\tworks_shared\tworks\n')
        for r in sorted(out_rows, key=lambda x: (-x[5], x[0])):
            f.write('\t'.join(map(str, r)) + '\n')
    print('目标词（≥3 字）%d 个，派生出异写/简称候选 %d 条，涉及目标词 %d 个' % (
        len(targets), len(out_rows), len({r[0] for r in out_rows})))
    print('\n桑弘羊 / 司马迁 / 霍去病 三个样本的全部派生结果（含依据，便于人工复核）：')
    for r in out_rows:
        if r[0] in ('桑弘羊', '司马迁', '霍去病', '桑弘羊'):
            print('   %-6s ← %-5s 目标文档 %2d ｜子形文档 %3d ｜同卷共现 %2d ｜同书 %d 部：%s' % (
                r[0], r[1], r[2], r[3], r[4], r[5], r[6]))
    print('\n按同书数排序的前 12 条（最强证据）：')
    for r in sorted(out_rows, key=lambda x: (-x[5], -x[4]))[:12]:
        print('   %-6s ← %-5s 同书 %d 部 同卷共现 %d ｜子形文档 %d' % (r[0], r[1], r[5], r[4], r[3]))
    (R / 'experiments/E033/results/alias_stats.json').write_text(json.dumps(
        dict(targets_ge3=len(targets), variants=len(out_rows), targets_with_variant=len({r[0] for r in out_rows})),
        ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
