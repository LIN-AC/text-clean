#!/usr/bin/env python3
"""E031 上下文评分对照：语料（现代/文言/合并）× 锚点跨度（1字/2字）× 权重。

评价指标除了改对字/误改字/错到错/总错误量，还单列编辑构成
（纯改对 / 纯改坏=把本来写对的字改掉 / 混合），这是 E029 学到的：
只看未修复样本会严重低估代价。控制臂与 X2 的冻结值先断言再往下跑。
"""
import collections, json, pathlib, subprocess, sys

R = pathlib.Path(__file__).resolve().parents[3]
O = R / 'experiments/E031/results'
O.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(R / 'experiments/E024/scripts'))
import align_lib as A
sys.stdout.reconfigure(encoding='utf-8')

EXE = 'build/e025/text_clean.exe'
CTRL = ['--missing-evidence', 'char', '--missing-cap', '0.6']
CTX = lambda d, span, w: CTRL + ['--evidence-dir', 'build/e031_ctx_' + d, '--ctx-evidence',
                                 '--ctx-span', str(span), '--ctx-weight', str(w)]
ARMS = [
    ('S0 控制臂（不接上下文）', CTRL, (147, 100, 1977)),
    # E030 的 X2 是 158/104/1970，但那张 pairs 表是按整篇连读的；本实验的文言表按 400 字分块，
    # 跨块邻接被切断，所以只作参照、不作断言（断言会让不同表互相打脸）。
    ('S1 文言 跨度1 权重0.5', CTX('classic', 1, 0.5), None),
    ('S2 文言 跨度2 权重0.5', CTX('classic', 2, 0.5), None),
    ('S3 文言 跨度2 权重1.0', CTX('classic', 2, 1.0), None),
    ('S4 现代 跨度1 权重1.0', CTX('modern', 1, 1.0), None),
    ('S5 现代 跨度2 权重0.5', CTX('modern', 2, 0.5), None),
    ('S6 现代 跨度2 权重1.0', CTX('modern', 2, 1.0), None),
    ('S7 合并 跨度2 权重0.5', CTX('both', 2, 0.5), None),
    ('S8 合并 跨度2 权重1.0', CTX('both', 2, 1.0), None),
    ('V1 现代 跨度2 单边 w1.0', CTX('modern', 2, 1.0) + ['--ctx-one-sided'], None),
    ('V2 现代 跨度2 单边 w0.5', CTX('modern', 2, 0.5) + ['--ctx-one-sided'], None),
    ('V3 文言 跨度1 单边 w1.0', CTX('classic', 1, 1.0) + ['--ctx-one-sided'], None),
    ('V4 合并 跨度2 单边 w1.0', CTX('both', 2, 1.0) + ['--ctx-one-sided'], None),
    ('V5 合并 跨度2 单边 w2.0', CTX('both', 2, 2.0) + ['--ctx-one-sided'], None),
    ('W1 历史词频 gap0.45（E030 最优档）', CTRL + ['--evidence-dir', 'build/e031_ctx_mod_dom', '--domain-freq', '--domain-gap', '0.45'], None),
    ('W2 历史词频0.45 + 单边上下文', CTRL + ['--evidence-dir', 'build/e031_ctx_mod_dom', '--domain-freq', '--domain-gap', '0.45', '--ctx-evidence', '--ctx-span', '2', '--ctx-weight', '1.0', '--ctx-one-sided'], None),
    ('W3 历史词频1.5 + 单边上下文', CTRL + ['--evidence-dir', 'build/e031_ctx_mod_dom', '--domain-freq', '--ctx-evidence', '--ctx-span', '2', '--ctx-weight', '1.0', '--ctx-one-sided'], None),
    ('W4 历史词频1.5 + 合并单边 w2.0', CTRL + ['--evidence-dir', 'build/e031_ctx_both_dom', '--domain-freq', '--ctx-evidence', '--ctx-span', '2', '--ctx-weight', '2.0', '--ctx-one-sided'], None),
    ('W5 历史词频0.45 + 合并单边 w2.0', CTRL + ['--evidence-dir', 'build/e031_ctx_both_dom', '--domain-freq', '--domain-gap', '0.45', '--ctx-evidence', '--ctx-span', '2', '--ctx-weight', '2.0', '--ctx-one-sided'], None),
]
SPECIAL = {('魏清', '卫青'), ('桑红阳', '桑弘羊'), ('丧红阳', '桑弘羊'),
           ('填富', '田赋'), ('填付', '田赋'), ('现关', '县官')}

