#!/usr/bin/env python3
"""按 docs/RAG_DATA_CONTRACT.md §1 交付原料库 corpus.sqlite（E036，不覆盖 E033）。

与 E033 的三点实质差别：
  1) 句界不再人为制造。历史来源在维基文库扫描转录里本来就没有句读，且 E030 的清洗步骤把原始
     换行也抹掉了；这里从 raw/*.json 的 wikitext 恢复**原文献行边界**（先证明恢复出来的汉字流
     与 E030 逐字相同，才敢用它当边界），一个 run 就是一行，不再出现"250 字块首当句首"。
  2) 每段都能在 docs.text_norm 里用 off 复原，segs 只是索引，全文与映射才是事实来源。
  3) 身份与去重分开：source_family（同一书/同一注释本/同一语料组）用于留出划分，
     cluster_id 用于证据计数封顶——完全重复用整文哈希，近重复用 8 字 shingle 的 MinHash 并查集。
"""
import collections, hashlib, itertools, json, pathlib, re, sqlite3, sys, time, zlib

R = pathlib.Path(__file__).resolve().parents[3]
OUT = R / 'build/e036_corpus'
RAW_HIST = R / 'build/e030_corpus/raw'
TXT_HIST = R / 'build/e030_corpus/txt'
MODERN = R / 'build/e031_corpus/cmn_sentences.tsv'
CEDICT = R / 'data/raw/cedict_ts.u8'
MAN_HIST = R / 'build/e030_corpus/manifest.json'
NORMALIZATION_VERSION = 'e036-norm-1（长度保持：汉字保留或繁→简，其余每字符变一个空格）'
sys.stdout.reconfigure(encoding='utf-8')


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def trad_simp_map():
    pairs = {}
    for line in CEDICT.read_text(encoding='utf-8').splitlines():
        if line.startswith('#'):
            continue
        m = re.match(r'(\S+)\s+(\S+)\s+\[', line)
        if m and len(m.group(1)) == len(m.group(2)):
            for a, b in zip(m.group(1), m.group(2)):
                if a != b and '一' <= a <= '鿿':
                    pairs.setdefault(a, b)
    return pairs


TS = trad_simp_map()
MAP_SHA = sha(CEDICT)[:16]


def norm(text):
    """长度保持的规范化：返回 (规范化文本, 每个规范化字符对应的原文下标)。"""
    out, idx = [], []
    for i, ch in enumerate(text):
        if '一' <= ch <= '鿿' or (ch in TS):
            out.append(TS.get(ch, ch)); idx.append(i)
        elif chr(0x3400) <= ch <= chr(0x4DBF) or ord(ch) > 0x20000:      # 扩展区汉字：原样保留并计数
            out.append(ch); idx.append(i)
        else:
            out.append(' '); idx.append(i)
    return ''.join(out), idx


MARK = re.compile(r'\{\{[^|}]*\|?|\}\}|\[\[|\]\]|<[^>]*>|={2,}')


def strip_markup(wikitext):
    """与 E030 的 clean() **同一串正则、同一顺序**，只是不删换行。

    E030 最后用 ''.join(ch for ch in t if 是汉字) 收字，把原文献的行边界一起抹掉了。
    这里保持同样的处理顺序（含 <[^>]+> 会连带删掉编辑说明注释里的汉字这一点），
    之后逐字校验汉字流必须与已用过的 txt 完全相同，才敢把行当边界用。
    """
    t = re.sub(r'<ref[^>]*>.*?</ref>', '', wikitext, flags=re.S)
    t = re.sub(r'<ref[^/>]*\s*/>', '', t)
    t = re.sub(r'<[^>]+>', '', t)
    t = re.sub(r'\{\{[^{}]*\}\}', '', t)
    t = re.sub(r"'''?", '', t)
    t = re.sub(r'\[\[([^\]|]*\|)?([^]]*)\]\]', r'\2', t)
    t = re.sub(r'^\s*[!#|;:].*$', '', t, flags=re.M)
    return t


