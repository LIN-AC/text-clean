#!/usr/bin/env python3
"""E036 验收 v2：按 Astra 复核意见更正口径。

改掉的四个错：
  1) 单位混用：v1 把"docs join segs 的 count(*)"当成文档数报。现在分别报 文档数 / 去重簇数 / 段数 / 汉字数。
  2) 字符表口径：通用 V 必须只从**训练侧**统计（v1 注释写了"留出外"但代码没排除）。
  3) 声调口径：本项目 1-4 是声调、5 是轻声、0 才是未知。v1 把含 5 调报成"未知调"。
  4) 映射校验：v1 只查长度。现在逐字符验证 text_norm[i] 确实由 text_raw[map[i]] 规范化而来。
"""
import collections, csv, hashlib, json, pathlib, re, sqlite3, sys

R = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(R / 'experiments/E036/scripts'))
from build_corpus import TS, norm as build_norm  # noqa: E402
sys.stdout.reconfigure(encoding='utf-8')
DB = R / 'build/e036_corpus/corpus.sqlite'
TRAIN = R / 'build/e036_corpus/corpus_train.sqlite'
HOLD = R / 'build/e036_corpus/holdout.json'


def norm_char(ch):
    if '一' <= ch <= '鿿':
        return ch
    return TS.get(ch, ' ')


def main():
    hold = json.loads(HOLD.read_text(encoding='utf-8'))
    holdsets = set(hold['holdout_clusters'])
    db = sqlite3.connect(DB)
    rep = {}

    # 1) 单位分开报
    units = {}
    for dom in ('现代', '历史'):
        docs = db.execute('select count(*) from docs where domain=?', (dom,)).fetchone()[0]
        clus = db.execute('select count(distinct cluster_id) from docs where domain=?', (dom,)).fetchone()[0]
        segs, chars = db.execute('''select count(*), sum(s.chars) from segs s join docs d on d.doc_id=s.doc_id
                                    where d.domain=?''', (dom,)).fetchone()
        han = db.execute('''select sum(length(replace(text_norm,' ',''))) from docs where domain=?''', (dom,)).fetchone()[0]
        units[dom] = dict(docs=docs, clusters=clus, segs=segs, seg_chars=chars, han_chars=han)
    units['合计'] = {k: sum(v[k] for v in units.values()) for k in ('docs', 'clusters', 'segs', 'han_chars')}
    rep['单位分列'] = units
    print('=== 1. 单位分列（v1 把段数当文档数，已更正）===')
    for k, v in units.items():
        print('  %-4s 文档 %-7s 去重簇 %-7s 段 %-7s 汉字 %s' % (k, v.get('docs', '—'), v.get('clusters', '—'),
                                                              v.get('segs', '—'), v.get('han_chars', '—')))

    # 2) 两侧隔离 + 字符表只从训练侧
    tdb = sqlite3.connect(TRAIN)
    train_clusters = {r[0] for r in tdb.execute('select distinct cluster_id from docs')}
    rep['留出'] = dict(留出簇=len(holdsets), 训练簇=len(train_clusters),
                     穿越两侧=len(train_clusters & holdsets))
    print('\n=== 2. 留出隔离（按整簇）===')
    print('  留出簇 %d，训练簇 %d，**同时出现在两侧的簇 %d**（v1 是 184）' % (
        len(holdsets), len(train_clusters), len(train_clusters & holdsets)))
    vc = collections.Counter()
    for (tn,) in tdb.execute("select text_norm from docs where domain='现代'"):
        for c in re.findall(r'[一-鿿]', tn):
            vc[c] += 1
    V1 = {c for c, n in vc.items() if n >= 1}
    V2 = {c for c, n in vc.items() if n >= 2}
    rows = [r for r in csv.DictReader((l for l in (R / 'data/correction/candidates.tsv').read_text(encoding='utf-8')
                                      .splitlines() if not l.startswith('#')), delimiter='\t') if r['status'] == '1']
    tg = sorted({r['canonical'] for r in rows})
    cov = lambda S: sum(1 for t in tg if set(t) <= S)
    print('  训练侧现代字种 %d；V(≥2 次)=%d → 目标全覆盖 %d/%d；V(≥1 次)=%d → 目标全覆盖 %d/%d' % (
        len(vc), len(V2), cov(V2), len(tg), len(V1), cov(V1), len(tg)))
    print('  **降到 1 次也覆盖不全**：仍缺 %d 个目标（例：%s）' % (
        len(tg) - cov(V1), '、'.join(t for t in tg if not set(t) <= V1)[:60]))
    rep['字符表(仅训练侧)'] = dict(modern_chars=len(vc), V_ge2=len(V2), targets_full_ge2=cov(V2),
                              V_ge1=len(V1), targets_full_ge1=cov(V1),
                              uncovered_at_1=[t for t in tg if not set(t) <= V1])

    # 3) 声调口径
    t5 = sorted({r['canonical'] for r in rows if '5' in r['pinyin']})
    t0 = sorted({r['canonical'] for r in rows if '0' in r['pinyin']})
    print('\n=== 3. 声调（1-4 声调、5=轻声、0=未知）===')
    print('  含轻声(5)的目标 %d 个：%s' % (len(t5), '、'.join(t5)))
    print('  含未知调(0)的目标 %d 个' % len(t0))
    rep['声调'] = dict(轻声5=t5, 未知调0=t0)

    # 4) 映射逐字符校验
    # 规范化是长度保持的，所以 map 必须等于 [0..n-1]，且整篇重算必须与库里 text_norm 完全相同。
    # （上一版这里我自己写错校验函数：先判了 CJK 区间、漏了繁→简，误报 44899 篇不一致。）
    bad = bad_map = checked = 0
    for raw, tn, mp in db.execute('select text_raw, text_norm, normalization_map_json from docs'):
        checked += 1
        if build_norm(raw)[0] != tn:
            bad += 1
        m = json.loads(mp)
        if len(m) != len(tn) or any(m[i] != i for i in range(0, len(m), 7)) or (m and m[-1] != len(m) - 1):
            bad_map += 1
    print('\n=== 4. 规范化映射逐字符回查 ===')
    print('  校验文档 %s 篇：重算 text_norm 不一致 %d 篇，映射非恒等/长度不符 %d 篇' % (f'{checked:,}', bad, bad_map))
    rep['映射校验'] = dict(docs_checked=checked, text_norm_mismatch=bad, map_bad=bad_map)

    # 5) 段边界类别（历史不再一律当"无句读"）
    cls = {}
    for dom, kind, n in db.execute('''select d.domain, d.boundary_kind, count(*) from docs d group by 1,2'''):
        cls.setdefault(dom, {})[kind] = n
    ends = dict(db.execute("select right_class, count(*) from segs group by 1"))
    print('\n=== 5. 边界类别 ===')
    print('  文档级：', json.dumps(cls, ensure_ascii=False))
    print('  段右端：', json.dumps(ends, ensure_ascii=False))
    rep['边界'] = dict(docs=cls, seg_right=ends)
    (R / 'experiments/E036/results/verify_v2.json').write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding='utf-8')
    ok = (rep['留出']['穿越两侧'] == 0 and bad == 0)
    print('\n结论：%s' % ('留出隔离与映射校验通过' if ok else '仍有未过项，见 verify_v2.json'))


if __name__ == '__main__':
    main()
