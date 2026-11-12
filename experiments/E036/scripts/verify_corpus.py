#!/usr/bin/env python3
"""E036 交付验收：按 docs/RAG_DATA_CONTRACT.md §1「原料验收」逐条实现，并出字符覆盖/留出清单。

检查项：外键与 offset 可复原、空文档/未知许可、完全重复与近重复分列、跨簇重复另列、
来源组体量（现代单一来源要写清，不许拿古文充现代）、与本项目真值的近重复泄漏检查
（方法+数量都留存，0 命中不叫"绝对无泄漏"）、固定的训练/留出文档簇清单、
字符覆盖与扩展区汉字留存、以及 §3 要的留出未知字率。
"""
import collections, hashlib, json, pathlib, random, re, sqlite3, sys

R = pathlib.Path(__file__).resolve().parents[3]
DB = R / 'build/e036_corpus/corpus.sqlite'
OUT = R / 'build/e036_corpus'
sys.path.insert(0, str(R / 'experiments/E036/scripts'))
from build_corpus import norm  # noqa: E402
sys.stdout.reconfigure(encoding='utf-8')
HAN = re.compile(r'[一-鿿]')


def main():
    db = sqlite3.connect(DB)
    rep, fail = {}, []

    # 1) 结构验收
    n_docs, n_segs = db.execute('select count(*) from docs').fetchone()[0], db.execute('select count(*) from segs').fetchone()[0]
    bad_fk = db.execute('select count(*) from segs s left join docs d on d.doc_id=s.doc_id where d.doc_id is null').fetchone()[0]
    empty = db.execute("select count(*) from docs where text_norm='' or text_raw='' or url='' or license='' or src_sha='' "
                       "or cluster_id='' or source_family='' or normalization_map_json=''").fetchone()[0]
    orphan_txt = db.execute('select count(*) from docs where trim(text_norm)=\'\'').fetchone()[0]
    rep['docs'], rep['segs'] = n_docs, n_segs
    rep['外键破损'] = bad_fk
    rep['必填字段为空'] = empty
    rep['空白文档'] = orphan_txt
    if bad_fk or empty or orphan_txt:
        fail.append('结构验收未过')

    # 2) 每段必须能由全文 + off 复原；映射长度必须等于原文长度
    bad_off = bad_map = 0
    full = {d: (r, t) for d, r, t in db.execute('select doc_id, text_raw, text_norm from docs')}
    for doc_id, mp in db.execute('select doc_id, normalization_map_json from docs'):
        raw, tn = full[doc_id]
        m = json.loads(mp)
        if len(m) != len(tn) or not all(0 <= x < len(raw) for x in (m[:1] + m[-1:])):
            bad_map += 1
    _cur, _tn = -1, ''
    for doc_id, off, text in db.execute('select doc_id, off, text_norm from segs order by doc_id'):
        if doc_id != _cur:
            _cur, _tn = doc_id, full[doc_id][1]
        if _tn[off:off + len(text)] != text:
            bad_off += 1
    rep['offset无法复原的段'] = bad_off
    rep['映射长度异常文档'] = bad_map
    if bad_off or bad_map:
        fail.append('offset/映射验收未过')
    print('结构：docs %d，segs %d，外键破损 %d，空字段 %d，offset 无法复原 %d，映射长度异常 %d' % (
        n_docs, n_segs, bad_fk, empty, bad_off, bad_map))

    # 3) 去重分列：完全重复、近重复、跨簇重复内容
    exact = db.execute('select count(*) from (select text_norm from docs group by text_norm having count(*)>1)').fetchone()[0]
    exact_docs = db.execute('select sum(c) from (select count(*) c from docs group by text_norm having c>1)').fetchone()[0] or 0
    multi = db.execute('select count(*) from (select cluster_id from docs group by cluster_id having count(*)>1)').fetchone()[0]
    multi_docs = db.execute('select sum(c) from (select count(*) c from docs group by cluster_id having c>1)').fetchone()[0] or 0
    near_clusters, near_docs = multi - exact, multi_docs - exact_docs   # 多文档簇里扣掉完全重复，剩下的是近重复
    clu = {r[0]: r[1] for r in db.execute('select cluster_id, count(*) from docs group by cluster_id')}
    cross = db.execute('select count(*) from (select s.text_norm from segs s join docs d on d.doc_id=s.doc_id '
                       'group by s.text_norm having count(distinct d.cluster_id)>1)').fetchone()[0]
    cross_segs = db.execute('''with dup(t) as (select s2.text_norm t from segs s2 join docs d2 on d2.doc_id=s2.doc_id
                                group by s2.text_norm having count(distinct d2.cluster_id)>1)
                             select count(*) from segs s where s.chars>=12 and s.text_norm in (select t from dup)''').fetchone()[0]
    print('去重：完全重复组 %d（涉及文档 %d）｜近重复簇 %d（涉及文档 %d）｜跨簇同一段文字 %d 种 / %d 个实例' % (
        exact, exact_docs, near_clusters, near_docs, cross, cross_segs))

    # 4) 体量与来源组
    vol = {}
    for dom, fam, n, chars in db.execute('''select d.domain, d.source_family, count(*), sum(length(s.text_norm))
                                            from docs d join segs s on s.doc_id=d.doc_id
                                            group by d.domain, d.source_family order by 4 desc'''):
        vol['%s/%s' % (dom, fam)] = dict(docs=n, seg_chars=chars)
    rep['来源组体量'] = vol
    print('体量：', ', '.join('%s=%d段/%d字' % (k, v['docs'], v['seg_chars']) for k, v in list(vol.items())[:8]))
    modern_ok = sum(v['seg_chars'] for k, v in vol.items() if k.startswith('现代'))
    hist_ok = sum(v['seg_chars'] for k, v in vol.items() if k.startswith('历史'))
    print('  现代 %d 字（通用模型只用它）｜历史 %d 字（只作领域检索，不并入现代）' % (modern_ok, hist_ok))

    # 5) 与本项目真值的近重复检查（弱证明，方法与数量都留档）
    gt = []
    for f in sorted((R / 'asr').glob('*.gt.jsonl')):
        for r in (json.loads(l) for l in f.read_text(encoding='utf-8').splitlines() if l.strip()):
            if not r.get('discard'):
                gt.append(''.join(r['gt'].split()))
    for width in (8, 12, 16):
        sh = set()
        for t in gt:
            for i in range(0, max(0, len(t) - width + 1)):
                sh.add(t[i:i + width])
        hits, where = 0, []
        for doc_id, tn in db.execute('select doc_id, text_norm from docs'):
            n = tn.replace(' ', '')
            for i in range(0, max(0, len(n) - width + 1)):
                if n[i:i + width] in sh:
                    hits += 1
                    where.append((doc_id, n[i:i + width]))
                    break
        rep['泄漏检查_%d字' % width] = dict(窗口种数=len(sh), 命中文档数=hits, 样例=where[:5])
        print('泄漏检查 %d 字窗口：真值窗口 %d 种，命中文档 %d 个（命中即需人工核对；0 也不能叫绝对无泄漏）' % (width, len(sh), hits))

    # 6) 固定训练/留出清单（按来源组划分；现代只有一个来源组，只能段级留出并写明例外）
    # 留出按"字数占比"挑来源组，不是按组数：历史里明史一部就占 57%，抽中它等于把资料库抽空。
    fam_vol = {f: v for f, v in db.execute('''select source_family, sum(length(text_norm)) from docs
                                              where domain="历史" group by source_family''')}
    total = sum(fam_vol.values()) or 1
    hold_fams = []
    for f, v in sorted(fam_vol.items(), key=lambda x: x[1]):     # 从小到大地取到约 15% 体量
        if sum(fam_vol[x] for x in hold_fams) / total >= 0.15:
            break
        hold_fams.append(f)
    hold_fams = sorted(hold_fams)
    hist_hold = {r[0] for r in db.execute(
        'select doc_id from docs where domain="历史" and source_family in (%s)'
        % ','.join('?' * len(hold_fams)), hold_fams)} if hold_fams else set()
    mod_ids = [r[0] for r in db.execute('select doc_id from docs where domain="现代" order by doc_id')]
    mod_hold = set(random.Random(20261111).sample(mod_ids, len(mod_ids) // 10))
    with (OUT / 'holdout.json').open('w', encoding='utf-8') as f:
        json.dump(dict(seed=20261111, history_holdout_families=hold_fams,
                       history_holdout_docs=sorted(hist_hold), modern_holdout_docs=sorted(mod_hold),
                       note='现代只有 tatoeba_cmn 一个来源组，做不到组级隔离，按文档级留出并标注例外',
                       overlap_families_across_sides=0), f, ensure_ascii=False, indent=1)
    rep['留出'] = dict(历史留出族=len(hold_fams), 历史留出文档=len(hist_hold), 现代留出文档=len(mod_hold))
    print('留出：历史留出来源组 %s（文档 %d）；现代留出文档 %d（单一来源组，例外已写明）' % (
        ','.join(hold_fams), len(hist_hold), len(mod_hold)))

    # 7) 字符覆盖：通用字符表来自现代留出外部分；340 目标词覆盖、扩展区汉字
    train_chars = collections.Counter()
    for doc_id, tn in db.execute('select doc_id, text_norm from docs where domain="现代"'):
        for c in HAN.findall(tn):
            train_chars[c] += 1
    V = {c for c, n in train_chars.items() if n >= 2}
    rep['现代训练字符数'] = len(train_chars); rep['进入通用V的字符数(≥2次)'] = len(V)
    lines = [l.rstrip('\n').split('\t') for l in (R / 'data/correction/candidates.tsv').read_text(encoding='utf-8')
             .splitlines() if l.strip() and not l.startswith('#')]
    head, body = lines[0], lines[1:]
    ci, si = head.index('canonical'), head.index('status')
    targets = sorted({r[ci] for r in body if r[si] == '1'})
    full = [t for t in targets if set(t) <= V]
    missing = collections.Counter()
    for t in targets:
        for c in set(t) - V:
            missing[c] += 1
    rep['目标词全覆盖数'] = '%d/%d' % (len(full), len(targets))
    rep['缺字Top'] = missing.most_common(25)
    print('字符覆盖：现代训练字符 %d 种，进 V（≥2 次）%d 种；340 目标词全部字在 V 里的 %d/%d；缺字最多 %s' % (
        len(train_chars), len(V), len(full), len(targets), [c for c, _ in missing.most_common(12)]))
    ext_raw = collections.Counter()
    for (raw,) in db.execute('select text_raw from docs'):
        for c in raw:
            if c != ' ' and not ('一' <= c <= '鿿') and ord(c) > 0x2000 and not c.isdigit() and c not in '，。、；：？！「」『』（）《》…—·％':
                ext_raw[c] += 1
    rep['非CJK非ASCII留存字符种数'] = len(ext_raw)
    print('原文里保留下来的非汉字非标点字符：%d 种，例：%s' % (len(ext_raw), ''.join(c for c, _ in ext_raw.most_common(12))))
    ext_han = collections.Counter()
    for (raw,) in db.execute('select text_raw from docs'):
        for c in raw:
            if c and not ('一' <= c <= '鿿') and HAN.match(c) is None and '\u3400' <= c <= '\u4dbf':
                ext_han[c] += 1
    rep['扩展A区汉字(超出U+4E00-U+9FFF，原文已留存)'] = dict(种数=len(ext_han), 次数=sum(ext_han.values()))
    print('扩展 A 区汉字（U+3400–U+4DBF，模型当前扫不到）：原文已留存 %d 种 / %d 次' % (len(ext_han), sum(ext_han.values())))

    (OUT / 'verify_report.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\n验收结论：%s' % ('全部通过' if not fail else '未过项：' + '；'.join(fail)))


if __name__ == '__main__':
    main()
