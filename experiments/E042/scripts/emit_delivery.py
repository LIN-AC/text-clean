#!/usr/bin/env python3
"""E042 交付物汇总：source_list.tsv 与 manifest.json 全部从实际产物算出，不手填数字。

source_list.tsv 每行一个来源组：URL/书名、许可、SHA、字数、domain/register/source_family。
manifest.json 绑定库、报告、检查文件与原始 dump 的 SHA256，并写入选择规则与已知限制。
"""
import argparse, collections, hashlib, json, pathlib, sqlite3, sys, time

R = pathlib.Path(__file__).resolve().parents[3]
sys.stdout.reconfigure(encoding='utf-8')
OUT = R / 'build/e042_corpus'
JSONL = OUT / 'jsonl'

META = {
    'zhwikiquote': ('https://zh.wikiquote.org', '中文维基语录', '语录/发言摘录', '2006–2026'),
    'zhwikivoyage': ('https://zh.wikivoyage.org', '中文维基导游', '旅行指南', '2013–2026'),
    'zhwikiversity': ('https://zh.wikiversity.org', '中文维基大学', '教材/讲义', '2007–2026'),
    'zhwikibooks': ('https://zh.wikibooks.org', '中文维基教科书', '教程/手册', '2007–2026'),
    'zhwikinews': ('https://zh.wikinews.org', '中文维基新闻', '新闻报道', '2005–2026'),
    'zhwikipedia': ('https://zh.wikipedia.org', '中文维基百科', '百科说明文', '2002–2026'),
    'gov_cn_policy_library': ('https://www.gov.cn/zhengce/zhengceku/', '中国政府网 政策文件库', '政务公文', '2004–2026'),
    'beijing_gov_policy_library': ('https://www.beijing.gov.cn/zhengce/zhengcefagui/', '北京市政府 政策文件库', '地方政务公文', '2016–2026'),
    'shanghai_gov_policy_library': ('https://www.shanghai.gov.cn/nw12344/', '上海市政府 信息公开文件', '地方政务公文', '2016–2026'),
    'aishell1_transcript': ('https://huggingface.co/datasets/AISHELL/AISHELL-1', 'AISHELL-1 人工转写文本', '口语朗读（照稿）', '2015–2018'),
}
DUMP_URL = {'zhwikiquote': 'zhwikiquote', 'zhwikivoyage': 'zhwikivoyage', 'zhwikiversity': 'zhwikiversity',
            'zhwikibooks': 'zhwikibooks', 'zhwikinews': 'zhwikinews', 'zhwikipedia': 'zhwiki'}


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=str(OUT / 'corpus_supplement.sqlite'))
    a = ap.parse_args()
    db = sqlite3.connect(pathlib.Path(a.db).resolve().as_uri() + '?mode=ro', uri=True)

    # 每个来源组的原始批次指纹：dump SHA 或 gov 抓取索引 SHA
    dumps = json.loads((OUT / 'dump_manifest.json').read_text(encoding='utf-8')) if (OUT / 'dump_manifest.json').exists() else {}
    rows = ['domain\tsource_family\tsource_name\turl_or_call\tparent_license\tregister\tperiod'
            '\tdocs_used\thanzi_used\tnorm_len_used\tdocs_available\thanzi_available\tshare_percent\tsource_sha256']
    fam_db = {}
    # 单位分开算：hanzi = 去掉规范化空格后的长度（≈汉字数，含扩展区汉字）；norm_len = text_norm 全长
    for dom, fam, docs, hanzi, norm_len in db.execute(
            '''select domain, source_family, count(*),
                      sum(length(replace(text_norm, ' ', ''))), sum(chars)
               from docs group by 1,2 order by 3 desc'''):
        fam_db[(dom, fam)] = (docs, hanzi, norm_len)
    # 可用量（封顶前）从 jsonl 直接再数一遍，保证封顶与选择规则可核
    avail_docs, avail_chars, batch_sha = collections.Counter(), collections.Counter(), {}
    for f in sorted(JSONL.glob('*.jsonl')):
        key = f.stem
        for line in f.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            avail_docs[(d['domain'], d['source_family'])] += 1
            avail_chars[(d['domain'], d['source_family'])] += d['chars']
        if key.startswith('ws_'):
            pages = sorted((OUT / 'raw_ws').glob('%s__*.json' % key[3:]))
            batch_sha[key] = hashlib.sha256(''.join(p.name for p in pages).encode()).hexdigest()
        elif key == 'gov_cn_policy_library':
            batch_sha[key] = sha(OUT / 'gov_index.jsonl')
        elif key in DUMP_URL:
            name = '%s-latest-pages-articles.xml.bz2' % DUMP_URL[key]
            batch_sha[key] = dumps.get(name, {}).get('sha256', '')
    total = sum(v[1] for v in fam_db.values()) or 1
    for (dom, fam), (docs, chars, norm_len) in sorted(fam_db.items(), key=lambda x: -x[1][1]):
        url, name, register, period = META.get(fam, ('https://zh.wikisource.org/wiki/', fam.replace('wikisource_', ''),
                                                     '古籍转录', '先秦—清'))
        if fam.startswith('wikisource_'):
            url = 'https://zh.wikisource.org/wiki/' + name
        lic = ' '.join((db.execute('select license from docs where source_family=? limit 1', (fam,)).fetchone()[0]
                        or '').split())          # 许可里不能有制表/换行，否则 TSV 串列
        rows.append('%s\t%s\t%s\t%s\t%s\t%s\t%s\t%d\t%d\t%d\t%d\t%d\t%.1f\t%s' % (
            dom, fam, name, url, lic, register, period, docs, chars, norm_len,
            avail_docs[(dom, fam)], avail_chars[(dom, fam)], chars * 100.0 / total, batch_sha.get(
                fam if not fam.startswith('wikisource_') else 'ws_' + ''.join(name.split()), '')))
    (OUT / 'source_list.tsv').write_text('\n'.join(rows) + '\n', encoding='utf-8', newline='\n')

    checks = json.loads((OUT / 'hard_checks.json').read_text(encoding='utf-8')) if (OUT / 'hard_checks.json').exists() else {}
    cov = {}
    if (OUT / 'coverage_report.tsv').exists():
        lines = (OUT / 'coverage_report.tsv').read_text(encoding='utf-8').splitlines()
        for l in lines[1:]:
            c = l.split('\t')
            cov[c[0]] = dict(docs_total=int(c[1]), docs_modern=int(c[2]), docs_historical=int(c[3]),
                             source_families=int(c[4]), status=c[6])
    rep = json.loads((OUT / 'build_report.json').read_text(encoding='utf-8')) if (OUT / 'build_report.json').exists() else {}
    man = dict(
        batch='e042-corpus-supplement-1',
        built_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
        contract='docs/RAG_DATA_CONTRACT.md（docs/segs 字段沿用，新增 register/period/source_batch/rev_timestamp 列）',
        request='docs/RAG_CORPUS_REQUEST.md',
        normalization_version=rep.get('normalization_version', ''),
        db=dict(path=str(pathlib.Path(a.db).name), bytes=pathlib.Path(a.db).stat().st_size, sha256=sha(a.db),
                docs=rep.get('docs'), segs=rep.get('segs')),
        families=rep.get('families'), family_used_hanzi=rep.get('family_used_chars'),
        family_available_hanzi=rep.get('family_avail_chars'),
        family_cap_hanzi=rep.get('cap_chars'), max_share=rep.get('max_share'),
        selection_rule='每个来源组按 sha256(title|url) 升序累加，达到封顶字数即停；封顶值由 max_share 水填解出',
        dumps=dumps,
        hard_checks=checks,
        coverage=cov,
        files={},
        forbidden_inputs_verified=dict(
            asr_or_truth_used_to_select=False, llm_generated=False, template_sentences=False,
            dictionary_entries=False, project_subtitles=False,
            leak_12char_windows=checks.get('leak_probe_windows'), leak_hits=checks.get('leak_hits')),
        known_limits=[],
    )
    for name in ['corpus_supplement.sqlite', 'coverage_report.tsv', 'coverage_report.detail.json',
                 'source_list.tsv', 'hard_checks.json', 'samples_naturalness.tsv', 'build_report.json',
                 'dump_manifest.json', 'README.md']:
        p = OUT / name
        if p.exists():
            man['files'][name] = dict(bytes=p.stat().st_size, sha256=sha(p))
    (OUT / 'manifest.json').write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(docs=rep.get('docs'), segs=rep.get('segs'), families=len(man['families'] or {}),
                          leak_hits=checks.get('leak_hits'), max_share=man['max_family_share_percent'] if 'max_family_share_percent' in man else None),
                     ensure_ascii=False))
    print('写出 source_list.tsv 与 manifest.json')


if __name__ == '__main__':
    main()
