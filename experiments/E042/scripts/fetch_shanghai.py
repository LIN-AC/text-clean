#!/usr/bin/env python3
"""E042：抓上海市政府信息公开文件，作为现代政务语料的又一个独立来源组（不同网站、不同编辑社区）。

列表 https://www.shanghai.gov.cn/nw12344/index.html 及 index_N.html（N 从 2 起，index_1 不存在）；
正文容器与北京市政府同类 CMS 不同，交给 fetch_gov.extract() 的选择器列表统一处理。
许可口径：地方行政规范性文件，著作权法第五条不适用著作权；逐篇留 URL 与标题。
"""
import argparse, collections, hashlib, importlib.util, json, pathlib, re, subprocess, sys, time

R = pathlib.Path(__file__).resolve().parents[3]
sys.stdout.reconfigure(encoding='utf-8')
spec = importlib.util.spec_from_file_location('fg', R / 'experiments/E042/scripts/fetch_gov.py')
FG = importlib.util.module_from_spec(spec)
argv, sys.argv = sys.argv, ['fetch_gov.py', 'index']
spec.loader.exec_module(FG)
sys.argv = argv

OUT = R / 'build/e042_corpus'
BASE = 'https://www.shanghai.gov.cn'
FAMILY = 'shanghai_gov_policy_library'
WORK = '上海市人民政府 信息公开文件'
LICENSE = ('上海市政府公开文件（地方行政规范性文件）；著作权法第五条不适用著作权的行政性质文件；逐篇标注来源 URL')
GET = ['curl', '-s', '-m', '45', '--noproxy', '*', '-A', 'text_clean-e042/1.0 (research)']


def listing_pages(max_pages=60):
    urls = []
    for i in range(1, max_pages + 1):
        u = BASE + '/nw12344/index.html' if i == 1 else BASE + '/nw12344/index_%d.html' % i
        h = subprocess.run(GET + [u], capture_output=True).stdout.decode('utf-8', 'replace')
        if not h or len(h) < 3000:
            continue
        found = re.findall(r'href="(/nw\d+/\d{8}/[0-9a-f]{20,}\.html)"', h)
        urls += [BASE + x for x in dict.fromkeys(found)]
        time.sleep(0.08)
    return list(dict.fromkeys(urls))


def main(target=700):
    dst = OUT / 'jsonl' / (FAMILY + '.jsonl')
    dst.parent.mkdir(parents=True, exist_ok=True)
    links = listing_pages()
    print('列表取到文件链接 %d' % len(links), flush=True)
    done = set()
    if dst.exists():
        for l in dst.read_text(encoding='utf-8').splitlines():
            try:
                done.add(json.loads(l)['url'])
            except Exception:
                pass
    links.sort(key=lambda u: hashlib.sha256(u.encode()).hexdigest())
    stats = collections.Counter()
    with dst.open('a', encoding='utf-8', newline='\n') as w:
        for u in links:
            if stats['kept'] >= target:
                break
            if u in done:
                continue
            raw = subprocess.run(GET + [u], capture_output=True).stdout
            if not raw:
                stats['fetch_fail'] += 1
                continue
            page = raw.decode('utf-8', 'replace')
            text, src = FG.extract(page)
            han = sum(1 for c in text if '一' <= c <= '鿿')
            title_m = re.search(r'<title>([^<]{4,90})</title>', page)
            title = (title_m.group(1) if title_m else '').strip()
            year_m = re.search(r'/(\d{4})\d{4}/', u)
            year = (year_m.group(1) if year_m else '') + '年'
            if han < 250:
                stats['short_or_empty'] += 1
                continue
            if src and '上海' not in src and '政府' not in src and '本站' not in src:
                stats['media_source_skipped'] += 1
                continue
            w.write(json.dumps(dict(domain='现代', register='地方政务公文', period=year, work=WORK, title=title,
                                    url=u, license=LICENSE, source_family=FAMILY,
                                    fetched_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
                                    src_sha=hashlib.sha256(raw).hexdigest(), chars=han, raw=text),
                                ensure_ascii=False) + '\n')
            stats['kept'] += 1
            stats['kept_han'] += han
            if stats['kept'] % 100 == 0:
                w.flush()
                print('  已存 %d 篇 / %d 字 %s' % (stats['kept'], stats['kept_han'], dict(stats)), flush=True)
            time.sleep(0.1)
    print('SHANGHAI DONE', json.dumps({k: v for k, v in stats.items()}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', type=int, default=700)
    main(ap.parse_args().target)
