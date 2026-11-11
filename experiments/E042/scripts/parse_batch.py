#!/usr/bin/env python3
"""E042：把已下载完成的中文 Wikimedia dump 逐个解析成文档 JSONL，并登记 dump 的 SHA256。

只处理带 .done 标记（大小与 Content-Length 一致）的文件；已解析过的项目跳过。
每个项目是独立来源组（不同站点、不同编辑社区），逐条记录 URL、修订时间戳与 wikitext SHA256，
许可按 Wikimedia 文字项目条款记 CC BY-SA 4.0（早期贡献另带 GFDL）。
"""
import hashlib, json, pathlib, subprocess, sys, time

R = pathlib.Path(__file__).resolve().parents[3]
sys.stdout.reconfigure(encoding='utf-8')
RAW = R / 'build/e042_corpus/raw'
JSONL = R / 'build/e042_corpus/jsonl'
PARSER = R / 'experiments/E042/scripts/parse_wm.py'
LIC = 'CC BY-SA 4.0（Wikimedia 中文文字项目；早期贡献另带 GFDL；逐条记录页面 URL 与修订时间戳）'
# family, dump 文件, 项目名, 站点, 书名/栏目, register
CONF = [
    ('zhwikiquote', 'zhwikiquote-latest-pages-articles.xml.bz2', 'zhwikiquote', 'zh.wikiquote.org', '中文维基语录', '语录/发言摘录'),
    ('zhwikivoyage', 'zhwikivoyage-latest-pages-articles.xml.bz2', 'zhwikivoyage', 'zh.wikivoyage.org', '中文维基导游', '旅行指南'),
    ('zhwikiversity', 'zhwikiversity-latest-pages-articles.xml.bz2', 'zhwikiversity', 'zh.wikiversity.org', '中文维基大学', '教材/讲义'),
    ('zhwikibooks', 'zhwikibooks-latest-pages-articles.xml.bz2', 'zhwikibooks', 'zh.wikibooks.org', '中文维基教科书', '教程/手册'),
    ('zhwikinews', 'zhwikinews-latest-pages-articles.xml.bz2', 'zhwikinews', 'zh.wikinews.org', '中文维基新闻', '新闻报道'),
    ('zhwikipedia', 'zhwiki-latest-pages-articles.xml.bz2', 'zhwiki', 'zh.wikipedia.org', '中文维基百科', '百科说明文'),
]

if __name__ == '__main__':
    JSONL.mkdir(parents=True, exist_ok=True)
    man = R / 'build/e042_corpus/dump_manifest.json'
    entries = json.loads(man.read_text(encoding='utf-8')) if man.exists() else {}
    for fam, name, project, site, work, register in CONF:
        p = RAW / name
        out = JSONL / ('%s.jsonl' % fam)
        if not (RAW / (name + '.done')).exists() or not p.exists():
            print('等待下载', name, flush=True)
            continue
        if out.exists() and out.stat().st_size > 0:
            print('已解析', fam, out.stat().st_size, '字节', flush=True)
            continue
        dig = dict(bytes=p.stat().st_size, sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                   url='https://dumps.wikimedia.org/%s/latest/%s' % (project, name),
                   recorded_at=time.strftime('%Y-%m-%dT%H:%M:%S'))
        entries[name] = dig
        man.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')
        print('解析', fam, flush=True)
        subprocess.run([sys.executable, str(PARSER), '--dump', str(p), '--project', project, '--site', site,
                        '--family', fam, '--work', work, '--register', register, '--license', LIC,
                        '--out', str(out)], check=False)
    print('PARSE BATCH FINISHED', flush=True)
