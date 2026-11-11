#!/usr/bin/env python3
"""E042：把 jsonl 里的新语料建成 docs/RAG_DATA_CONTRACT.md 口径的 corpus_supplement.sqlite。

规范化、边界分类、去重身份三件事直接复用 E036 建库的那份代码（import，不重写），
这样补充批次与 build/e036_corpus 是同一套语义；本文件只新增两件事：
  1) docs 增加 register / period / source_batch / rev_timestamp 列（只加列，不动原列语义）；
  2) 来源多样性封顶：按 sha256(标题+URL) 的固定顺序抽样，使任一来源组不超过该批总量的 --max-share。
"""
import argparse, collections, hashlib, importlib.util, io, json, pathlib, re, sqlite3, sys, time, zlib

R = pathlib.Path(__file__).resolve().parents[3]
sys.stdout.reconfigure(encoding='utf-8')
spec = importlib.util.spec_from_file_location('e036build', R / 'experiments/E036/scripts/build_corpus.py')
E036 = importlib.util.module_from_spec(spec)
sys.argv_backup = sys.argv
sys.argv = ['build_corpus.py']                      # 只 import，不触发 __main__
spec.loader.exec_module(E036)
sys.argv = sys.argv_backup
norm, edge, shingles, minhash, clusters = E036.norm, E036.edge, E036.shingles, E036.minhash, E036.clusters

OUT = R / 'build/e042_corpus'
JSONL = OUT / 'jsonl'
NORMALIZATION_VERSION = E036.NORMALIZATION_VERSION

# 古籍的 period 该填年代而不是书名（契约里 period=大致年代）。未列出的沿用抓取时的标注。
PERIOD = {'資治通鑑': '北宋编著，记战国—五代', '宋史': '元修，记960–1279', '晉書': '唐修，记265–420',
          '清史稿': '民国初修，记1616–1912', '鹽鐵論': '西汉（桓宽编）', '通典': '唐（杜佑）',
          '文獻通考': '元（马端临）', '宋會要輯稿': '宋史料，清辑本', '續資治通鑑長編': '南宋（李焘）',
          '金史': '元修，记1115–1234', '元史': '明修，记1206–1368', '唐會要': '北宋（王溥）',
          '朝花夕拾': '1928（鲁迅回忆散文）'}


def period_of(d):
    """古籍在 jsonl 里 period 暂存书名，这里换成契约要求的年代；其余来源沿用原标注。"""
    for key in (d.get('work') or '', (d.get('title') or '').split('/')[0], d.get('period') or ''):
        if key in PERIOD:
            return PERIOD[key]
    return str(d.get('period', ''))


def load():
    docs = []
    for f in sorted(JSONL.glob('*.jsonl')):
        for line in f.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            d['batch_file'] = f.name
            docs.append(d)
    return docs


def order(d):
    return hashlib.sha256((d['title'] + '|' + d['url']).encode()).hexdigest()


def plan(docs, max_share, budget):
    """按域各自求封顶值 C：单组不超过该域选用总量的 max_share，且该域总量不超过 budget 字。

    used(C)=Σmin(avail,C) 与 top(C)=max(min(avail,C)) 都随 C 单调，直接二分取最大可行 C。
    budget 是本轮"补语料"的规模（需求文档：现代 3,000 万目标、历史 500 万），
    不是为了冲量把整站百科全塞进库里。
    """
    picked, cap_info = [], {}
    for dom in ('现代', '历史'):
        sub = [d for d in docs if d['domain'] == dom]
        if not sub:
            continue
        avail = collections.Counter()
        for d in sub:
            avail[d['source_family']] += d['chars']

        def used(c):
            return sum(min(v, c) for v in avail.values())

        def top(c):
            return max(min(v, c) for v in avail.values())

        hi = max(avail.values())
        lo = 1.0
        # 来源组不足 ⌈1/max_share⌉ 组时，「单组不超过 max_share」在数学上不可满足：
        # 这时只用总量预算约束，并把该域标记为 share 约束未生效，交给人判读。
        share_feasible = 1.0 / max_share <= len(avail)

        def ok(c):
            u = used(c)
            if budget.get(dom) and u > budget[dom]:
                return False
            return (not share_feasible) or top(c) <= max_share * u + 1

        for _ in range(70):
            mid = (lo + hi) / 2
            if ok(mid):
                lo = mid
            else:
                hi = mid
            cap = lo
        if ok(hi):
            cap = hi
        per = collections.Counter()
        for d in sorted(sub, key=lambda x: (x['source_family'], order(x))):
            f = d['source_family']
            if per[f] + d['chars'] > cap:
                continue
            per[f] += d['chars']
            picked.append(d)
        tot = sum(per.values()) or 1
        cap_info[dom] = dict(cap=int(cap), budget=budget.get(dom), used=int(tot), families=len(per),
                             share_constraint_applied=bool(share_feasible),
                             share={f: round(v * 100.0 / tot, 1) for f, v in per.items()})
        if per:
            print('%s 封顶 %d 字/组，选用 %d 字 / %d 组，最大占比 %.1f%%，share 约束%s' % (
                dom, cap, tot, len(per), max(per.values()) * 100.0 / tot,
                '生效' if share_feasible else '未生效（组数太少）'), flush=True)
    avail_all = collections.Counter()
    for d in docs:
        avail_all[(d['domain'], d['source_family'])] += d['chars']
    per_sel = collections.Counter()
    for d in picked:
        per_sel[(d['domain'], d['source_family'])] += d['chars']
    return picked, avail_all, per_sel, cap_info


