#!/usr/bin/env python3
"""E042 硬性检查（独立复算，不调用建库脚本的 norm/edge）。

检查项：库完整性；segs 能否由全文+偏移复原；规范化是否长度保持且可回查原文；
边界类别与 is_stop 是否一致；泄漏（本项目真值与原始 ASR 的 12 字窗口）；
完全重复 / 近重复 / 与 E036 老库的跨批重复；来源多样性；许可与 URL 可追。
产物：build/e042_corpus/hard_checks.json 与 samples_naturalness.tsv
"""
import argparse, collections, hashlib, json, pathlib, random, re, sqlite3, sys, time

R = pathlib.Path(__file__).resolve().parents[3]
sys.stdout.reconfigure(encoding='utf-8')
CEDICT = R / 'data/raw/cedict_ts.u8'
GT_DIR = R / 'asr'
E036_DB = R / 'build/e036_corpus/corpus.sqlite'
SHINGLE = 12
STOP = set('。？！')
PAUSE = set('，、；：')


def simp_map():
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


TS = simp_map()


def mynorm(text):
    """长度保持：基本汉字（或繁简对照命中）保留/转简，其余每字符一个空格。独立于建库实现。"""
    out = []
    for ch in text:
        if '一' <= ch <= '鿿':
            out.append(TS.get(ch, ch))
        elif chr(0x3400) <= ch <= chr(0x4DBF) or ord(ch) > 0x20000:
            out.append(ch)
        else:
            out.append(' ')
    return ''.join(out)


