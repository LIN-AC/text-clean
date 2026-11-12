#!/usr/bin/env python3
"""交付配套：§2 要求的读音缺口统计，以及"实体异写建议表"（按规范的列格式，一律标 pending）。

只读正式词库与语料原料，不启用任何候选、不改 data/。
异写证据改用 E036 原料库重算：按 cluster（去重文档簇）计数的，同一转载链最多贡献一次。
"""
import collections, json, pathlib, re, sqlite3, sys

R = pathlib.Path(__file__).resolve().parents[3]
DATA = R / 'data'
DB = R / 'build/e036_corpus/corpus.sqlite'
OUT = R / 'build/e036_corpus'
sys.stdout.reconfigure(encoding='utf-8')
SYL = re.compile(r'[a-zv:]+[0-5]')


def tsv(path):
    return list(csv_rows(path))


def csv_rows(path):
    import csv
    with open(path, encoding='utf-8') as f:
        for row in csv.DictReader((l for l in f if not l.startswith('#')), delimiter='\t'):
            yield row


def readings_of(s, n):
    out = []
    for form in (s or '').split('|'):
        parts = SYL.findall(form)
        if len(parts) == n and ''.join(parts) == form:
            out.append(parts)
    return out


def main():
    # ---------- 通用字符表 V（现代、出现≥2 次），与 §3 的构建器规则一致 ----------
    db = sqlite3.connect(DB)
    modern_chars = collections.Counter()
    for (tn,) in db.execute("select text_norm from docs where domain='现代'"):
        for c in re.findall(r'[一-鿿]', tn):
            modern_chars[c] += 1
    V = {c for c, n in modern_chars.items() if n >= 2}

    # ---------- §2 读音缺口 ----------
    char_read = {r['char']: r['readings'].split('|') for r in tsv(DATA / 'pronunciation/pronunciation_char.tsv')}
    entries = list(tsv(DATA / 'pronunciation/pronunciation.tsv'))
    cand = [r for r in tsv(DATA / 'correction/candidates.tsv') if r['status'] == '1']
    targets = sorted({r['canonical'] for r in cand})
    gaps = dict(目标词数=len(targets), 缺词级读音=[], 音节数不等于字数=[], 含未知调=[], 含V外字=[], 超长词=[])
    multi = 0
    for t in targets:
        row = next((r for r in cand if r['canonical'] == t), None)
        s = row['pinyin'] if row else ''
        ps = readings_of(s, len(t))
        if not s or s == '-':
            gaps['缺词级读音'].append(t)
        elif not ps:
            gaps['音节数不等于字数'].append(t)
        if any(x.endswith(('0', '5')) for form in (s or '').split('|') for x in SYL.findall(form)):
            gaps['含未知调'].append(t)
        if set(t) - V:
            gaps['含V外字'].append(t + '(' + ''.join(sorted(set(t) - V)) + ')')
        if len(t) > 6:
            gaps['超长词'].append(t)
        if len(readings_of(s, len(t))) > 1:
            multi += 1
    comp = [r for r in entries if 2 <= len(r['entry']) <= 6 and re.fullmatch(r'[一-鿿]+', r['entry'])]
    print('=== §2 竞争词与读音缺口（只报数，不启用任何词）===')
    print('  竞争词池：读音表内 2~6 字汉字条目 %d 条；启用目标词 %d 个，其中多音（≥2 个完整变体）%d 个' % (len(comp), len(targets), multi))
    for k in ('缺词级读音', '音节数不等于字数', '含未知调', '含V外字', '超长词'):
        print('  %-10s %3d 个%s' % (k, len(gaps[k]), '：' + '、'.join(gaps[k][:8]) if gaps[k] else ''))
    print('  通用字符表 V：现代字种 %d，进 V（≥2 次）%d；若构建器把 min_count 降到 1，V 变 %d' % (
        len(modern_chars), len(V), len(modern_chars)))

    # ---------- §2 实体异写建议（按规范列）----------
    hist = [(cid, fam, url, tn) for cid, fam, url, tn in db.execute(
        "select cluster_id, source_family, url, text_norm from docs where domain='历史'")]

    def doc_hits(form):
        q = ' '.join(form)
        out = {}
        for cid, fam, url, tn in hist:
            if form in tn.replace(' ', '') or q in tn:
                out.setdefault(cid, (fam, url))
        return out

    import itertools
    sugg, seen = [], set()
    for t in targets:
        if len(t) < 3:
            continue
        dt = doc_hits(t)
        if not dt:
            continue
        for k in range(2, len(t)):
            for combo in itertools.combinations(range(len(t)), k):
                v = ''.join(t[i] for i in combo)
                if (t, v) in seen:
                    continue
                dv = doc_hits(v)
                if not dv or len(dv) > 2 * len(dt):
                    continue
                same_work = {x[0] for x in dv.values()} & {x[0] for x in dt.values()}
                if not same_work:
                    continue
                seen.add((t, v))
                sugg.append(dict(entity_id='ent:' + t, form=v, docs_with_form=len(dv), docs_with_target=len(dt),
                                 docs_shared_cluster=len(set(dv) & set(dt)), works='、'.join(sorted(same_work)),
                                 example_url=sorted(dv.values())[0][1], scope='历史原文',
                                 ambiguous='是' if len(dv) > len(dt) else '否',
                                 evidence='同书共现 + 保序子序列 + 稀有度比例≤2', human_state='pending'))
    out = OUT / 'alias_suggestions.tsv'
    with out.open('w', encoding='utf-8', newline='\n') as f:
        f.write('# E036 实体异写/简称建议：全部为自动派生建议，人工状态一律 pending，不宣称同义，不进正式词库\n')
        cols = ['entity_id', 'form', 'docs_with_form', 'docs_with_target', 'docs_shared_cluster',
                'works', 'example_url', 'scope', 'ambiguous', 'evidence', 'human_state']
        f.write('\t'.join(cols) + '\n')
        for r in sugg:
            f.write('\t'.join(str(r[c]) for c in cols) + '\n')
    amb = sum(1 for r in sugg if r['ambiguous'] == '是')
    print('\n=== §2 实体异写建议表（新原料重算）===')
    print('  建议 %d 条，涉及目标词 %d 个，标"可能歧义" %d 条；文件 %s' % (len(sugg), len({r['entity_id'] for r in sugg}), amb, out))
    for r in sugg[:8]:
        print('   %s ← %s ｜同簇共现 %d ｜书 %s ｜歧义 %s' % (
            r['entity_id'][4:], r['form'], r['docs_shared_cluster'], r['works'], r['ambiguous']))
    (OUT / 'pron_gaps.json').write_text(json.dumps(
        dict(gaps={k: v for k, v in gaps.items()}, V_size=len(V), modern_chars=len(modern_chars),
             competitor_pool=len(comp), multi_reading_targets=multi,
             alias_suggestions=len(sugg), alias_ambiguous=amb), ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
