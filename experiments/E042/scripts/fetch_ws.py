#!/usr/bin/env python3
"""E042 P1：从维基文库补新增古籍来源组（不重切 E036 已有四部书）。

stage=probe  只用 allpages 数每个作品的子页数，不取正文
stage=fetch  按子页批量取 wikitext，逐页缓存到 build/e042_corpus/raw_ws/（可续跑）
stage=clean  把缓存的 wikitext 汇成契约文档 JSONL：一卷=一个文档，行边界=转录原始换行

许可：作品本身公有领域；转录由维基文库按 CC BY-SA/GFDL 提供，逐页记录标题、URL、修订时间戳与 SHA256。
"""
import argparse, collections, hashlib, json, pathlib, re, subprocess, sys, time, urllib.parse

sys.stdout.reconfigure(encoding='utf-8')
OUT = pathlib.Path('build/e042_corpus')
RAW = OUT / 'raw_ws'
API = 'https://zh.wikisource.org/w/api.php'
UA = 'text_clean-e042/1.0 (research corpus, non-commercial)'
LICENSE = '公有领域古籍；维基文库转录按 CC BY-SA 4.0/GFDL 提供，逐页署名来源 URL'
WORKS = ['資治通鑑', '宋史', '晉書', '清史稿', '鹽鐵論', '通典', '文獻通考', '續資治通鑑長編',
         '金史', '元史', '新唐書', '舊唐書', '三國志', '後漢書', '史記', '周禮', '管子', '商君書',
         '夢溪筆談', '農政全書', '天工開物', '貞觀政要', '明史紀事本末', '讀史方輿紀要', '徐霞客遊記',
         '宋會要輯稿', '唐會要', '冊府元龜', '國語', '戰國策', '漢書', '後漢書補逸', '明夷待訪錄']

MARK = re.compile(r'\{\{[^|}]*\|?|\}\}|\[\[|\]\]|<[^>]*>|={2,}')   # 与 E036 建库同源的标记残留清理参照


def api(params, waits=(0, 20, 60, 120, 240)):
    q = urllib.parse.urlencode(params)
    for w in waits:
        if w:
            print('  限流/失败，等 %ds' % w, flush=True)
            time.sleep(w)
        r = subprocess.run(['curl', '-s', '--max-time', '90', '-A', UA, '-w', '\n@@%{http_code}',
                            API + '?' + q], capture_output=True)
        raw = r.stdout.decode('utf-8', 'replace')
        body, _, code = raw.rpartition('\n@@')
        if code.strip() in ('429', '403', '503') or not body.strip():
            continue
        try:
            return json.loads(body)
        except Exception:
            continue
    return {}


def subpages(title, limit=4000):
    names, cont = [], {}
    while True:
        p = dict(action='query', list='allpages', apprefix=title + '/', apnamespace='0',
                 aplimit='max', format='json')
        p.update(cont)
        d = api(p)
        for it in (d.get('query') or {}).get('allpages', []):
            names.append(it['title'])
        if 'continue' in d and len(names) < limit:
            cont = d['continue']
            time.sleep(1.0)
        else:
            break
    return names


def probe():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for w in WORKS:
        one = api(dict(action='query', titles=w, prop='info', format='json'))
        pages = (one.get('query') or {}).get('pages', {})
        exists = any('missing' not in p for p in pages.values())
        sp = subpages(w) if exists or True else []
        rows.append(dict(work=w, root_exists=exists, subpages=len(sp)))
        print('%-12s 主页面 %s 子页 %d' % (w, '有' if exists else '无', len(sp)), flush=True)
        time.sleep(0.6)
    (OUT / 'ws_probe.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')


