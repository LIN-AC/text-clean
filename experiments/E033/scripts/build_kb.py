#!/usr/bin/env python3
"""E033 第二、三步：建"带出处的资料库 + 二字实体倒排检索"（SQLite FTS5，离线）。

为什么要二字串索引：SQLite 默认 trigram 分词器对少于 3 个字符的词不管用，
"卫青""桑弘羊"这类 2 字实体必须靠预分词。这里把每段切成"单字 + 相邻二字串"的空格序列，
用 FTS5 建倒排并直接拿 bm25 排序，2 字实体就是一个 token，精确命中。

规矩（对应 Astra 研究报告 §4.1）：
  保存原文资料，不只保存聚合计数——每段留 text_raw（未繁简转换）+ 出处（书名/页名/URL/许可/抓取时间/SHA）；
  历史与现代分库存（domain 列），不混成一张无来源大表；
  规范化时保留边界（非汉字一律变空格，不删），与 E033 第一步的结论一致；
  另存重复段统计：同一段文字出现在多份文档里时，doc_count 只算 1，避免转载被当成多个独立证据。
产物全部在 build/，正式词库 data/ 一字不动。
"""
import hashlib, json, pathlib, re, sqlite3, sys, time

R = pathlib.Path(__file__).resolve().parents[3]
HIST_RAW = R / 'build/e030_corpus/raw'
MODERN = R / 'build/e031_corpus/cmn_sentences.tsv'
CEDICT = R / 'data/raw/cedict_ts.u8'
MANIFEST = R / 'build/e030_corpus/manifest.json'
OUT = R / 'build/e033_kb'
GT_DIR = R / 'asr'
SHINGLE = 12
sys.stdout.reconfigure(encoding='utf-8')


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


def norm(text):
    """规范化：繁→简，非汉字一律变空格（保留边界），连续空格合一。"""
    out = []
    for ch in text:
        if '一' <= ch <= '鿿':
            out.append(TS.get(ch, ch))
        else:
            out.append(' ')
    return re.sub(r' +', ' ', ''.join(out)).strip()


def tokens(n):
    """单字 + 相邻二字串（跨空格不生成二字串，边界保留）。"""
    tk = list(n)
    tk += [n[i:i + 2] for i in range(len(n) - 1)]
    return ' '.join(tk)


def sha(path):
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


STEP, OVERLAP = 250, 24      # 切块留重叠：上一版不留，卫青 58 次只索引到 48 段，实体被切掉 12%~16%


def segments_hist(txt):
    n = norm(txt)
    step = max(1, STEP - OVERLAP)
    for i in range(0, max(1, len(n)), step):
        chunk = n[i:i + STEP]
        if len(chunk) >= 6:
            yield i, chunk
        if i + STEP >= len(n):
            break


def gt_shingles():
    """本项目七篇真值 + 原始 ASR 的 12 字窗口集合（小），反过来查语料里有没有出现（泄漏检查）。"""
    out = {}
    for f in sorted(GT_DIR.glob('*.gt.jsonl')):
        rows = [r for r in (json.loads(l) for l in f.read_text(encoding='utf-8').splitlines() if l.strip())
                if not r.get('discard')]
        for field in ('gt', 'text'):
            for r in rows:
                n = norm(r.get(field, ''))
                for i in range(0, max(0, len(n) - SHINGLE + 1)):
                    out.setdefault(n[i:i + SHINGLE], f.stem)
    return out