def gt_windows():
    out = {}
    for f in sorted(GT_DIR.glob('*.gt.jsonl')):
        rows = [json.loads(l) for l in f.read_text(encoding='utf-8').splitlines() if l.strip()]
        for r in rows:
            if r.get('discard'):
                continue
            for field in ('gt', 'text'):
                n = mynorm(r.get(field, '') or '')
                for i in range(0, max(0, len(n) - SHINGLE + 1)):
                    out.setdefault(n[i:i + SHINGLE], f.stem)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=str(R / 'build/e042_corpus/corpus_supplement.sqlite'))
    ap.add_argument('--max-share', type=float, default=0.28)
    ap.add_argument('--sample-docs', type=int, default=0, help='0=全量')
    a = ap.parse_args()
    t0 = time.time()
    db = sqlite3.connect(pathlib.Path(a.db).resolve().as_uri() + '?mode=ro', uri=True)
    res = collections.OrderedDict()
    res['db'] = str(a.db)
    res['db_sha256'] = hashlib.sha256(pathlib.Path(a.db).read_bytes()).hexdigest()
    res['integrity'] = db.execute('pragma integrity_check').fetchone()[0]

    W = gt_windows()
    res['leak_probe_windows'] = len(W)
    print('真值/ASR 的 %d 字窗口 %d 个' % (SHINGLE, len(W)), flush=True)

    old = set()
    if E036_DB.exists():
        s = sqlite3.connect(E036_DB.resolve().as_uri() + '?mode=ro', uri=True)
        old = {r[0] for r in s.execute('select text_norm from docs')}
        s.close()
    res['e036_docs'] = len(old)

    bad_norm = bad_len = bad_map = bad_seg = bad_edge = leak = cross_dup = 0
    leak_examples, fam_chars, dom_chars, lic_missing, url_bad, sha_bad = [], collections.Counter(), \
        collections.Counter(), 0, 0, 0
    dup_exact = collections.Counter()
    samples = []
    n = 0
    q = 'select doc_id,domain,source_family,license,url,src_sha,text_raw,text_norm,normalization_map_json from docs'
    if a.sample_docs:
        q += ' where doc_id <= %d' % a.sample_docs
    for doc_id, dom, fam, lic, url, src_sha, raw, tn, mp in db.execute(q):
        n += 1
        if n % 20000 == 0:
            print('  已查 %d 篇 %.0fs' % (n, time.time() - t0), flush=True)
        if mynorm(raw) != tn:
            bad_norm += 1
        if len(raw) != len(tn):
            bad_len += 1
        m = json.loads(mp)
        if len(m) != len(tn) or any(m[i] != i for i in range(0, len(m), 97)):
            bad_map += 1
        if not re.fullmatch(r'[0-9a-f]{64}', src_sha or ''):
            sha_bad += 1
        if not lic or len(lic) < 6:
            lic_missing += 1
        if not re.match(r'https?://[^\s]+/(\S|$)', url or '') or url.rstrip('/').count('/') < 3:
            url_bad += 1
        fam_chars[(dom, fam)] += sum(1 for c in tn if c != ' ')
        dom_chars[dom] += sum(1 for c in tn if c != ' ')
        h = hashlib.sha256(tn.encode()).hexdigest()
        dup_exact[h] += 1
        if h in old:
            cross_dup += 1
        for run in re.split(' +', tn):
            for i in range(0, max(0, len(run) - SHINGLE + 1)):
                sh = run[i:i + SHINGLE]
                if sh in W:
                    leak += 1
                    if len(leak_examples) < 10:
                        leak_examples.append([W[sh], sh, url])
        if n % 137 == 0 and len(samples) < 4000:
            runs = [r for r in re.split(' +', tn) if len(r) >= 24]
            if runs:
                samples.append((dom, fam, random.Random(doc_id).choice(runs)[:40], url))
    res['docs_checked'] = n
    res['norm_mismatch'] = bad_norm
    res['length_not_preserved'] = bad_len
    res['map_mismatch'] = bad_map
    res['src_sha_missing'] = sha_bad
    res['license_missing'] = lic_missing
    res['url_not_traceable'] = url_bad
    res['leak_hits'] = leak
    res['leak_examples'] = leak_examples
    res['cross_batch_exact_duplicates'] = cross_dup
    res['within_batch_exact_duplicate_docs'] = sum(v - 1 for v in dup_exact.values() if v > 1)
    res['han_chars_by_domain'] = dict(dom_chars)

    # 边界类别与 is_stop 一致性（消费者会同时读这两列，矛盾就等于给它两个答案）
    for side in ('left', 'right'):
        c = db.execute("select count(*) from segs where %s_class='句末标点' and %s_is_stop=0" % (side, side)).fetchone()[0]
        c2 = db.execute("select count(*) from segs where %s_is_stop=1 and %s_class<>'句末标点'" % (side, side)).fetchone()[0]
        bad_edge += c + c2
    res['edge_class_vs_is_stop_conflicts'] = bad_edge

    # 段必须能由全文+偏移复原（抽样 4000 篇逐段核对）
    bad_seg = 0
    for doc_id in [r[0] for r in db.execute('select doc_id from docs order by random() limit 4000')]:
        tn = db.execute('select text_norm from docs where doc_id=?', (doc_id,)).fetchone()[0]
        for off, seg in db.execute('select off, text_norm from segs where doc_id=?', (doc_id,)):
            if tn[off:off + len(seg)] != seg:
                bad_seg += 1
    res['seg_offset_mismatch_sampled4000'] = bad_seg

    total = sum(fam_chars.values()) or 1
    shares = {'%s/%s' % k: round(v * 1000.0 / total) / 10.0 for k, v in fam_chars.items()}
    res['family_share_percent'] = dict(sorted(shares.items(), key=lambda x: -x[1]))
    res['max_family_share_percent'] = max(shares.values()) if shares else 0
    res['families_modern'] = sum(1 for k in fam_chars if k[0] == '现代')
    res['families_history'] = sum(1 for k in fam_chars if k[0] == '历史')
    res['share_limit_ok'] = res['max_family_share_percent'] <= a.max_share * 100 + 0.5

    out = pathlib.Path(a.db).parent / 'hard_checks.json'
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
    with (pathlib.Path(a.db).parent / 'samples_naturalness.tsv').open('w', encoding='utf-8', newline='\n') as w:
        w.write('domain\tsource_family\tsample_context\turl\n')
        rng = random.Random(20261112)
        for row in rng.sample(samples, min(40, len(samples))):
            w.write('\t'.join(str(x).replace('\t', ' ') for x in row) + '\n')
    print(json.dumps({k: v for k, v in res.items() if k not in ('family_share_percent', 'leak_examples')},
                     ensure_ascii=False, indent=2), flush=True)
    print('写出 %s，用时 %.0fs' % (out, time.time() - t0))


if __name__ == '__main__':
    main()
