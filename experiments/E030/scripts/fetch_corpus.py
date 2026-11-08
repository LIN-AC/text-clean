#!/usr/bin/env python3
"""E030 语料抓取：从维基文库下载公开历史文本（二十四史类），缓存到 build/（不入库）。

许可记录（写进实验报告）：
  * 文本本身为公有领域古籍（四庫全書本等）。
  * 页面转录由 Wikisource 提供，按其条款以 CC BY-SA 4.0 / GFDL 公开，使用时署名来源 URL。
  * 不抓取版权未明的现代整理本；不抓取七篇真值与任何本项目真值。
"""
import hashlib, json, pathlib, re, subprocess, sys, time

OUT = pathlib.Path('build/e030_corpus')
RAW = OUT / 'raw'
TXT = OUT / 'txt'
for d in (OUT, RAW, TXT):
    d.mkdir(parents=True, exist_ok=True)
sys.stdout.reconfigure(encoding='utf-8')

WORKS = {'明史': '明史', '汉书': '漢書', '后汉书': '後漢書', '史记集解': '史記集解'}
BATCH = 20        # 小批量，避免触发限流
UA = 'text_clean-e030/1.0 (research corpus, non-commercial)'


def api(params):
    q = urllib_parse(params)
    # 429 限流要长退避，快速重试只会一直被拒
    for attempt, wait in enumerate((0, 20, 60, 120, 240)):
        if wait:
            print('  失败或限流，等待 %ds 后重试' % wait, flush=True)
            time.sleep(wait)
        r = subprocess.run(['curl', '-s', '--max-time', '90', '-A', UA,
                            '-w', '\n@@%{http_code}',
                            'https://zh.wikisource.org/w/api.php?' + q], capture_output=True)
        raw = r.stdout.decode('utf-8', 'replace')
        body, _, code = raw.rpartition('\n@@')
        if code.strip() in ('429', '403', '503'):
            continue
        try:
            return json.loads(body)
        except Exception:
            continue
    return {}


def urllib_parse(params):
    import urllib.parse
    return urllib.parse.urlencode(params)


def clean(wikitext):
    t = re.sub(r'<ref[^>]*>.*?</ref>', '', wikitext, flags=re.S)
    t = re.sub(r'<ref[^/>]*\s*/>', '', t)
    t = re.sub(r'<[^>]+>', '', t)
    t = re.sub(r'\{\{[^{}]*\}\}', '', t)
    t = re.sub(r"'''?", '', t)
    t = re.sub(r'\[\[([^\]|]*\|)?([^]]*)\]\]', r'\2', t)
    t = re.sub(r'^\s*[!#|;:].*$', '', t, flags=re.M)
    han = ''.join(ch for ch in t if '一' <= ch <= '鿿')
    return han


def titles_of(name, prefix):
    """列出一部书的分卷页（跳过"全覽"这类汇总页）。"""
    found, cont = [], None
    while True:
        d = api({'action': 'query', 'list': 'allpages', 'apprefix': prefix, 'aplimit': '500',
                 'format': 'json', 'formatversion': '2'} | ({'apcontinue': cont} if cont else {}))
        found += [x['title'] for x in d.get('query', {}).get('allpages', []) if '/卷' in x['title']]
        cont = d.get('continue', {}).get('apcontinue')
        if not cont:
            return found


def fetch_batch(titles):
    """一个请求取回最多 BATCH 页正文，写缓存并返回取到的页数与新汉字总数。"""
    d = api({'action': 'query', 'prop': 'revisions', 'rvprop': 'content', 'rvslots': 'main',
             'format': 'json', 'formatversion': '2', 'titles': '|'.join(titles)})
    got = chars = 0
    for page in d.get('query', {}).get('pages', []):
        title = page.get('title', '')
        if 'revisions' not in page or not title:
            continue
        content = page['revisions'][0]['slots']['main']['content']
        s = slug(title)
        (RAW / (s + '.json')).write_text(json.dumps({'title': title, 'content': content},
                                                   ensure_ascii=False), encoding='utf-8')
        text = clean(content)
        (TXT / (s + '.txt')).write_text(text, encoding='utf-8')
        chars += len(text)
        got += 1
    return got, chars


def slug(title):
    return re.sub(r'[^0-9A-Za-z一-鿿]+', '_', title)[:120]


todo = []
for name, prefix in WORKS.items():
    titles = titles_of(name, prefix)
    new = [t for t in titles if not (TXT / (slug(t) + '.txt')).exists()]
    print('%s: 分卷页 %d，待抓 %d' % (name, len(titles), len(new)), flush=True)
    todo += new
print('合计待抓 %d 页，已缓存跳过若干' % len(todo), flush=True)

chars = pages = 0
for i in range(0, len(todo), BATCH):
    g, c = fetch_batch(todo[i:i + BATCH])
    pages += g
    chars += c
    print('%d/%d 页 本轮 %d 页 累计汉字=%d' % (min(i + BATCH, len(todo)), len(todo), g, chars), flush=True)
    time.sleep(3.0)
report = {'fetched_pages': pages}

# 合并 + 指纹
merged = OUT / 'history_raw_han.txt'
with merged.open('w', encoding='utf-8', newline='\n') as f:
    for p in sorted(TXT.glob('*.txt')):
        f.write(p.read_text(encoding='utf-8'))
        f.write('\n')
raw = merged.read_bytes()
meta = dict(work=report, files=len(list(TXT.glob('*.txt'))), bytes=len(raw),
            han=len(re.findall('[一-鿿]', raw.decode('utf-8', 'replace'))),
            sha256=hashlib.sha256(raw).hexdigest(), source='zh.wikisource.org',
            license='古籍本文公有领域；转录页面 CC BY-SA 4.0 / GFDL（署名 Wikisource 及来源页）',
            fetched_at=time.strftime('%Y-%m-%dT%H:%M:%S'))
(OUT / 'manifest.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(meta, ensure_ascii=False, indent=2))