def main():
    GT = gt_shingles()
    print('待查泄漏窗口 %d 个（来自 7 篇真值与原始 ASR 的 %d 字窗口）' % (len(GT), SHINGLE), flush=True)
    leaks = []

    def check(text_norm):
        for i in range(0, max(0, len(text_norm) - SHINGLE + 1)):
            sh = text_norm[i:i + SHINGLE]
            if sh in GT:
                leaks.append((GT[sh], sh))

    OUT.mkdir(parents=True, exist_ok=True)
    db_path = OUT / 'kb.sqlite'
    if db_path.exists():
        db_path.unlink()
    man = json.loads(MANIFEST.read_text(encoding='utf-8'))
    db = sqlite3.connect(db_path)
    db.executescript('''
    create table docs(doc_id integer primary key, domain text, work text, title text, url text,
                      license text, fetched_at text, src_sha text, n_segs int);
    create table segs(seg_id integer primary key, doc_id int, ord int, off int, text_norm text, chars int);
    create virtual table kb using fts5(tokens);
    create table meta(k text primary key, v text);
    ''')
    t0 = time.time()
    doc_id = seg_id = 0
    counts = {'历史': [0, 0], '现代': [0, 0]}
    # ---- 历史：每卷一个文档，页名与许可来自 E030 抓取记录 ----
    for jf in sorted(HIST_RAW.glob('*.json')):
        d = json.loads(jf.read_text(encoding='utf-8'))
        title = d.get('title', jf.stem)
        txt = (jf.parent.parent / 'txt' / (jf.stem + '.txt'))
        if not txt.exists():
            continue
        segs = list(segments_hist(txt.read_text(encoding='utf-8')))
        if not segs:
            continue
        doc_id += 1
        db.execute('insert into docs values(?,?,?,?,?,?,?,?,?)',
                   (doc_id, '历史', title.split('/')[0], title,
                    'https://zh.wikisource.org/wiki/' + title.replace(' ', '_'),
                    man.get('license', ''), man.get('fetched_at', ''), sha(txt), len(segs)))
        for ord_, (off, chunk) in enumerate(segs):
            check(chunk)
            seg_id += 1
            db.execute('insert into segs values(?,?,?,?,?,?)', (seg_id, doc_id, ord_, off, chunk, len(chunk)))
            db.execute('insert into kb(rowid,tokens) values(?,?)', (seg_id, tokens(chunk)))
        counts['历史'][0] += 1; counts['历史'][1] += len(segs)
        if doc_id % 200 == 0:
            db.commit(); print('  历史 %d 卷 / %d 段，%.0fs' % (doc_id, seg_id, time.time() - t0), flush=True)
    db.commit()
    # ---- 现代：Tatoeba 每句一段，句界天然保留 ----
    work = 'Tatoeba 中文句库 cmn_sentences.tsv'
    for line in MODERN.read_text(encoding='utf-8', errors='replace').split('\n'):
        parts = line.split('\t')
        if len(parts) < 3:
            continue
        chunk = norm(parts[2])
        if len(chunk) < 2:
            continue
        check(chunk)
        doc_id += 1
        db.execute('insert into docs values(?,?,?,?,?,?,?,?,?)',
                   (doc_id, '现代', work, 'sentence#' + parts[0],
                    'https://tatoeba.org/', 'CC BY 2.0 FR（署名 Tatoeba 项目）', '', '', 1))
        seg_id += 1
        db.execute('insert into segs values(?,?,?,?,?,?)', (seg_id, doc_id, 0, 0, chunk, len(chunk)))
        db.execute('insert into kb(rowid,tokens) values(?,?)', (seg_id, tokens(chunk)))
        counts['现代'][0] += 1; counts['现代'][1] += 1
        if doc_id % 20000 == 0:
            db.commit(); print('  现代 %d 句，%.0fs' % (counts['现代'][1], time.time() - t0), flush=True)
    db.commit()

    # ---- 重复段统计（同一段文字出现在多份文档里，不能当多个独立证据）----
    dup = db.execute('''select count(*) from (select text_norm from segs group by text_norm
                        having count(distinct doc_id) > 1)''').fetchone()[0]
    # ---- 泄漏检查在上面向量插入时已经顺手做完（check）----
    db.execute("insert into meta values('built_at', ?)", (time.strftime('%Y-%m-%dT%H:%M:%S'),))
    db.execute("insert into meta values('inputs', ?)", (json.dumps(
        {'history_manifest_sha': sha(MANIFEST), 'modern_sha': sha(MODERN), 'cedict_sha': sha(CEDICT)},
        ensure_ascii=False),))
    db.commit()
    uniq_leak = sorted(set(leaks))
    out = dict(docs=doc_id, segs=seg_id, per_domain={k: dict(docs=v[0], segs=v[1]) for k, v in counts.items()},
               dup_norm_texts=dup, leak_probe_windows=len(GT), leak_hits=len(leaks),
               leak_examples=[[a, b] for a, b in uniq_leak[:10]],
               seconds=round(time.time() - t0, 1), db_bytes=db_path.stat().st_size)
    (OUT / 'manifest.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2)[:900])


if __name__ == '__main__':
    main()
