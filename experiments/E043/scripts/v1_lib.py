#!/usr/bin/env python3
"""候选表 V1 对照工具：把 data/ 硬链接镜像成指定表的目录，跑七篇 V1 并按位点比差值。

不复制 data/（几百 MB），用 os.link；镜像目录只放不同的 candidates.tsv。
不触碰园长工作文件，也不改评分口径（沿用 experiments/E024/scripts/align_lib.py 的数字归一与唯一对齐）。
"""
import collections, json, os, pathlib, shutil, subprocess, sys

R = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(R / 'experiments/E024/scripts'))
sys.stdout.reconfigure(encoding='utf-8')
from align_lib import align     # noqa: E402

EXE = R / 'build/e035/text_clean.exe'


def mirror(dst, candidates_text):
    """在 dst 造一个与 data/ 同构的目录，只把 candidates.tsv 换成给定内容。"""
    dst = pathlib.Path(dst)
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for p in (R / 'data').rglob('*'):
        if not p.is_file():
            continue
        rel = p.relative_to(R / 'data')
        keep = dst / rel
        keep.parent.mkdir(parents=True, exist_ok=True)
        if str(rel).replace('\\', '/') == 'correction/candidates.tsv':
            keep.write_text(candidates_text, encoding='utf-8', newline='\n')
        else:
            os.link(p, keep)
    return dst


def run(data_dir):
    per_video, edits = {}, []
    for f in sorted((R / 'asr').glob('*.gt.jsonl')):
        rows = [json.loads(s) for s in f.read_text('utf-8').splitlines()
                if s.strip() and not json.loads(s).get('discard')]
        body = '\n'.join(r['text'] for r in rows) + '\n'
        out = subprocess.run([str(EXE), '--no-index-cache', '--data-dir', str(data_dir)],
                             input=body.encode('utf-8'), capture_output=True, check=True,
                             cwd=R).stdout.decode('utf-8')
        assert len(body) == len(out), '输出长度必须与输入一致'
        labels, offset = {}, 0
        for r in rows:
            lab, _ = align(r['text'], r['gt'])
            labels.update({offset + i: v for i, v in lab.items()})
            offset += len(r['text']) + 1
        c = collections.Counter(TP=0, FP=0, wrong=0)
        for i, v in labels.items():
            if out[i] != body[i]:
                c['TP' if out[i] == v else 'FP' if body[i] == v else 'wrong'] += 1
                edits.append((f.stem, i, body[i], out[i], v))
        per_video[f.stem] = dict(counts=c, distance=sum(align(l, r['gt'])[1]
                                                        for l, r in zip(out.splitlines(), rows)))
    counts = collections.Counter()
    for v in per_video.values():
        counts.update(v['counts'])
    return dict(counts=counts, distance=sum(v['distance'] for v in per_video.values()),
                edits=edits, by_video=per_video)


def classify(e):
    _video, _pos, src, out, gt = e
    return '改对' if out == gt else ('误改' if src == gt else '错到错')


def diff(before, after, label=('前', '后')):
    kb = {(e[0], e[1]): e for e in before['edits']}
    ka = {(e[0], e[1]): e for e in after['edits']}
    lost = [kb[k] for k in kb if k not in ka]
    gained = [ka[k] for k in ka if k not in kb]
    print('%s：%s 距离 %d    %s：%s 距离 %d' % (
        label[0], dict(before['counts']), before['distance'], label[1], dict(after['counts']), after['distance']))
    print('  消失 %d（%s）  新增 %d（%s）' % (
        len(lost), dict(collections.Counter(classify(e) for e in lost)),
        len(gained), dict(collections.Counter(classify(e) for e in gained))))
    for name, arr in (('消失', lost), ('新增', gained)):
        for e in arr:
            print('    %s %-16s 位点%-6d %s→%s（真值 %s）%s' % (
                name, e[0][:16], e[1], e[2], e[3], e[4], classify(e)))
    return lost, gained


def git_head_table():
    return subprocess.run(['git', 'show', 'HEAD:data/correction/candidates.tsv'],
                          capture_output=True, cwd=R, check=True).stdout.decode('utf-8')