vids = {}
for f in sorted((R / 'asr').glob('*.gt.jsonl')):
    kept = [json.loads(l) for l in f.read_text(encoding='utf-8').splitlines() if l.strip()]
    kept = [r for r in kept if not r.get('discard')]
    body = '\n'.join(r['text'] for r in kept) + '\n'
    labels, off = {}, 0
    for r in kept:
        lab, _ = A.align(r['text'], r['gt'])
        labels.update({off + k: v for k, v in lab.items()})
        off += len(r['text']) + 1
    vids[f.stem] = (body, labels, kept)

res = {}
for name, extra, frozen in ARMS:
    tp = fp = wr = dist = 0
    comp = collections.Counter()
    sp_ok, sp_no = {}, {}
    kinds = collections.Counter()
    mix_samples = []
    for stem, (body, labels, kept) in vids.items():
        p = subprocess.run([EXE, '--no-index-cache', '-v'] + extra, input=body.encode('utf-8'),
                           capture_output=True, cwd=str(R))
        assert p.returncode == 0, p.stderr.decode('utf-8', 'replace')[:300]
        out, err = p.stdout.decode(), p.stderr.decode()
        tp += sum(1 for i, v in labels.items() if out[i] != body[i] and out[i] == v)
        fp += sum(1 for i, v in labels.items() if out[i] != body[i] and body[i] == v)
        wr += sum(1 for i, v in labels.items() if out[i] != body[i] and out[i] != v and body[i] != v)
        dist += sum(A.align(l, r['gt'])[1] for l, r in zip(out.splitlines(), kept))
        for m in A.rx.finditer(err):
            kind, a, b, src, dst, d, sc, zc, zo = m.groups()
            a = int(a)
            kinds[{'exact': 'AC精确', 'pinyin': '拼音同音(d=0)', 'fuzzy': '近音(d≥1)'}.get(kind, kind)] += 1
            fix = brk = bad = 0
            for i in range(len(src)):
                if src[i] == dst[i]:
                    continue
                t = labels.get(a + i)
                if t is None:
                    continue
                if dst[i] == t:
                    fix += 1
                elif src[i] == t:
                    brk += 1
                else:
                    bad += 1
            comp['纯改对' if brk == 0 and bad == 0 else '纯改坏' if fix == 0 and bad == 0 else '混合'] += 1
            if (src, dst) in SPECIAL:
                # 按"词对"计数（同一词对在片中出现多次只算一组），与 E030 口径一致
                (sp_ok if out[a:a + len(src)] == dst else sp_no)[src + '→' + dst] = 1
            if brk and len(mix_samples) < 8:
                mix_samples.append((stem, a, src, dst, sc, 'brk=%d fix=%d' % (brk, fix)))
    if name in ('S5 现代 跨度2 权重0.5', 'S3 文言 跨度2 权重1.0'):
        print('   %s 破坏样本：' % name)
        for x in mix_samples:
            print('     %s:%d %s→%s score=%s %s' % (x[0][:14], x[1], x[2], x[3], x[4], x[5]))
    res[name] = dict(tp=tp, fp=fp, wrong=wr, distance=dist, comp=dict(comp), kinds=dict(kinds),
                     special_pairs_ok=sorted(sp_ok), special_pairs_no=sorted(sp_no))
    if frozen:
        assert (tp, fp, dist) == frozen, ('冻结值对不上: %s %s' % (name, (tp, fp, dist)))
    print('%-24s 改对=%-4d 误改=%-4d 错到错=%-4d 总错误量=%-5d(%+d) 构成=%s 卫青族改对词对数=%d 编辑种类=%s' % (
        name, tp, fp, wr, dist, dist - 2024, dict(comp), len(sp_ok), dict(kinds)), flush=True)

print('\n=== 相对控制臂 S0（总错误量越低越好；不纠错=2024）===')
base = res['S0 控制臂（不接上下文）']['distance']
for name, v in res.items():
    print('  %-24s 改对%+d 误改%+d 总错误量%+d（相对控制臂）' % (
        name, v['tp'] - res['S0 控制臂（不接上下文）']['tp'], v['fp'] - res['S0 控制臂（不接上下文）']['fp'],
        v['distance'] - base))
(O / 'compare_ctx.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