def gt_windows(shingle=12):
    """本项目七篇真值与原始 ASR 的 12 字窗口：公开语料里撞上就剔整篇，不改验收口径。

    AISHELL 这类独立发布的语料可能与旁白写出同一个通用句式（实测撞过"已经到了非解决不可的地步"），
    那是巧合不是抄答案；但需求文档写的是命中必须为 0，所以按文档执行，并把剔除项逐条留痕。
    """
    out = set()
    for f in sorted((R / 'asr').glob('*.gt.jsonl')):
        for line in f.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get('discard'):
                continue
            for field in ('gt', 'text'):
                n, _ = norm(row.get(field, '') or '')
                for i in range(0, max(0, len(n) - shingle + 1)):
                    w = n[i:i + shingle]
                    if ' ' not in w:
                        out.add(w)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max-share', type=float, default=0.28)
    ap.add_argument('--budget-modern', type=int, default=24000000, help='现代域选用汉字上限（需求文档目标 3,000 万）')
    ap.add_argument('--budget-history', type=int, default=9000000, help='历史域选用汉字上限（需求文档 500 万）')
    ap.add_argument('--plan-only', action='store_true')
    ap.add_argument('--out', default=str(OUT / 'corpus_supplement.sqlite'))
    a = ap.parse_args()
    t0 = time.time()
    docs = load()
    print('读入文档 %d 篇，汉字 %d' % (len(docs), sum(d['chars'] for d in docs)), flush=True)
    picked, avail, per, cap_info = plan(docs, a.max_share,
                                        {'现代': a.budget_modern, '历史': a.budget_history})
    cap = min([v['cap'] for v in cap_info.values()] or [0])
    print('选用 %d 篇 / %d 字' % (len(picked), sum(d['chars'] for d in picked)), flush=True)
    for k in sorted(avail, key=lambda x: -avail[x]):
        print('  %-8s %-34s 可用 %9d 选用 %9d' % (k[0], k[1], avail[k], per.get(k, 0)), flush=True)
    if a.plan_only:
        return
    items = []
    W = gt_windows()
    print('泄漏窗口 %d 个，建库时逐篇比对' % len(W), flush=True)
    dropped = []
    for d in picked:
        n, idx = norm(d['raw'])
        hit = next((sh for run in re.split(' +', n)
                    for sh in (run[i:i + 12] for i in range(0, max(0, len(run) - 11))) if sh in W), None)
        if hit:
            dropped.append(dict(domain=d['domain'], source_family=d['source_family'], title=d['title'],
                                url=d['url'], window=hit))
            continue
        runs = [(m.start(), m.group(0)) for m in re.finditer(r'[^ ]+', n)]
        if not runs:
            continue
        it = dict(domain=d['domain'], runs=runs, text_norm=n, map=idx, raw=d['raw'], work=d.get('work', ''),
                  title=d['title'], url=d['url'], license=d['license'], source_family=d['source_family'],
                  register=d.get('register', ''), period=period_of(d), src_sha=d['src_sha'],
                  fetched_at=d.get('fetched_at') or d.get('rev_timestamp') or '',
                  rev_timestamp=d.get('rev_timestamp', ''), batch=d.get('batch_file', ''))
        it['shs'] = {zlib.crc32(g.encode()) for g in shingles(n)}
        items.append(it)
    print('规范化完成 %d 篇，%.0fs' % (len(items), time.time() - t0), flush=True)
    if dropped:
        with (OUT / 'leak_dropped.tsv').open('w', encoding='utf-8', newline='\n') as fh:
            fh.write('domain\tsource_family\ttitle\twindow\turl\n')
            for x in dropped:
                fh.write('\t'.join([x['domain'], x['source_family'], x['title'], x['window'], x['url']]) + '\n')
    print('撞窗剔除 %d 篇（逐条见 leak_dropped.tsv）' % len(dropped), flush=True)

    for dom in ('现代', '历史'):
        sub = [x for x in items if x['domain'] == dom]
        for x in sub:
            x['sig'] = minhash(x['shs']) if len(x['shs']) >= 4 else None
        groups, exact_groups, near_merged = clusters(sub)
        print('%s：完全重复组 %d，近重复合并 %d，文档簇 %d（文档 %d）' % (
            dom, exact_groups, near_merged, len(groups), len(sub)), flush=True)
        for g in groups:
            cid = hashlib.sha256(sub[g[0]]['text_norm'].encode()).hexdigest()[:16]
            for i in g:
                sub[i]['cluster_id'] = cid
                sub[i]['cluster_size'] = len(g)
    db_path = pathlib.Path(a.out)
    if db_path.exists():
        db_path.unlink()
    db = sqlite3.connect(db_path)
    db.executescript('''
    create table docs(doc_id integer primary key, domain text not null, work text, title text,
      url text not null, license text not null, fetched_at text, src_sha text not null,
      cluster_id text not null, cluster_size integer not null default 1, source_family text not null,
      text_raw text not null, text_norm text not null,
      normalization_map_json text not null, normalization_version text not null, boundary_kind text not null,
      chars integer not null, runs integer not null,
      register text, period text, source_batch text, rev_timestamp text);
    create table segs(seg_id integer primary key, doc_id integer not null references docs,
      ord integer not null, off integer not null, text_norm text not null, chars integer not null,
      boundary_kind text not null, left_edge text, right_edge text,
      left_class text, right_class text,
      left_is_stop integer not null default 0, right_is_stop integer not null default 0);
    create index segs_doc on segs(doc_id, ord);
    create index docs_dom on docs(domain, source_family, cluster_id);
    create table meta(k text primary key, v text);
    ''')
    doc_id = seg_id = 0
    fam = collections.Counter()
    for it in sorted(items, key=lambda x: (x['domain'], x['source_family'], x['title'])):
        doc_id += 1
        n_stop = sum(it['raw'].count(c) for c in '。？！')
        n_pause = sum(it['raw'].count(c) for c in '，、；：')
        kind = ('来源自带标点' if n_stop else '仅有句内逗读，无句末标点' if n_pause else '全篇无明显句读')
        db.execute('insert into docs values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (
            doc_id, it['domain'], it['work'], it['title'], it['url'], it['license'], it['fetched_at'],
            it['src_sha'], it['cluster_id'], it['cluster_size'], it['source_family'], it['raw'], it['text_norm'],
            json.dumps(it['map'], separators=(',', ':')), NORMALIZATION_VERSION, kind,
            len(it['text_norm']), len(it['runs']), it['register'], it['period'], it['batch'],
            it.get('rev_timestamp', '')))
        raw, tn = it['raw'], it['text_norm']
        for o, (off, run) in enumerate(it['runs']):
            seg_id += 1
            src = it['map']
            le = raw[src[off - 1]] if off > 0 and src[off - 1] < len(raw) else '^'
            ri = raw[src[off + len(run)]] if off + len(run) < len(src) and src[off + len(run)] < len(raw) else '$'
            lcls, lstop = edge(le, it['domain'])
            rcls, rstop = edge(ri, it['domain'])
            db.execute('insert into segs values(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (seg_id, doc_id, o, off, run, len(run), kind, le, ri, lcls, rcls, lstop, rstop))
        fam[(it['domain'], it['source_family'])] += 1
        if doc_id % 5000 == 0:
            db.commit()
            print('  写入 %d 篇 / %d 段，%.0fs' % (doc_id, seg_id, time.time() - t0), flush=True)
    db.execute("insert into meta values('built_at',?)", (time.strftime('%Y-%m-%dT%H:%M:%S'),))
    db.execute("insert into meta values('normalization',?)", (NORMALIZATION_VERSION + ' 映射表SHA=' + E036.MAP_SHA,))
    db.execute("insert into meta values('family_cap_chars',?)", (str(int(cap)),))
    db.execute("insert into meta values('sources',?)", (json.dumps(
        {'%s/%s' % k: v for k, v in fam.items()}, ensure_ascii=False),))
    db.commit()
    rep = dict(docs=doc_id, segs=seg_id, bytes=db_path.stat().st_size,
               sha256=hashlib.sha256(db_path.read_bytes()).hexdigest(),
               families={'%s/%s' % k: v for k, v in fam.items()},
               family_avail_chars={'%s/%s' % k: v for k, v in avail.items()},
               family_used_chars={'%s/%s' % k: v for k, v in per.items()},
               cap_chars=int(cap), cap_per_domain=cap_info, max_share=a.max_share,
               seconds=round(time.time() - t0, 1),
               normalization_version=NORMALIZATION_VERSION)
    (OUT / 'build_report.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\n写出 %s：docs %d，segs %d，%.0fMB，用时 %.0fs' % (
        db_path, doc_id, seg_id, db_path.stat().st_size / 1e6, time.time() - t0), flush=True)


if __name__ == '__main__':
    main()
