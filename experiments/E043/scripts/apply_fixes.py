#!/usr/bin/env python3
"""E043：按园长批准的六项修复 + 补 `更赋` 一行，改 data/correction/candidates.tsv。

规矩：逐处**精确整行匹配**，匹配不到就报错退出，不做模糊替换；
写回必须用 write_bytes + LF（.gitattributes 把 data/** 设为 -text，上一轮我用 write_text 造成过全表 CRLF）。
"""
import hashlib, pathlib, sys

R = pathlib.Path(__file__).resolve().parents[3]
TBL = R / 'data/correction/candidates.tsv'

FIX = [
    ('高句丽\tgaogou1li2\t高沟黎\t人工确认\t1', '高句丽\tgao1gou1li2\t高沟黎\t人工确认\t1'),
    ('物资\tlwu4zi1\t沃兹\t人工确认\t1', '物资\twu4zi1\t沃兹\t人工确认\t1'),
    ('妥协\ttuo3xie2\t妥协\t人工确认\t1', '妥协\ttuo3xie2\t\t人工确认\t0'),
]
DELETE = [
    '祥符决口\txiang2fu2jue2kou3\t降服决口\t人工确认\t1',   # 整行重复，留一处
    '赈济\tzhen4ji3\t政绩\t人工确认\t1',                     # 正确读法是 ji4，留 ji4 行
    '与\tyu2\t于\t人工确认\t1',                              # 单字目标结构不可达，且与 status=0 行重名
]
ADD = ['更赋\tgeng1fu4\t庚付\t人工确认\t1']                  # 真值位点 8009 用的就是「更赋」，ASR 是「庚付」

text = TBL.read_text(encoding='utf-8')
if '\r\n' in text:
    sys.exit('表里已有 CRLF，先停手核查')
lines = text.split('\n')

for old, new in FIX:
    if lines.count(old) != 1:
        sys.exit('待改行匹配数=%d（应为 1）：%r' % (lines.count(old), old))
    lines[lines.index(old)] = new

for drop in DELETE:
    n = lines.count(drop)
    if n < 1:
        sys.exit('待删行不存在：%r' % drop)
    lines.pop(lines.index(drop))
    if drop.startswith('祥符决口') and lines.count(drop) != 1:
        sys.exit('祥符决口 应剩 1 行')

for extra in ADD:
    canon = extra.split('\t')[0]
    if any(l.startswith(canon + '\t') for l in lines):
        sys.exit('%s 已存在，不重复添加' % canon)
    while lines and not lines[-1].strip():
        lines.pop()
    lines.append(extra)

body = '\n'.join(l for l in lines if True).rstrip('\n') + '\n'
TBL.write_bytes(body.encode('utf-8'))            # 字节写回，行尾固定 LF
print('写出 %d 行，SHA256 %s' % (len(body.splitlines()), hashlib.sha256(TBL.read_bytes()).hexdigest()[:16]))
print('CRLF 检查:', '无' if '\r' not in body else '有！')
