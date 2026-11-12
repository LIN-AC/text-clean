#!/usr/bin/env python3
"""E044：把 E036 训练侧原料与 E042 补充库并成一个源库，供 prepare_rag_package 建包。

只读两个源库，不改它们；重新编号 doc_id/seg_id，保留 cluster_id/source_family/domain/register/
边界列与偏移。合并后必须再验一遍"类别与 is_stop 一致"，因为建包脚本对此是直接抛错的。
"""
import json, pathlib, sqlite3, sys, time

R = pathlib.Path(__file__).resolve().parents[3]
sys.stdout.reconfigure(encoding='utf-8')
SRC = [R / 'build/e036_corpus/corpus_train.sqlite', R / 'build/e042_corpus/corpus_supplement.sqlite']
OUT = R / 'build/e044_corpus/corpus_merged_train.sqlite'
OUT.parent.mkdir(parents=True, exist_ok=True)
if OUT.exists():
    OUT.unlink()

COLS = ['domain', 'work', 'title', 'url', 'license', 'fetched_at', 'src_sha', 'cluster_id', 'cluster_size',
        'source_family', 'text_raw', 'text_norm', 'normalization_map_json', 'normalization_version',
        'boundary_kind', 'chars', 'runs']
d = sqlite3.connect(OUT)
d.executescript('''
create table docs(doc_id integer primary key, domain text not null, work text, title text, url text not null,
  license text not null, fetched_at text, src_sha text not null, cluster_id text not null,
  cluster_size integer not null default 1, source_family text not null, text_raw text not null,
  text_norm text not null, normalization_map_json text not null, normalization_version text not null,
  boundary_kind text not null, chars integer not null, runs integer not null,
  register text, period text, source_batch text, rev_timestamp text);
create table segs(seg_id integer primary key, doc_id integer not null references docs, ord integer not null,
  off integer not null, text_norm text not null, chars integer not null, boundary_kind text not null,
  left_edge text, right_edge text, left_class text, right_class text,
  left_is_stop integer not null default 0, right_is_stop integer not null default 0);
create index segs_doc on segs(doc_id, ord);
create table meta(k text primary key, v text);
''')
doc_id = seg_id = 0
per_source = {}
for p in SRC:
    s = sqlite3.connect(p.resolve().as_uri() + '?mode=ro', uri=True)
    cols = {r[1] for r in s.execute('pragma table_info(docs)')}
    have = [c for c in COLS if c in cols]
    extra = [c for c in ('register', 'period', 'source_batch', 'rev_timestamp') if c in cols]
    n = 0
    t0 = time.time()
    for row in s.execute('select %s, doc_id from docs order by doc_id' % ','.join(have + extra)):
        rec = dict(zip(have + extra + ['_src_doc'], row))
        doc_id += 1
        n += 1
        d.execute('insert into docs values(%s)' % ','.join(['?'] * 22), (
            doc_id, rec['domain'], rec['work'], rec['title'], rec['url'], rec['license'], rec['fetched_at'],
            rec['src_sha'], rec['cluster_id'], rec['cluster_size'], rec['source_family'], rec['text_raw'],
            rec['text_norm'], rec['normalization_map_json'], rec['normalization_version'], rec['boundary_kind'],
            rec['chars'], rec['runs'], rec.get('register'), rec.get('period'),
            rec.get('source_batch') or p.name, rec.get('rev_timestamp')))
        for sg in s.execute('select ord, off, text_norm, chars, boundary_kind, left_edge, right_edge, '
                            'left_class, right_class, left_is_stop, right_is_stop from segs where doc_id=? order by ord',
                            (rec['_src_doc'],)):
            seg_id += 1
            d.execute('insert into segs values(?,?,?,?,?,?,?,?,?,?,?,?,?)', (seg_id, doc_id) + sg)
    per_source[p.name] = n
    print('%s 并入 %d 篇，累计 doc %d / seg %d，%.0fs' % (p.name, n, doc_id, seg_id, time.time() - t0), flush=True)
    s.close()

bad = d.execute("select count(*) from segs where (left_is_stop=1)!=(left_class='句末标点') "
                "or (right_is_stop=1)!=(right_class='句末标点')").fetchone()[0]
dom = dict(d.execute("select domain, sum(length(replace(text_norm,' ',''))) from docs group by 1"))
fam = dict(d.execute('select source_family, count(*) from docs group by 1 order by 2 desc limit 30'))
d.execute("insert into meta values('merged_from',?)", (json.dumps(per_source, ensure_ascii=False),))
d.execute("insert into meta values('merged_at',?)", (time.strftime('%Y-%m-%dT%H:%M:%S'),))
d.execute("insert into meta values('normalization',?)", ('与两个源库一致（E036 长度保持规范化 + 恒等映射）',))
d.commit()
print('\n合并完成：docs %d，segs %d，边界列矛盾 %d，汉字 %s' % (doc_id, seg_id, bad, dom))
print('来源组 top:', json.dumps(fam, ensure_ascii=False)[:600])
print('簇数：', d.execute('select count(distinct cluster_id) from docs').fetchone()[0])
