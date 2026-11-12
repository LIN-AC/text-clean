#!/usr/bin/env python3
"""留出必须按"文档簇"整体划分，并物化一份剔除留出的训练原料库。

上一版我用 doc_id 随机抽样，Astra 复核发现 184 个簇同时落在训练与留出两侧——
同一份内容（完全重复或近重复转载）被合成一个簇之后，只要抽样按文档走，就必然穿越两侧。
这里改成：先按 cluster_id 整簇分配，再物化 corpus_train.sqlite（只含训练簇），
让下游构建器不加改动也能建出真正的"训练包"，与"全量实验包"分开。

划分规则（固定种子，可复现）：
  历史：按 source_family（书）整族分配，贪心取到约 15% 字数进留出，同族绝不跨侧；
  现代：只有一个来源组，按 cluster_id 排序后用固定随机数取约 10% 字数，同样整簇划分。
"""
import hashlib, json, pathlib, random, sqlite3, sys

R = pathlib.Path(__file__).resolve().parents[3]
SRC = R / 'build/e036_corpus/corpus.sqlite'
TRAIN = R / 'build/e036_corpus/corpus_train.sqlite'
OUT = R / 'build/e036_corpus/holdout.json'
SEED = 20261111
sys.stdout.reconfigure(encoding='utf-8')


def main():
    db = sqlite3.connect(SRC)
    # 簇的体量与来源组
    # 一次 SQL 拿齐"簇 → 域/来源组/代表正文字数"，避免逐簇查询（上一版 8.9 万次查询慢到跑不完）
    cl = {cid: dict(domain=dom, family=fam, chars=n) for cid, dom, fam, n in db.execute(
        '''select cluster_id, domain, source_family, max(length(text_norm))
           from docs group by cluster_id''')}
    print('簇数 %d，开始划分' % len(cl), flush=True)
    out = {'seed': SEED, 'unit': 'cluster_id（整簇划分，同簇不跨两侧）'}
    hold = set()
    hist = [c for c, v in cl.items() if v['domain'] == '历史']
    fams = {}
    for c in hist:
        fams.setdefault(cl[c]['family'], []).append(c)
    tot_h = sum(cl[c]['chars'] for c in hist) or 1
    got = 0
    for f in sorted(fams, key=lambda x: sum(cl[c]['chars'] for c in fams[x])):   # 小部书优先
        if got / tot_h >= 0.15:
            break
        hold.update(fams[f]); got = sum(cl[c]['chars'] for c in hold if cl[c]['domain'] == '历史')
    out['history_holdout_families'] = sorted({cl[c]['family'] for c in hold})
    mod = [c for c, v in cl.items() if v['domain'] == '现代']
    rng = random.Random(SEED)
    need, acc = 0.10 * sum(cl[c]['chars'] for c in mod), 0
    for c in rng.sample(sorted(mod), len(mod)):
        if acc >= need:
            break
        hold.add(c); acc += cl[c]['chars']
    out['holdout_clusters'] = sorted(hold)
    out['counts'] = dict(clusters=len(cl), holdout=len(hold), train=len(cl) - len(hold),
                         holdout_chars=sum(cl[c]['chars'] for c in hold),
                         total_chars=sum(v['chars'] for v in cl.values()))
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')

    # 物化训练原料库（结构与正式库完全一致，只少留出簇）
    if TRAIN.exists():
        TRAIN.unlink()
    tdb = sqlite3.connect(TRAIN)
    tdb.executescript(''.join(r[0] + ';\n' for r in db.execute(
        "select sql from sqlite_master where sql is not null and type in ('table','index')")))
    cols_d = [r[1] for r in db.execute('pragma table_info(docs)')]
    cols_s = [r[1] for r in db.execute('pragma table_info(segs)')]
    ph_d = ','.join('?' * len(cols_d))
    pairs = list(db.execute('select doc_id, cluster_id from docs'))
    doc_ids = [d for d, c in pairs if c not in hold]
    kept_clusters = {c for d, c in pairs if d in set(doc_ids)}
    q = ','.join(str(x) for x in doc_ids)
    tdb.executemany('insert into docs values(%s)' % ph_d,
                    [r for r in db.execute('select * from docs where doc_id in (%s)' % q)])
    tdb.executemany('insert into segs values(%s)' % ','.join('?' * len(cols_s)),
                    [r for r in db.execute('select * from segs where doc_id in (%s)' % q)])
    for k, v in db.execute('select k, v from meta'):
        tdb.execute('insert or replace into meta values(?,?)', (k, v + '（已剔除留出簇，构建于 %s）' % __import__('time').strftime('%F %T')))
    tdb.commit()
    keep = set(doc_ids)
    cross = sorted(set(hold) & kept_clusters)     # 整簇划分，两侧不可能有同簇
    print('留出簇 %d 个（字数 %.0f 万 / 总 %.0f 万）；训练库 docs %d，segs %d' % (
        len(hold), out['counts']['holdout_chars'] / 1e4, out['counts']['total_chars'] / 1e4,
        len(keep), tdb.execute('select count(*) from segs').fetchone()[0]))
    print('穿越两侧的簇（必须为 0）：%d' % len(cross))
    print('训练库 SHA %s' % hashlib.sha256(TRAIN.read_bytes()).hexdigest()[:16])


if __name__ == '__main__':
    main()
