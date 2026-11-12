#!/usr/bin/env python3
"""开卷臂的位点级归因：Deepseek 旧表 trace vs 本轮新表 trace，方法/包结构相同，只换候选表。

对每个消失或新增的"改对位点"，从产生该改写的那一侧 trace 里取出对应窗口记录：
窗口里的 source/H 给出实际写入的目标词，再判断该词是否在定稿时被删除或停用。
"""
import collections, json, pathlib, sys

R = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(R / 'experiments/E024/scripts'))
sys.stdout.reconfigure(encoding='utf-8')
from align_lib import align     # noqa: E402

PATHS = {
    'openbook': ('experiments/E046/results/openbook.%s.gt.trace.json',
                 'build/e044_probe/traces_base/openbook.%s.gt.trace.json'),
    'perfect': ('experiments/E046/results/perfect.%s.gt.trace.json',
                'build/e044_probe/traces_base/perfect.%s.gt.trace.json'),
}
# 定稿相对旧表删除或停用的启用行（来自 git diff 与 E043 记录）
REMOVED = set('''卫青霍去 会要辑 祥符决口 摇薄赋 轻摇薄赋 鹿皮币 耕赋 妥协和清醒 宗室各 城勋 弘羊 句丽
跋宏 跋澄 豪强藏人 配书模式 在祥符决口 赋耕赋 赋更赋 均输平 当卖爵 事频仍 以建居为簿 仰马翻 任城王 伯颜
前的 匈漠 吉思 史之 只抢 塞光是 它霉 屋活 常掸 强像 役共 性劣势 慎独慎 掉藩镇 接时 远远 邻五邻 里五里
里物资 衍是 计跻 诿躲 胆魄与 微信 支付宝 腾讯 银行卡 验证码 转账 华为 抖音'''.split())
DEMOTED = {'华为', '抖音', '妥协'}


def rows_of(video):
    rr = [json.loads(s) for s in (R / 'asr' / (video + '.gt.jsonl')).read_text('utf-8').splitlines() if s.strip()]
    return [r for r in rr if not r.get('discard')]


def labels_and_offsets(rows):
    lab, off = {}, 0
    starts = []
    for r in rows:
        starts.append(off)
        l, _ = align(r['text'], r['gt'])
        lab.update({off + i: v for i, v in l.items()})
        off += len(r['text']) + 1
    return lab, starts


def tp_set(trace, rows):
    body = '\n'.join(r['text'] for r in rows) + '\n'
    out = trace['text']
    lab, starts = labels_and_offsets(rows)
    good = {i for i, v in lab.items() if out[i] != body[i] and out[i] == v}
    bad = {i for i, v in lab.items() if out[i] != body[i] and out[i] != v and body[i] == v}
    return good, bad, lab, starts, body, out


def window_for(trace, starts, pos):
    """找覆盖该位点的窗口，取实际写出的目标词（在 H 里且 executable 的那个）。"""
    vi = max(j for j, s in enumerate(starts) if s <= pos)
    best = None
    for w in trace['windows']:
        if w['begin'] > pos or w['end'] <= pos:
            continue
        for h in w.get('H', []):
            if h.get('executable') and w['begin'] <= pos < w['begin'] + len(h['word']):
                cand = pos - w['begin']
                if 0 <= cand < len(h['word']):
                    best = (w['source'], h['word'], w.get('reason'), w.get('p', h.get('p')))
        if best:
            return best
    return (None, None, 'no_window', None)


for arm, (old_tpl, new_tpl) in PATHS.items():
    lost = collections.Counter()
    gained = collections.Counter()
    lost_rows, gained_rows = [], []
    tot1 = tot2 = 0
    for video in sorted(p.stem[:-3] for p in (R / 'asr').glob('*.gt.jsonl')):
        o, n = R / (old_tpl % video), R / (new_tpl % video)
        if not (o.exists() and n.exists()):
            print('  %s 跳过 %s（缺 trace）' % (arm, video))
            continue
        rows = rows_of(video)
        g1, b1, lab, starts, _, _ = tp_set(json.loads(o.read_text('utf-8')), rows)
        tr_new = json.loads(n.read_text('utf-8'))
        g2, b2, _, _, _, _ = tp_set(tr_new, rows)
        tot1 += len(g1)
        tot2 += len(g2)
        for pos in sorted(g1 - g2):
            src, tgt, reason, p = window_for(json.loads(o.read_text('utf-8')), starts, pos)
            tag = ('删除行' if tgt in REMOVED else '停用行' if tgt in DEMOTED else '仍启用' if tgt else '无窗口')
            lost[tag] += 1
            lost_rows.append((video, pos, src, tgt, tag, lab.get(pos)))
        for pos in sorted(g2 - g1):
            src, tgt, reason, p = window_for(tr_new, starts, pos)
            gained[tgt or '?'] += 1
            gained_rows.append((video, pos, src, tgt, lab.get(pos)))
    print('\n==== %s：旧表 TP %d → 新表 TP %d（%+d）' % (arm, tot1, tot2, tot2 - tot1))
    print('   消失位点归因：', dict(lost))
    for v, pos, src, tgt, tag, gt in lost_rows[:25]:
        print('     - %-16s 位点%-6d %s→%s 目标词归类 %s（真值字 %s）' % (v[:16], pos, src, tgt, tag, gt))
    print('   新增位点目标词：', dict(gained))
    for v, pos, src, tgt, gt in gained_rows[:15]:
        print('     + %-16s 位点%-6d %s→%s（真值 %s）' % (v[:16], pos, src, tgt, gt))
    dst = R / ('experiments/E044/results/attribute_' + arm + '.json')
    dst.write_text(json.dumps(dict(arm=arm, old_tp=tot1, new_tp=tot2,
                                    lost=[list(x) for x in lost_rows], gained=[list(x) for x in gained_rows],
                                    lost_by=dict(lost), gained_by=dict(gained)),
                                ensure_ascii=False, indent=2), encoding='utf-8')
    print('写出', dst)
