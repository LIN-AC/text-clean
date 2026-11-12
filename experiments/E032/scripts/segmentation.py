#!/usr/bin/env python3
"""E032 第一步：分句呈现方式对纠错结果的影响（不需要重跑 whisper）。

园长假设：错误率飙升可能来自分句错误。本步只改"喂给纠错器的行怎么切"，
text_clean 参数一律用当前生产默认（M1+M2 K=0.6 + 跨度2 单边上下文），因此结果差异
只能来自分句呈现本身。

  A 逐 cue（每条字幕单独调用一次，句子之间完全不互看）
  B 整篇按 cue 换行（现有全部实验的口径，作为对照）
  C 整篇去换行后按固定 40 字重新切行（模拟另一种分句）
  D 全部并成一行（等于没有分句）

评测口径与 E022-E031 相同；A/C/D 需要把偏移映射回原 cue 才能对齐真值，
做法是逐 cue 重跑一遍同一口径的对齐，不共用 B 的标签。
"""
import collections, json, pathlib, subprocess, sys

R = pathlib.Path(__file__).resolve().parents[3]
O = R / 'experiments/E032/results'
O.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(R / 'experiments/E024/scripts'))
import align_lib as A
sys.stdout.reconfigure(encoding='utf-8')

EXE = str(R / 'build/e025/text_clean.exe')     # 当前生产默认，不加任何评分参数


def run(lines):
    """把给定的行依次喂进去，返回 (输出全文, 输入全文)。"""
    body = ''.join(l + '\n' for l in lines)
    p = subprocess.run([EXE, '--no-index-cache'], input=body.encode('utf-8'), capture_output=True, cwd=str(R))
    assert p.returncode == 0, p.stderr.decode('utf-8', 'replace')[:300]
    return p.stdout.decode('utf-8'), body


def score(cues, grouping):
    """grouping: 'per-cue' | 'whole' | 'fixed40' | 'single'"""
    tp = fp = wr = dist = 0
    if grouping == 'per-cue':
        outs = [run([c['text']])[0].rstrip('\n') for c in cues]
    elif grouping == 'whole':
        out, _ = run([c['text'] for c in cues]); outs = out.splitlines()
    elif grouping == 'single':
        out, _ = run([''.join(c['text'] for c in cues)])
        outs = [out.rstrip('\n')]
    else:  # fixed40：整篇拼起来后每 40 字强行切一行
        text = ''.join(c['text'] for c in cues)
        out, _ = run([text[i:i + 40] for i in range(0, len(text), 40)])
        outs = out.splitlines()
    # 真值侧同样按该分组重算：先把 cue 文本与真值拼回全文再切
    src_full = ''.join(c['text'] for c in cues)
    gt_full = ''.join(c['gt'] for c in cues)
    if grouping == 'per-cue':
        pairs = list(zip([c['text'] for c in cues], outs, [c['gt'] for c in cues]))
        for src, out, gt in pairs:
            lab, _ = A.align(src, gt)
            tp += sum(1 for i, v in lab.items() if i < len(out) and out[i] != src[i] and out[i] == v)
            fp += sum(1 for i, v in lab.items() if i < len(out) and out[i] != src[i] and src[i] == v)
            wr += sum(1 for i, v in lab.items() if i < len(out) and out[i] != src[i] and out[i] != v and src[i] != v)
            dist += A.align(out, gt)[1]
    else:
        chunks = ([src_full] if grouping == 'single'
                  else [src_full[i:i + 40] for i in range(0, len(src_full), 40)]
                  if grouping == 'fixed40' else [c['text'] for c in cues])
        assert len(chunks) == len(outs), (grouping, len(chunks), len(outs))
        if grouping == 'whole':
            # 逐 cue 对齐再求和，与 E022-E031 完全同口径
            for c, out in zip(cues, outs):
                lab, _ = A.align(c['text'], c['gt'])
                tp += sum(1 for i, v in lab.items() if i < len(out) and out[i] != c['text'][i] and out[i] == v)
                fp += sum(1 for i, v in lab.items() if i < len(out) and out[i] != c['text'][i] and c['text'][i] == v)
                wr += sum(1 for i, v in lab.items() if i < len(out) and out[i] != c['text'][i]
                          and out[i] != v and c['text'][i] != v)
                dist += A.align(out, c['gt'])[1]
        else:
            # 切分行与 cue 不对齐：对拼接后的整段做一次对齐统计
            joined_out = ''.join(outs)
            lab, _ = A.align(src_full, gt_full)
            tp += sum(1 for i, v in lab.items() if i < len(joined_out) and joined_out[i] != src_full[i] and joined_out[i] == v)
            fp += sum(1 for i, v in lab.items() if i < len(joined_out) and joined_out[i] != src_full[i] and src_full[i] == v)
            wr += sum(1 for i, v in lab.items() if i < len(joined_out) and joined_out[i] != src_full[i]
                      and joined_out[i] != v and src_full[i] != v)
            dist = sum(A.align(joined_out[i:i + 40], gt_full[i:i + 40])[1]
                       for i in range(0, len(gt_full), 40)) if grouping == 'fixed40' else A.align(joined_out, gt_full)[1]
    return dict(tp=tp, fp=fp, wrong=wr, distance=dist)


res = {}
for path in sorted((R / 'asr').glob('*.gt.jsonl')):
    cues = [r for r in (json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip())
            if not r.get('discard')]
    for g in ('per-cue', 'whole', 'fixed40', 'single'):
        v = score(cues, g)
        agg = res.setdefault(g, dict(tp=0, fp=0, wrong=0, distance=0))
        for k in agg:
            agg[k] += v[k]
    print(path.stem, '完成', flush=True)

noop = sum(A.align(''.join(r['text'] for r in cues if not r.get('discard')),
                   ''.join(r['gt'] for r in cues if not r.get('discard')))[1]
           for path in sorted((R / 'asr').glob('*.gt.jsonl'))
           for cues in [ [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()] ])
print('\n=== 分句呈现对照（text_clean 全部用生产默认，不传参数）===')
for g, label in (('whole', 'B 整篇按 cue 换行（现有口径）'), ('per-cue', 'A 逐 cue 单独处理'),
                 ('fixed40', 'C 固定 40 字强行切行'), ('single', 'D 整篇合成一行')):
    v = res[g]
    print('  %-26s 改对字=%-4d 误改字=%-4d 错到错=%-4d 总错误量=%-5d 相对不纠错=%+d' % (
        label, v['tp'], v['fp'], v['wrong'], v['distance'], v['distance'] - noop))
print('  不纠错参照总距离 =', noop)
(O / 'segmentation.json').write_text(json.dumps(dict(arms=res, noop=noop), ensure_ascii=False, indent=1),
                                     encoding='utf-8')
