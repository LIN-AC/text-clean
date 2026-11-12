#!/usr/bin/env python3
"""候选表体检：把"不像一个词"的条目用可核对的证据挑出来。

判定一条一条给依据，不靠感觉：
  格式类：别名与目标词长度不等、读音音节数与字数不符、含非汉字、别名等于目标词、同目标多读音冲突；
  语料类：目标词在 E036 原料库（现代 91.6 万字 + 历史 715.3 万字，去重后）里**从未作为连续串出现**；
  拼接类：目标词可拆成两个各自独立出现的启用目标词（跨实体/跨词边界的嫌疑，如 卫青霍去 = 卫青 + 霍去病 的相邻片段）。
只读脚本，不改表；改表由 audit 结果另行执行。
"""
import collections, json, pathlib, re, sqlite3, sys

R = pathlib.Path(__file__).resolve().parents[3]
DATA = R / 'data'
DB = R / 'build/e036_corpus/corpus.sqlite'
OUT = R / 'experiments/E036/results/candidates_audit.json'
sys.path.insert(0, str(R / 'experiments/E036/scripts'))
sys.stdout.reconfigure(encoding='utf-8')
SYL = re.compile(r'[a-zv:]+[0-5]')


def rows_of(path):
    return list(__import__('csv').DictReader((l for l in path.read_text(encoding='utf-8').splitlines()
                                              if not l.startswith('#')), delimiter='\t'))


def main():
    body = rows_of(DATA / 'correction/candidates.tsv')
    en = [r for r in body if r['status'] == '1']
    tg = sorted({r['canonical'] for r in en}, key=len, reverse=True)
    T = set(tg)
    db = sqlite3.connect(DB)
    docs = [tn for (tn,) in db.execute('select text_norm from docs')]
    print('原料库文档 %d 篇，总字数 %.1f 万' % (len(docs), sum(len(h) for h in docs) / 1e4))
    # 合成一根大串（段间用空格隔开，规范化里空格就是边界，所以词不会跨文档粘连）；
    # 逐词查一次比"每个词扫 9 万篇"快两个数量级。
    BIG = ' '.join(docs)

    def in_corpus(w, limit=None):
        return 1 if w in BIG else 0

    absent, glued, bad_len, bad_py, non_cjk, same, multi_read = [], [], [], [], [], [], []
    by_target = collections.defaultdict(set)
    for r in en:
        by_target[r['canonical']].add(r['pinyin'])
    for r in en:
        t, a, p = r['canonical'], r['alias'], r['pinyin']
        if len(t) != len(a):
            bad_len.append((t, a))
        if len(SYL.findall(p)) != len(t) or ''.join(SYL.findall(p)) != p:
            bad_py.append((t, p))
        if not re.fullmatch(r'[一-鿿]+', t):
            non_cjk.append(t)
        if t == a:
            same.append(t)
        sp = [t[:i] for i in range(2, len(t) - 1) if t[:i] in T and t[i:] in T]
        if len(t) >= 4 and sp:
            glued.append((t, sp[0] + '+' + t[len(sp[0]):]))
    for t in sorted(T):
        if in_corpus(t, limit=1) == 0:
            absent.append(t)
    multi_read = [t for t, s in by_target.items() if len(s) > 1]

    print('=== 体检结果（启用行 %d，去重目标词 %d）===' % (len(en), len(T)))
    for name, lst in (('别名与目标词长度不等', bad_len), ('读音音节数≠字数或含杂字符', bad_py),
                      ('目标词含非汉字', non_cjk), ('别名等于目标词', same),
                      ('同一目标词有多个读音写法', multi_read),
                      ('可拆成两个启用目标词（跨词边界嫌疑）', glued),
                      ('在 807 万字原料库中从未连续出现', absent)):
        print('  %-24s %4d 条  例：%s' % (name, len(lst), (lst[:8] if lst else '—')))
    absent_len = collections.Counter(len(t) for t in absent)
    print('  其中"从未出现"的按长度分布：', dict(sorted(absent_len.items())))
    print('\n逐条列出"从未出现"的条目（这些是最该复核是否真的是一个词的）：')
    for t in absent:
        row = next(r for r in en if r['canonical'] == t)
        print('   %-12s 别名 %-12s 读音 %-22s 来源 %s' % (t, row['alias'], row['pinyin'], row['source']))
    OUT.write_text(json.dumps(dict(
        enabled_rows=len(en), targets=len(T), corpus_docs=len(docs),
        长度不等=bad_len, 读音不符=bad_py, 含非汉字=non_cjk, 别名同形=same, 多读音=multi_read,
        跨词拼接=glued, 语料未见=absent), ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