def han_only(text):
    return ''.join(c if ('一' <= c <= '鿿' or c in TS) else '' for c in text)


QUOTE = {chr(c) for c in (0x201c,0x201d,0x2018,0x2019,0x300c,0x300d,0x300e,0x300f,0xff08,0xff09,0x300a,0x300b,0x3008,0x3009,0x5b,0x5d,0x3010,0x3011,0x28,0x29,0x22,0x27,0x60)}
WHITE = {chr(c) for c in (0x20,0x0a,0x09,0x0d,0x3000,0x00a0)}

def edge(ch, domain):
    """段端点的唯一分类入口：一次同时给出「类别」和「是否句末」，两者不可能互相矛盾。

    上一版 left_class/right_class 用一套字符表、*_is_stop 用另一套，导致 32 处
    「类别=句末标点但 is_stop=0」；同时把所有非句末字符一律标成"换行或空白"，
    把引号、书名号、数字、模板残留都算进了可跨越的空白里（右端 65,365 处）。
    现在按实测字符分类：只有真正的空白/换行才是"排版边界"，其余各自成类，都不是句末。
    历史的 wikitext 表格里残留 ASCII ! 和 ?，不是句读，所以半角 ?! 只在现代算句末。
    """
    if ch == '^':
        return '文档头', 0
    if ch in ('$', ''):
        return '文档尾', 0
    stop = set('。？！') | ({'?', '!'} if domain == '现代' else set())
    if ch in stop:
        return '句末标点', 1
    if ch in '，、；：,;:':
        return '句内停顿', 0
    if ch in QUOTE:
        return '引号或括号', 0
    if ch.isdigit():
        return '数字', 0
    if ('a' <= ch.lower() <= 'z'):
        return '拉丁字母', 0
    if ch in WHITE:
        return '空白或换行', 0
    return '其他符号或标记残留', 0


def history_docs():
    """每个文件一个文档；边界用恢复出来的原文献行。先验证汉字流与 E030 一致。"""
    man = json.loads(MAN_HIST.read_text(encoding='utf-8'))
    bad = 0
    for jf in sorted(RAW_HIST.glob('*.json')):
        d = json.loads(jf.read_text(encoding='utf-8'))
        raw = strip_markup(d.get('content', ''))
        txt = TXT_HIST / (jf.stem + '.txt')
        if not txt.exists():
            continue
        old = han_only(txt.read_text(encoding='utf-8'))
        if han_only(raw) != old:                      # 恢复的行文本汉字流必须与已用过的正文逐字相同
            bad += 1
            raw = txt.read_text(encoding='utf-8')     # 不一致就退回旧正文（无换行，整篇一个 run）
        work = jf.stem.split('_')[0]
        yield dict(work=work, title=d.get('title', jf.stem), raw=raw,
                   url='https://zh.wikisource.org/wiki/' + d.get('title', '').replace(' ', '_'),
                   **{'license': man.get('license', ''), 'fetched_at': man.get('fetched_at', ''), 'src_sha': sha(txt)})
    print('  历史：原文献行恢复后汉字流与 E030 不一致的文件 %d 个（已退回旧正文）' % bad)


def modern_docs():
    src_sha = sha(MODERN)
    for line in MODERN.read_text(encoding='utf-8', errors='replace').split('\n'):
        parts = line.split('\t')
        if len(parts) >= 3 and parts[2].strip():
            yield dict(work='Tatoeba 中文句库 cmn_sentences.tsv', title='sentence#' + parts[0],
                       raw=parts[2], url='https://downloads.tatoeba.org/exports/persistent/cmn_sentences.tar.bz2#id=' + parts[0],
                       **{'license': 'CC BY 2.0 FR（署名 Tatoeba 项目；衍生表同样按 CC BY 提供）',
                          'fetched_at': '2026-11-08T05:22:00', 'src_sha': src_sha})


