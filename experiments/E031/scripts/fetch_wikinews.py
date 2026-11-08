#!/usr/bin/env python3
"""E031 现代语料抓取：中文维基新闻（zh.wikinews.org，CC BY 2.5）——现代书面汉语。

用途：给上下文评分找一个句式与本任务字幕接近的语料。E030 的邻接统计来自文言语料，
现代口语并不适用。缓存放 build/（不入库），批量 20 篇/请求、批间 2s、429 长退避。
只保留正文汉字数 ≥ 200 的页面（符号标题、重定向、删除页会被跳过）。
"""
import hashlib, json, pathlib, re, subprocess, sys, time
import urllib.parse

OUT = pathlib.Path('build/e031_corpus/wikinews')
OUT.mkdir(parents=True, exist_ok=True)
sys.stdout.reconfigure(encoding='utf-8')
API = 'https://zh.wikinews.org/w/api.php'
UA = 'text_clean-e031/1.0 (research context corpus, non-commercial)'
BATCH = 20
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 0


def call(params):
    url = API + '?' + urllib.parse.urlencode(params)
    for wait in (0, 15, 45, 90):
        if wait:
            print('  失败/限流，等 %ds 重试' % wait, flush=True)
            time.sleep(wait)
        r = subprocess.run(['curl', '-s', '--max-time', '90', '-A', UA,
                            '-w', chr(10) + '@@%{http_code}', url], capture_output=True)
        raw = r.stdout.decode('utf-8', 'replace')
        body, _, code = raw.rpartition(chr(10) + '@@')
        if code.strip() in ('429', '403', '503'):
            continue
        try:
            return json.loads(body)
        except Exception:
            continue
    return {}


titles, cont = [], None
while True:
    p = {'action': 'query', 'list': 'allpages', 'apnamespace': '0', 'aplimit': '500',
         'format': 'json', 'formatversion': '2'}
    if cont:
        p['apcontinue'] = cont
    d = call(p)
    titles += [x['title'] for x in d.get('query', {}).get('allpages', [])]
    cont = d.get('continue', {}).get('apcontinue')
    if not cont or (LIMIT and len(titles) >= LIMIT):
        break
titles = titles[:LIMIT] if LIMIT else titles
print('候选标题 %d 个' % len(titles), flush=True)

chars = kept = skipped = 0
for i in range(0, len(titles), BATCH):
    chunk = titles[i:i + BATCH]
    d = call({'action': 'query', 'prop': 'extracts', 'explaintext': '1', 'exlimit': str(BATCH),
              'format': 'json', 'formatversion': '2', 'titles': '|'.join(chunk)})
    for page in d.get('query', {}).get('pages', []):
        text = page.get('extract') or ''
        han = len(re.findall('[一-鿿]', text))
        if han < 200:
            skipped += 1
            continue
        name = re.sub(r'[^0-9A-Za-z一-鿿]+', '_', page.get('title', ''))[:120] + '.txt'
        (OUT / name).write_text(re.sub(r'[^一-鿿]', ' ', text), encoding='utf-8')
        chars += han
        kept += 1
    print('%d/%d 标题  保留 %d 篇 累计汉字=%d' % (min(i + BATCH, len(titles)), len(titles), kept, chars), flush=True)
    time.sleep(2.0)

merged = pathlib.Path('build/e031_corpus/wikinews_han.txt')
with merged.open('w', encoding='utf-8', newline='\n') as f:
    for p in sorted(OUT.glob('*.txt')):
        f.write(p.read_text(encoding='utf-8'))
        f.write('\n')
raw = merged.read_bytes()
meta = dict(kept_pages=kept, skipped=skipped, files=len(list(OUT.glob('*.txt'))), bytes=len(raw),
            han=len(re.findall('[一-鿿]', raw.decode('utf-8', 'replace'))),
            sha256=hashlib.sha256(raw).hexdigest(), source='zh.wikinews.org',
            license='CC BY 2.5（Wikinews）；仅用于内部实验，不并入产品词库',
            fetched_at=time.strftime('%Y-%m-%dT%H:%M:%S'))
(pathlib.Path('build/e031_corpus/wikinews_manifest.json')).write_text(
    json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(meta, ensure_ascii=False, indent=2))
