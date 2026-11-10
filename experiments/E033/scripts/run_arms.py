#!/usr/bin/env python3
"""E033 第一步的判决：上下文表保留句内边界之后，纠错结果变了多少。

只动一张表，其余全部用生产默认（V1：M1 字频补缺 + M2 封顶 + 单边上下文）。
两臂基线先断言再往下跑：默认 = 145 改对 / 82 误改 / 25 错到错 / 1961 总错误量；
关上下文 = 147 / 100 / 27 / 1977。对不上就说明环境或词库被改过，停手先查。
"""
import collections, json, pathlib, subprocess, sys

R = pathlib.Path(__file__).resolve().parents[3]
O = R / 'experiments/E033/results'
O.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(R / 'experiments/E024/scripts'))
import align_lib as A
sys.stdout.reconfigure(encoding='utf-8')

EXE = 'build/e025/text_clean.exe'
# 2026-11-10 园长批准把正式上下文表换成"保留句内边界"版，基线随之从 145/82/25/1961 变成 145/83/25/1962。
# 旧口径表用 --context-dir 显式指回复现，作为对照继续断言，方向写死在这里，防止以后有人误以为换表赚了分。
ARMS = [
    ('A0 生产默认（正式表已保留边界）', [], (145, 83, 25, 1962)),
    ('A1 旧口径（不保留边界，已替换）', ['--context-dir', 'build/e033_ctx_repro'], (145, 82, 25, 1961)),
    ('A2 关掉上下文证据', ['--no-ctx-evidence'], (147, 100, 27, 1977)),
]


def load():
    vids = {}
    for f in sorted((R / 'asr').glob('*.gt.jsonl')):
        kept = [r for r in (json.loads(l) for l in f.read_text(encoding='utf-8').splitlines() if l.strip())
                if not r.get('discard')]
        body = '\n'.join(r['text'] for r in kept) + '\n'
        labels, off = {}, 0
        for r in kept:
            lab, _ = A.align(r['text'], r['gt'])
            labels.update({off + k: v for k, v in lab.items()})
            off += len(r['text']) + 1
        vids[f.stem] = (body, labels, kept)
    return vids


def main():
    vids = load()
    res, edits = {}, {}
    for name, extra, frozen in ARMS:
        tp = fp = wr = dist = 0
        comp = collections.Counter()
        per = {}
        for stem, (body, labels, kept) in vids.items():
            p = subprocess.run([EXE, '--no-index-cache', '-v'] + extra, input=body.encode('utf-8'),
                               capture_output=True, cwd=str(R))
            assert p.returncode == 0, p.stderr.decode('utf-8', 'replace')[:300]
            out, err = p.stdout.decode(), p.stderr.decode()
            t = sum(1 for i, v in labels.items() if out[i] != body[i] and out[i] == v)
            f_ = sum(1 for i, v in labels.items() if out[i] != body[i] and body[i] == v)
            w = sum(1 for i, v in labels.items() if out[i] != body[i] and out[i] != v and body[i] != v)
            d = sum(A.align(l, r['gt'])[1] for l, r in zip(out.splitlines(), kept))
            tp += t; fp += f_; wr += w; dist += d
            per[stem] = (t, f_, w, d)
            for m in A.rx.finditer(err):
                kind, a, b, src, dst, dd, sc, zc, zo = m.groups()
                a = int(a)
                fix = brk = bad = 0
                for i in range(len(src)):
                    if src[i] == dst[i]:
                        continue
                    t2 = labels.get(a + i)
                    if t2 is None:
                        continue
                    if dst[i] == t2:
                        fix += 1
                    elif src[i] == t2:
                        brk += 1
                    else:
                        bad += 1
                comp['纯改对' if brk == 0 and bad == 0 else '纯改坏' if fix == 0 and bad == 0 else '混合'] += 1
            edits.setdefault(name, {})[stem] = out
        res[name] = dict(tp=tp, fp=fp, wrong=wr, distance=dist, comp=dict(comp), per=per)
        if frozen:
            assert (tp, fp, wr, dist) == frozen, ('冻结值对不上: %s %s' % (name, (tp, fp, wr, dist)))
        print('%-24s 改对=%-4d 误改=%-4d 错到错=%-4d 总错误量=%-5d 构成=%s' % (
            name, tp, fp, wr, dist, dict(comp)), flush=True)
    base = res['A0 生产默认（正式表已保留边界）']
    print('\n=== 相对 A0（总错误量越低越好；不纠错=2024）===')
    for name, v in res.items():
        print('  %-24s 改对%+d 误改%+d 错到错%+d 总错误量%+d' % (
            name, v['tp'] - base['tp'], v['fp'] - base['fp'], v['wrong'] - base['wrong'],
            v['distance'] - base['distance']))
    print('\n=== 每篇明细（改对/误改/错到错/总错误量）===')
    for stem in vids:
        print('  %-20s A0=%s A2=%s' % (stem, res['A0 生产默认（正式表已保留边界）']['per'][stem],
                                       res['A1 旧口径（不保留边界，已替换）']['per'][stem]))
    (O / 'arms.json').write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
    (O / 'texts.json').write_text(json.dumps({k: v for k, v in edits.items()}, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