def shingles(text, k=8):
    for run in re.split(' +', text):
        for i in range(0, max(0, len(run) - k + 1)):
            yield run[i:i + k]


def minhash(shingle_ids, buckets=16):
    """band 最小哈希：每个 shingle 只算一次 crc32，band 用线性变换取最小值（纯 Python 也能跑动）。"""
    hs = [None] * buckets
    for h in shingle_ids:
        for b in range(buckets):
            v = ((b + 1) * h + 7919 * b) & 0xFFFFFFFF
            if hs[b] is None or v < hs[b]:
                hs[b] = v
    return hs


def clusters(items, threshold=0.8):
    """完全重复按整文哈希；近重复按 MinHash 相似度并查集（只对同 domain 内比较，避免古文并到现代）。"""
    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    exact = collections.defaultdict(list)
    for i, it in enumerate(items):
        exact[hashlib.sha256(it['text_norm'].encode()).hexdigest()].append(i)
    exact_groups = 0
    for grp in exact.values():
        if len(grp) > 1:
            exact_groups += 1
            for x in grp[1:]:
                union(grp[0], x)
    inv = collections.defaultdict(list)
    for i, it in enumerate(items):
        if it.get('sig'):
            for b, v in enumerate(it['sig']):
                inv[(b, v)].append(i)
    cand = set()
    for grp in inv.values():
        if 1 < len(grp) <= 400:
            for a, b in itertools.combinations(sorted(grp)[:60], 2):
                cand.add((a, b))
    merged_near = 0
    for a, b in cand:
        if find(a) == find(b):
            continue
        sa, sb = items[a]['shs'], items[b]['shs']
        if not sa or not sb or len(sa & sb) / len(sa | sb) < threshold:
            continue
        union(a, b); merged_near += 1
    groups = collections.defaultdict(list)
    for i in range(len(items)):
        groups[find(i)].append(i)
    return list(groups.values()), exact_groups, merged_near


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    db_path = OUT / 'corpus.sqlite'
    if db_path.exists():
        db_path.unlink()
    items = []
    for dom, gen in (('历史', history_docs()), ('现代', modern_docs())):
        for d in gen:
            n, idx = norm(d['raw'])
            runs = [(m.start(), m.group(0)) for m in re.finditer(r'[^ ]+', n)]
            if not runs:
                continue
            it = dict(domain=dom, runs=runs, text_norm=n, map=idx, **d)
            it['shs'] = {zlib.crc32(g.encode()) for g in shingles(n)}
            items.append(it)
        print('%s 文档 %d，用时 %.0fs' % (dom, sum(1 for x in items if x['domain'] == dom), time.time() - t0), flush=True)
    for dom in ('历史', '现代'):
        sub = [x for x in items if x['domain'] == dom]
        for x in sub:
            x['sig'] = minhash(x['shs']) if len(x['shs']) >= 4 else None
        groups, exact_groups, near_merged = clusters(sub)
        print('%s：完全重复组 %d，近重复合并 %d，最终文档簇 %d（文档 %d）' % (dom, exact_groups, near_merged, len(groups), len(sub)), flush=True)
        for g in groups:
            cid = hashlib.sha256(sub[g[0]]['text_norm'].encode()).hexdigest()[:16]
            for i in g:
                sub[i]['cluster_id'] = cid
                sub[i]['cluster_size'] = len(g)

    db = sqlite3.connect(db_path)
    db.executescript('''
    create table docs(doc_id integer primary key, domain text not null, work text, title text,
      url text not null, license text not null, fetched_at text, src_sha text not null,
      cluster_id text not null, cluster_size integer not null default 1, source_family text not null,
      text_raw text not null, text_norm text not null,
      normalization_map_json text not null, normalization_version text not null, boundary_kind text not null,
      chars integer not null, runs integer not null);
    create table segs(seg_id integer primary key, doc_id integer not null references docs,
      ord integer not null, off integer not null, text_norm text not null, chars integer not null,
      boundary_kind text not null,
      left_edge text, right_edge text,
      left_class text, right_class text,
      left_is_stop integer not null default 0, right_is_stop integer not null default 0);
    create index segs_doc on segs(doc_id, ord);
    create table meta(k text primary key, v text);
    ''')
    doc_id = seg_id = 0
    fams = collections.Counter()
    for it in sorted(items, key=lambda x: (x['domain'], x['work'], x['title'])):
        doc_id += 1
        fam = ('tatoeba_cmn' if it['domain'] == '现代' else re.sub(r'[（(].*$', '', it['work']).strip())
        # 不按"域"猜边界：实测这一篇有没有句读。7 部历史书里 5 部带标点，只有四庫全書本（史記集解、後漢書補逸）没有。
        n_stop = sum(it['raw'].count(c) for c in '。？！')
        n_pause = sum(it['raw'].count(c) for c in '，、；：')
        if it['domain'] == '现代':
            kind = '来源自带标点'
        elif n_stop:
            kind = '史源整理本：有句末标点'
        elif n_pause:
            kind = '仅有句内逗读，无句末标点'
        else:
            kind = '全篇无标点，段边界=原文献换行'
        db.execute('insert into docs values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (
            doc_id, it['domain'], it['work'], it['title'], it['url'], it['license'], it['fetched_at'],
            it['src_sha'], it['cluster_id'], it['cluster_size'], fam, it['raw'], it['text_norm'],
            json.dumps(it['map'], separators=(',', ':')), NORMALIZATION_VERSION, kind,
            len(it['text_norm']), len(it['runs'])))
        raw, tn = it['raw'], it['text_norm']
        for o, (off, run) in enumerate(it['runs']):
            seg_id += 1
            # 段两端挨着的原文字符：让消费者自己判断这是句末标点、句中停顿，还是排版换行。
            # 历史没有句读，两端永远不该拿到句首/句末证据，这一列就是给它用的。
            src = it['map']
            le = raw[src[off - 1]] if off > 0 and src[off - 1] < len(raw) else '^'
            ri = raw[src[off + len(run)]] if off + len(run) < len(src) and src[off + len(run)] < len(raw) else '$'
            # 历史 wikitext 残留的表格符 ! 和 ? 不是句读，只有现代（自带标点）才把 ASCII ? ! 当句末
            lcls, lstop = edge(le, it['domain'])
            rcls, rstop = edge(ri, it['domain'])
            db.execute('insert into segs values(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (seg_id, doc_id, o, off, run, len(run), kind, le, ri,
                        lcls, rcls, lstop, rstop))
        fams[(it['domain'], fam)] += 1
    db.execute("insert into meta values('built_at',?)", (time.strftime('%Y-%m-%dT%H:%M:%S'),))
    db.execute("insert into meta values('inputs',?)", (json.dumps(dict(
        modern_sha=sha(MODERN), cedict_sha=sha(CEDICT), history_manifest_sha=sha(MAN_HIST),
        history_files=len(list(RAW_HIST.glob('*.json')))), ensure_ascii=False),))
    db.execute("insert into meta values('normalization',?)", (NORMALIZATION_VERSION + ' 映射表SHA=' + MAP_SHA,))
    db.commit()
    print('\n写出 %s：docs %d，segs %d，%.1fMB，用时 %.0fs' % (
        db_path, doc_id, seg_id, db_path.stat().st_size / 1e6, time.time() - t0))
    print('来源组（前 12）：', ', '.join('%s/%s=%d' % (d, f, n) for (d, f), n in fams.most_common(12)))
    (OUT / 'build_report.json').write_text(json.dumps(dict(
        docs=doc_id, segs=seg_id, families={f'{d}/{f}': n for (d, f), n in fams.items()},
        db_bytes=db_path.stat().st_size, db_sha=sha(db_path), seconds=round(time.time() - t0, 1),
        normalization_version=NORMALIZATION_VERSION, inputs=dict(modern_sha=sha(MODERN), cedict_sha=sha(CEDICT))),
        ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
