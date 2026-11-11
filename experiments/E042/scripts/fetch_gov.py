#!/usr/bin/env python3
"""E042：抓中国政府网「政策文件库」公开公文，做现代政务语料（一个文件=一个文档）。

许可口径：《著作权法》第五条对法律、法规及国家机关具有立法、行政、司法性质的文件不适用著作权；
本脚本只取 /zhengce/zhengceku/ 的公文原文页，不取带媒体来源署名的新闻稿。逐篇记录 URL、发布机关、
成文/发布时间与抓取时间，正文按 HTML 段落保换行。

两阶段：
  index  列清单（国务院文件按年份分区绕开单查询深度上限；部门文件直接翻页）
  fetch  按 sha256(id) 确定性抽样下载正文（可断点续跑，不重复请求已完成 URL）
"""
import argparse, collections, hashlib, html, io, json, pathlib, random, re, subprocess, sys, time

sys.stdout.reconfigure(encoding='utf-8')
OUT = pathlib.Path('build/e042_corpus')
UA = 'text_clean-e042/1.0 (research corpus, non-commercial)'
API = 'https://sousuo.www.gov.cn/search-gov/data'
LICENSE = ('中国政府网政策文件库公开公文（国务院/部门文件）；'
           '著作权法第五条不适用著作权的立法、行政性质文件；逐篇标注来源 URL 与发布机关')
FAMILY = 'gov_cn_policy_library'
WORK = '中国政府网 政策文件库'


def get(url, binary=False, tries=(0, 5, 15, 40)):
    for w in tries:
        if w:
            time.sleep(w)
        r = subprocess.run(['curl', '-s', '-m', '60', '-A', UA, url], capture_output=True)
        if r.stdout and r.returncode == 0:
            return r.stdout if binary else r.stdout.decode('utf-8', 'replace')
    return ''


def api(t, page, year=''):
    q = '%s?t=%s&q=&n=20&p=%d&sort=pubtime&sortType=1&searchfield=title%s' % (
        API, t, page, ('&pubtimeyear=%s' % year) if year else '')
    raw = get(q)
    if not raw:
        return []
    try:
        sv = json.loads(raw).get('searchVO') or {}
    except Exception:
        return []
    return sv.get('listVO') or [], sv.get('totalpage') or 0


def index():
    seen, rows = set(), []
    for t, label in (('zhengcelibrary_gw', '国务院文件'), ('zhengcelibrary_bm', '部门文件')):
        first, pages = api(t, 1)
        caps = pages * 20 < (json.loads(get('%s?t=%s&q=&n=20&p=1' % (API, t)) or '{}').get(
            'searchVO', {}) or {}).get('totalCount', 0)
        plans = []
        if label == '国务院文件' or caps or pages > 300:
            plans = [(y, None) for y in range(2004, 2027)][::-1]
        else:
            plans = [(None, pages)]
        for year, limit in plans:
            p = 1
            stop = limit if limit else 0
            while True:
                got = api(t, p, str(year) if year else '')
                if not got:
                    break
                items, tp = got
                for it in items:
                    url = it.get('url') or ''
                    if not url.startswith('https://www.gov.cn/zhengce/') or url in seen:
                        continue
                    seen.add(url)
                    rows.append(dict(id=str(it.get('id')), url=url, title=(it.get('title') or '').strip(),
                                     pubtime=it.get('pubtimeStr') or '', org=it.get('puborg') or '',
                                     child=it.get('childtype') or '', kind=label,
                                     year=(str(year) if year else (it.get('pubtimeStr') or '')[:4])))
                p += 1
                if p > tp or (stop and p > stop):
                    break
                if p % 50 == 0:
                    print('  %s %s 第%d页，累计%d' % (label, year or '', p, len(rows)), flush=True)
                time.sleep(0.12)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'gov_index.jsonl').write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n',
                                         encoding='utf-8', newline='\n')
    print('清单 %d 篇，按年：%s' % (len(rows), dict(sorted(collections.Counter(r['year'] for r in rows).items()))), flush=True)


def container(page_html, attr_re):
    """从命中的属性往回找它所属的 <div>，再顺序配对标签找到闭合位置。"""
    m = re.search(attr_re, page_html)
    if not m:
        return ''
    start = page_html.rfind('<div', 0, m.start())
    if start < 0:
        return ''
    depth, i = 0, start
    while True:
        nxt = re.compile(r'<(/?)div\b', re.I).search(page_html, i)
        if not nxt:
            return page_html[start:]
        depth += -1 if nxt.group(1) else 1
        i = nxt.end()
        if depth == 0:
            return page_html[start:nxt.start()]


