#!/usr/bin/env python3
"""E042 逐词覆盖报告：在「E036 老库 + E042 补充库」的并集上按 cluster_id 计独立文档数。

口径与 DeepSeek 的 E041 一致：文档正文（规范化后的简体文本）含目标词的精确子串即算 1 篇；
同一 cluster_id 只算一次；域按 docs.domain 分。sample_context 取公开来源正文里目标词前后
20–40 字，不取本项目任何 ASR/真值/字幕。
"""
import argparse, collections, csv, json, pathlib, sqlite3, sys

R = pathlib.Path(__file__).resolve().parents[3]
sys.stdout.reconfigure(encoding='utf-8')
TARGETS = R / 'docs/RAG_CORPUS_TARGETS.tsv'
OLD = R / 'build/e036_corpus/corpus.sqlite'


def scan(db_path, targets, want_ctx=True):
    """返回 target → {'docs': {(domain,cluster):1}, 'fam': {(domain,family)}, 'ctx': [...]}"""
    out = {t: dict(docs=collections.defaultdict(set), fam=collections.defaultdict(set), ctx=[]) for t in targets}
    db = sqlite3.connect(pathlib.Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)
    n = 0
    for dom, fam, cid, tn, url, title in db.execute(
            'select domain, source_family, cluster_id, text_norm, url, title from docs'):
        n += 1
        if n % 20000 == 0:
            print('  %s 已扫 %d 篇' % (pathlib.Path(db_path).name, n), flush=True)
        for t in targets:
            i = tn.find(t)
            if i < 0:
                continue
            out[t]['docs'][dom].add(cid)
            out[t]['fam'][dom].add(fam)
            if want_ctx and len(out[t]['ctx']) < 6:
                left = tn[max(0, i - 18):i].replace(' ', '')
                right = tn[i + len(t):i + len(t) + 18].replace(' ', '')
                out[t]['ctx'].append(dict(domain=dom, family=fam, text=(left + t + right)[:44],
                                          url=url, title=title, source=pathlib.Path(db_path).name))
    db.close()
    return out, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', action='append', default=[], help='补充库路径，可多次')
    ap.add_argument('--out', default=str(R / 'build/e042_corpus/coverage_report.tsv'))
    ap.add_argument('--with-old', action='store_true', help='把 E036 老库并入统计（交付口径）')
    a = ap.parse_args()
    rows = list(csv.DictReader((l for l in TARGETS.read_text(encoding='utf-8').splitlines() if not l.startswith('#')),
                               delimiter='\t'))
    targets = [r['target'] for r in rows]
    paths = ([str(OLD)] if a.with_old and OLD.exists() else []) + a.db
    merged = {t: dict(docs=collections.defaultdict(set), fam=collections.defaultdict(set), ctx=[]) for t in targets}
    per_db = {}
    for p in paths:
        res, n = scan(p, targets)
        per_db[str(p)] = n
        for t in targets:
            for dom, s in res[t]['docs'].items():
                merged[t]['docs'][dom] |= s
            for dom, s in res[t]['fam'].items():
                merged[t]['fam'][dom] |= s
            merged[t]['ctx'].extend(res[t]['ctx'][:2])
    print('扫描文档数：', per_db, flush=True)

    need = dict(P0=(20, 3, '现代'), P1=(10, 2, '历史'), P2_context=(20, 0, None), P2_low=(10, 2, '历史'), P3=(1, 0, None))
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ['target\tdocs_total\tdocs_modern\tdocs_historical\tsource_families\tsample_context\tstatus']
    detail = {}
    for r in rows:
        t, pri = r['target'], r['priority'].replace('-', '_')
        m = merged[t]
        dm, dh = len(m['docs'].get('现代', ())), len(m['docs'].get('历史', ()))
        fams = m['fam'].get('现代', set()) | m['fam'].get('历史', set())
        dom_need = need[pri][2]
        docs = (dm if dom_need == '现代' else dh if dom_need == '历史' else dm + dh)
        famn = len(m['fam'].get(dom_need, set())) if dom_need in ('现代', '历史') else len(fams)
        min_docs, min_fam, _ = need[pri]
        ok = docs >= min_docs and (not min_fam or famn >= min_fam)
        if pri == 'P3':
            ok = docs >= int(r['current_docs_domain'] or 1)
        ctx = m['ctx'][0]['text'] if m['ctx'] else ''
        status = 'OK' if ok else ('MISSING' if docs == 0 else 'BELOW_MIN')
        lines.append('%s\t%d\t%d\t%d\t%d\t%s\t%s' % (t, dm + dh, dm, dh, famn, ctx, status))
        detail[t] = dict(priority=r['priority'], domain_needed=r['domain_needed'], positions=r['positions'],
                         docs_modern=dm, docs_history=dh, families=sorted(fams), min_docs=min_docs,
                         min_families=min_fam, status=status, baseline_docs_domain=r['current_docs_domain'],
                         samples=m['ctx'][:6])
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    out.with_suffix('.detail.json').write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\n'.join(lines[:45]), flush=True)
    print('写出', out)


if __name__ == '__main__':
    main()