def fetch(work, max_pages=0):
    RAW.mkdir(parents=True, exist_ok=True)
    names = [work] + subpages(work)
    if max_pages:
        names = names[:max_pages]
    got = 0
    for i in range(0, len(names), 20):
        batch = names[i:i + 20]
        d = api(dict(action='query', titles='|'.join(batch), prop='revisions', rvprop='content|timestamp',
                     rvslots='main', format='json', formatversion='2'))
        for pg in (d.get('query') or {}).get('pages', []):
            rev = (pg.get('revisions') or [{}])[0]
            content = ((rev.get('slots') or {}).get('main') or {}).get('content') or rev.get('content') or ''
            if not content:
                continue
            key = hashlib.sha256(pg['title'].encode()).hexdigest()[:16]
            f = RAW / ('%s__%s.json' % (re.sub(r'[^\w一-鿿]+', '_', work), key))
            f.write_text(json.dumps(dict(work=work, title=pg['title'], timestamp=rev.get('timestamp', ''),
                                         content=content), ensure_ascii=False), encoding='utf-8')
            got += 1
        print('  %s %d/%d 取回%d' % (work, min(i + 20, len(names)), len(names), got), flush=True)
        time.sleep(1.2)
    print('FETCH %s 页 %d' % (work, got), flush=True)


def clean(work, domain='历史', register='古籍转录'):
    """缓存 → 文档 JSONL：只剥标记，保留换行；一卷一片，不拼接不同页。"""
    dst = OUT / 'jsonl'
    dst.mkdir(parents=True, exist_ok=True)
    out = dst / ('ws_%s.jsonl' % re.sub(r'[^\w一-鿿]+', '_', work))
    n = c = 0
    with out.open('w', encoding='utf-8', newline='\n') as w:
        for f in sorted(RAW.glob('%s__*.json' % re.sub(r'[^\w一-鿿]+', '_', work))):
            d = json.loads(f.read_text(encoding='utf-8'))
            t = re.sub(r'<ref[^>]*>.*?</ref>|<ref[^/>]*/>', '', d['content'], flags=re.S)
            for _ in range(12):
                s = re.sub(r'\{\{[^{}]*\}\}', '', t, flags=re.S)
                if s == t:
                    break
                t = s
            t = re.sub(r'__[A-Z_]+__', '', t)
            t = re.sub(r'<nowiki>|</nowiki>', '', t)
            t = re.sub(r'\[\[(?:File|Image|Category):[^]]*\]\]', '', t, flags=re.I)
            t = re.sub(r'\[\[(?:[^]|]*\|)?([^]]*)\]\]', r'\1', t)
            t = re.sub(r'<[^>]+>', '', t)
            t = re.sub(r"'''?", '', t)
            lines = []
            for line in t.split('\n'):
                s = line.strip()
                if not s or s[0] in '{|}!#;:' or s.startswith('|-'):
                    continue
                s = re.sub(r'^=+\s*(.*?)\s*=+\s*$', r'\1', s)
                s = re.sub(r'\s+', ' ', s).strip()
                if s:
                    lines.append(s)
            text = '\n'.join(lines)
            han = sum(1 for ch in text if '一' <= ch <= '鿿' or chr(0x3400) <= ch <= chr(0x4dbf))
            if han < 120:
                continue
            w.write(json.dumps(dict(domain=domain, register=register, period=d['work'], work=d['work'],
                                    title=d['title'], url='https://zh.wikisource.org/wiki/' +
                                    urllib.parse.quote(d['title'].replace(' ', '_')), license=LICENSE,
                                    source_family='wikisource_' + re.sub(r'[^\w]+', '', work),
                                    rev_timestamp=d['timestamp'], src_sha=hashlib.sha256(d['content'].encode()).hexdigest(),
                                    chars=han, raw=text), ensure_ascii=False) + '\n')
            n += 1
            c += han
    print('CLEAN %s 文档 %d 汉字 %d → %s' % (work, n, c, out), flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('stage', choices=('probe', 'fetch', 'clean'))
    ap.add_argument('--work', default='')
    ap.add_argument('--max-pages', type=int, default=0)
    ap.add_argument('--domain', default='历史', help='公有领域现代白话用 现代')
    ap.add_argument('--register', default='古籍转录')
    a = ap.parse_args()
    if a.stage == 'probe':
        probe()
    elif a.stage == 'fetch':
        fetch(a.work, a.max_pages)
    elif a.work:
        clean(a.work, a.domain, a.register)
    else:
        for w in sorted({re.split(r'__', p.stem)[0] for p in RAW.glob('*.json')}):
            clean(w, a.domain, a.register)