def extract(page_html):
    """取正文容器，按段落保留换行；返回 (文本, 来源标注)。

    中国政府网用 id="UCAP-CONTENT"/class 含 pages_content，北京市政府用 id="mainText"
    （青橄榄 CMS 的 TRS_UEDITOR 编辑区），因此按候选选择器依次试。
    """
    body = ''
    for sel in (r'id="UCAP-CONTENT"', r'class="[^"]*pages_content[^"]*"', r'id="mainText"',
                r'class="[^"]*TRS_UEDITOR[^"]*"', r'id="zoom"', r'class="[^"]*Article_content[^"]*"',
                r'id="ivs_content"'):
        body = container(page_html, sel)
        if body:
            break
    if not body:
        return '', ''
    body = re.sub(r'<script.*?</script>|<style.*?</style>', '', body, flags=re.S | re.I)
    body = re.sub(r'<!--.*?-->', '', body, flags=re.S)
    body = re.sub(r'<(p|div|br|tr|h\d|li)\b[^>]*>', '\n', body, flags=re.I)
    body = re.sub(r'<[^>]+>', '', body)
    body = html.unescape(body)
    lines = [re.sub(r'[\t 　 ]+', ' ', x).strip() for x in body.split('\n')]
    text = '\n'.join(x for x in lines if x)
    src = re.findall(r'来源[：:]\s*([^\n<]{2,20})', page_html)
    return text, (src[0].strip() if src else '')


def fetch(target, seed=20261111):
    rows = [json.loads(l) for l in (OUT / 'gov_index.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    done = set()
    dst = OUT / 'jsonl' / 'gov_cn_policy_library.jsonl'
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        for l in dst.read_text(encoding='utf-8').splitlines():
            try:
                done.add(json.loads(l)['url'])
            except Exception:
                pass
    # 确定性抽样：按 id 的 SHA256 前 8 位排序取前 target 篇（与关键词无关，避免按答案挑句）
    rows.sort(key=lambda r: hashlib.sha256((r['id'] + r['url']).encode()).hexdigest())
    picked = rows[:target]
    print('候选 %d，抽样 %d，已完成 %d' % (len(rows), len(picked), len(done)), flush=True)
    stats = collections.Counter()
    with io.open(dst, 'a', encoding='utf-8', newline='\n') as w:
        for r in picked:
            if r['url'] in done:
                stats['resume_skip'] += 1
                continue
            h = get(r['url'], binary=True)
            if not h:
                stats['fetch_fail'] += 1
                continue
            enc = 'utf-8'
            try:
                page = h.decode('utf-8')
            except UnicodeDecodeError:
                page = h.decode('gb18030', 'replace'); enc = 'gb18030'
            text, src = extract(page)
            han = sum(1 for c in text if '一' <= c <= '鿿')
            if han < 300:
                stats['short_or_empty'] += 1
                continue
            if src and not re.search(r'中国政府网|国新网|本站|来源', src):
                stats['media_source_skipped'] += 1
                continue
            w.write(json.dumps(dict(domain='现代', register='政务公文', period=(r['year'] or '') + '年代',
                                    work=WORK, title=r['title'], url=r['url'], license=LICENSE,
                                    source_family=FAMILY, puborg=r['org'], childtype=r['child'],
                                    kind=r['kind'], fetched_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
                                    src_sha=hashlib.sha256(h).hexdigest(), encoding=enc,
                                    chars=han, raw=text), ensure_ascii=False) + '\n')
            stats['kept'] += 1
            stats['kept_han'] += han
            if stats['kept'] % 100 == 0:
                w.flush()
                print('  已存 %d 篇 / %d 字，丢弃 %s' % (stats['kept'], stats['kept_han'], dict(stats)), flush=True)
            time.sleep(0.15)
    print('GOV FETCH DONE', json.dumps({k: v for k, v in stats.items()}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('stage', choices=('index', 'fetch'))
    ap.add_argument('--target', type=int, default=2200)
    a = ap.parse_args()
    (index if a.stage == 'index' else lambda: fetch(a.target))()
