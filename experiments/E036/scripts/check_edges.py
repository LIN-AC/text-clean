#!/usr/bin/env python3
"""边界标注专项核查（回应 Astra E037 §三.2/3/4/5）。

只回答四个问题：
  1) 类别与 is_stop 是否还可能互相矛盾（v1 有 32 处）；
  2) "空白或换行"这一类里是否还混着引号、数字、字母、模板残留；
  3) 无句末标点的历史文档到底多少篇、分布在哪几部书（按文档实测，不按书名下结论）；
  4) 字数统计按字符范围分列，不再把扩展区和其他保留字符混进"汉字数"。
"""
import collections, json, pathlib, sqlite3, sys

R = pathlib.Path(__file__).resolve().parents[3]
db = sqlite3.connect(R / 'build/e036_corpus/corpus.sqlite')
sys.stdout.reconfigure(encoding='utf-8')
rep = {}

conf = db.execute("""select count(*) from segs where
    (right_class='句末标点') <> (right_is_stop=1) or (left_class='句末标点') <> (left_is_stop=1)""").fetchone()[0]
left = dict(db.execute('select left_class, count(*) from segs group by 1'))
right = dict(db.execute('select right_class, count(*) from segs group by 1'))
rep['类别与is_stop矛盾段'] = conf
rep['左端类别'] = left
rep['右端类别'] = right
print('1) 类别与句末标记矛盾的段：%d（v1 报的是 32）' % conf)
print('2) 段端类别分布（右端）：%s' % json.dumps(right, ensure_ascii=False))
print('   （左端）：%s' % json.dumps(left, ensure_ascii=False))
blank_old = right.get('空白或换行', 0)
split_out = sum(v for k, v in right.items() if k in ('引号或括号', '数字', '拉丁字母', '其他符号或标记残留'))
print('   原来标"换行或空白"的 109,603 处，现在只剩 %d 处真是空白/换行，其余 %d 处已按实测字符分到引号括号／数字／拉丁字母／标记残留' % (blank_old, split_out))

# 3) 无句末标点文档按书统计
rows = collections.defaultdict(lambda: collections.Counter())
for fam, kind, n in db.execute('select source_family, boundary_kind, count(*) from docs where domain="历史" group by 1,2'):
    rows[fam][kind] = n
rep['历史文档边界分类'] = {f: dict(c) for f, c in rows.items()}
print('3) 历史各书的边界实测：')
for f in sorted(rows, key=lambda x: -sum(rows[x].values())):
    print('   %-14s %s' % (f, dict(rows[f])))
tot = sum(sum(c.values()) for c in rows.values())
nostop = sum(c.get('全篇无标点，段边界=原文献换行', 0) + c.get('仅有句内逗读，无句末标点', 0) for c in rows.values())
print('   合计 %d 篇，其中无句末标点 %d 篇（不是"只有两部书 146 卷"）' % (tot, nostop))

# 4) 字符范围分列
out = {}
for dom in ('现代', '历史'):
    c = collections.Counter()
    for (tn,) in db.execute('select text_norm from docs where domain=?', (dom,)):
        for ch in tn:
            if ch == ' ':
                c['空格(边界)'] += 1
            elif chr(0x4e00) <= ch <= chr(0x9fff):
                c['基本汉字 U+4E00-U+9FFF'] += 1
            elif chr(0x3400) <= ch <= chr(0x4dbf):
                c['扩展A U+3400-U+4DBF'] += 1
            elif ch.isalpha():
                c['其他汉字或字母'] += 1
            else:
                c['其他保留符号'] += 1
    out[dom] = dict(c)
rep['字符范围'] = out
print('4) 字符范围分列：')
for dom, c in out.items():
    print('   %s：%s' % (dom, json.dumps(c, ensure_ascii=False)))

(R / 'experiments/E036/results/edge_check.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding='utf-8')
print('\n结论：%s' % ('边界一致性通过' if conf == 0 else '仍有 %d 处矛盾，未过' % conf))
