#!/usr/bin/env python3
"""E042：把中文 Wikimedia 项目 dump 解析成契约文档 JSONL（一个条目=一个文档）。

要点：
  * 只在 `</page>` 边界切分，流式读 bz2，不把整份 XML 装进内存。
  * 清洗只剥标记，不合并换行：原文落在哪一行，规范化后仍是那一段，边界类别才可信。
  * 每个文档记录 wikitext 的 SHA256 与修订时间戳，便于用同一份公开 dump 复核。
"""
import argparse, bz2, collections, hashlib, html, io, json, pathlib, re, sys

sys.stdout.reconfigure(encoding='utf-8')

SKIP_TITLE = re.compile(r'^\s*(讨论|Discussion|Talk|Help|Wikipedia|Project|Template|Category|Portal|Module|MediaWiki|User|用户|模板|分类|主题|模块|帮助|项目|对话|Special|特殊):', re.I)
DISAMBIG = re.compile(r'[（(](消歧|_disambig)', re.I)


def unescape(s):
    return html.unescape(s or '').replace('_</', '</')


def strip_templates(t):
    for _ in range(14):
        n = re.sub(r'\{\{[^{}]*\}\}', '', t, flags=re.S)
        if n == t:
            break
        t = n
    return re.sub(r'\{\{[^{}]*$', '', t, flags=re.S)


def clean(wikitext):
    """剥标记，保留换行结构（表格与列表行整行丢弃，避免把字段名当正文）。"""
    t = wikitext
    t = re.sub(r'<!--.*?-->', '', t, flags=re.S)
    t = re.sub(r'__[A-Z_]+__', '', t)   # __TOC__/__NOTOC__ 等 MediaWiki 魔法词不是正文
    for tag in ('ref', 'noinclude', 'includeonly', 'syntaxhighlight', 'source', 'timeline', 'score', 'math', 'gallery', 'cite'):
        t = re.sub(r'<%s[^>]*>.*?</%s>' % (tag, tag), '', t, flags=re.S | re.I)
    t = re.sub(r'<(ref|ref\s[^/]*?)[^>]*/>', '', t, flags=re.I)
    t = strip_templates(t)
    t = re.sub(r'\[\[(?:File|Image|Category|File|Wikipedia):[^]]*\]\]', '', t, flags=re.I)
    t = re.sub(r'\[\[(?:[^]|]*\|)?([^]]*)\]\]', r'\1', t)
    t = re.sub(r'\[[^\]\s]+\s+([^\]]+)\]', r'\1', t)
    t = re.sub(r'\[https?:[^]]*\]', '', t)
    t = re.sub(r'<br\s*/?>', '\n', t, flags=re.I)
    t = re.sub(r'<[^>]+>', '', t)
    t = re.sub(r"'''?", '', t)
    out = []
    for line in t.split('\n'):
        s = line.strip()
        if not s:
            out.append('')
            continue
        if s[0] in '{|}|!#;:' or s.startswith('|-') or s.startswith('!') or s.startswith(':{|'):
            continue
        s = re.sub(r'^=+\s*(.*?)\s*=+\s*$', r'\1', s)          # 标题行只留文字
        s = re.sub(r'^[*#:;]+\s*', '', s)                        # 列表/缩进符
        s = re.sub(r'[!|]{2}', ' ', s)
        s = re.sub(r'\s+', ' ', s).strip()
        s = re.sub(r'[（(](?:[；;，,、\s]|生卒|－|—)*[)）]', '', s)   # 剥元数据后留下的空括号
        s = re.sub(r'[\[{|}]\]?', '', s)                          # 零星残留的方括号/表格符
        s = s.strip()
        if s:
            out.append(s)
    text = '\n'.join(out)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def pages(path):
    """流式产出完整 <page>…</page> 块。"""
    with bz2.BZ2File(path) as f:
        buf = ''
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            buf += chunk.decode('utf-8', 'replace')
            while True:
                i = buf.find('</page>')
                if i < 0:
                    break
                block, buf = buf[:i + len('</page>')], buf[i + len('</page>'):]
                j = block.find('<page')
                yield block[j:] if j >= 0 else block


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dump', required=True)
    ap.add_argument('--project', required=True, help='zhwiki / zhwikinews / …')
    ap.add_argument('--family', required=True)
    ap.add_argument('--work', required=True)
    ap.add_argument('--register', required=True)
    ap.add_argument('--license', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--site', required=True, help='条目所在站点主机名，如 zh.wikiquote.org')
    ap.add_argument('--max-docs', type=int, default=0)
    ap.add_argument('--keep-mod', type=int, default=1,
                    help='按标题哈希每 N 篇取 1 篇：大 dump 只解析一部分时保持全库均匀，不偏向文件开头的老条目')
    ap.add_argument('--min-han', type=int, default=200)
    a = ap.parse_args()
    site = 'https://%s/wiki/' % a.site
    stats = collections.Counter()
    with io.open(a.out, 'w', encoding='utf-8', newline='\n') as w:
        for block in pages(pathlib.Path(a.dump)):
            stats['pages'] += 1
            m = re.search(r'<title>(.*?)</title>', block, re.S)
            title = unescape(m.group(1)) if m else ''
            if a.keep_mod > 1 and int(hashlib.sha256(title.encode()).hexdigest()[:8], 16) % a.keep_mod:
                stats['skip_stride'] += 1
                continue
            ns = re.search(r'<ns>(\d+)</ns>', block)
            if (ns and ns.group(1) != '0') or SKIP_TITLE.search(title) or DISAMBIG.search(title):
                stats['skip_ns_or_title'] += 1
                continue
            if '<redirect' in block:
                stats['skip_redirect'] += 1
                continue
            tm = re.search(r'<text[^>]*>(.*?)</text>', block, re.S)
            wt = unescape(tm.group(1)) if tm else ''
            if not wt:
                stats['skip_empty'] += 1
                continue
            text = clean(wt)
            han = sum(1 for c in text if '一' <= c <= '鿿')
            if han < a.min_han:
                stats['skip_short'] += 1
                continue
            ts = re.search(r'<timestamp>([^<]+)</timestamp>', block)
            rec = dict(domain='现代', register=a.register, period='2002–2026', work=a.work, title=title,
                       url=site + title.replace(' ', '_'), license=a.license,
                       rev_timestamp=ts.group(1) if ts else '', src_sha=hashlib.sha256(wt.encode()).hexdigest(),
                       chars=han, source_family=a.family, raw=text)
            w.write(json.dumps(rec, ensure_ascii=False) + '\n')
            stats['kept'] += 1
            stats['kept_han'] += han
            if a.max_docs and stats['kept'] >= a.max_docs:
                break
    print(a.family, json.dumps({k: v for k, v in stats.items()}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
