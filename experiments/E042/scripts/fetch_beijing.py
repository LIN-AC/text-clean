#!/usr/bin/env python3
"""E042：抓北京市政府政策文件库（地方行政规范性文件），作为现代政务语料的独立来源组。

列表页 https://www.beijing.gov.cn/zhengce/zhengcefagui/ 单页即含约 999 条文件链接，不翻页；
抽样规则与 fetch_gov.py 相同：按 sha256(URL) 升序取前 N 篇，与关键词无关，避免按答案挑料。
许可口径：著作权法第五条对国家机关具有立法、行政、司法性质的文件不适用著作权；逐篇留 URL、标题、日期。
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
LIST = 'https://www.beijing.gov.cn/zhengce/zhengcefagui/'
FAMILY = 'beijing_gov_policy_library'
WORK = '北京市人民政府 政策文件库'
LICENSE = ('北京市政府公开政策文件（地方行政规范性文件）；著作权法第五条不适用著作权的行政性质文件；'
           '逐篇标注来源 URL 与发文机关')
ITEM = re.compile(r'href="(\./(\d{6})/(t\d+_\d+)\.html)"[^>]*title="([^"]{6,120})"')


def fetch(target=700):
    dst = OUT / 'jsonl' / 'beijing_gov_policy_library.jsonl'
    dst.parent.mkdir(parents=True, exist_ok=True)
    html = FG.get(LIST)
    if not html:
        print('列表页取回失败'); return 1
    items = []
    for rel, ym, stem, title in ITEM.findall(html):
        url = LIST + rel.lstrip('./')
        items.append(dict(url=url, title=title.strip(), ym=ym))
    print('列表页条目 %d' % len(items), flush=True)
    done = set()
    if dst.exists():
        for l in dst.read_text(encoding='utf-8').splitlines():
            try:
                done.add(json.loads(l)['url'])
            except Exception:
                pass
    items.sort(key=lambda r: hashlib.sha256(r['url'].encode()).hexdigest())
    stats = collections.Counter()
    with dst.open('a', encoding='utf-8', newline='\n') as w:
        for r in items:
            if stats['kept'] >= target:
                break
            if r['url'] in done:
                continue
            h = subprocess.run(['curl', '-s', '-m', '45', '--noproxy', '*', '-A', 'text_clean-e042/1.0',
                                r['url']], capture_output=True).stdout
            if not h:
                stats['fetch_fail'] += 1
                continue
            page = h.decode('utf-8', 'replace')
            text, src = FG.extract(page)
            han = sum(1 for c in text if '一' <= c <= '鿿')
            if han < 250:
                stats['short_or_empty'] += 1
                continue
            if src and '北京' not in src and '政府' not in src and '本站' not in src:
                stats['media_source_skipped'] += 1
                continue
            w.write(json.dumps(dict(domain='现代', register='地方政务公文', period=r['ym'][:4] + '年',
                                    work=WORK, title=r['title'], url=r['url'], license=LICENSE,
                                    source_family=FAMILY, fetched_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
                                    src_sha=hashlib.sha256(h).hexdigest(), chars=han, raw=text),
                                ensure_ascii=False) + '\n')
            stats['kept'] += 1
            stats['kept_han'] += han
            if stats['kept'] % 100 == 0:
                w.flush()
                print('  已存 %d 篇 / %d 字 %s' % (stats['kept'], stats['kept_han'], dict(stats)), flush=True)
            time.sleep(0.1)
    print('BEIJING DONE', json.dumps({k: v for k, v in stats.items()}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', type=int, default=700)
    fetch(ap.parse_args().target)
