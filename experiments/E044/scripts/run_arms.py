#!/usr/bin/env python3
"""E044：按 E046 文档的方法复跑新架构与两个完全开卷臂。

臂：
  v1                 生产默认（C++，--no-index-cache）
  rag                新入口（RAG+N-gram+新公式，--research，有检索）
  rag_no_retrieval   新入口去掉检索（只留字符 4-gram 与判决）
  openbook           臂1：把真值句子做成临时证据库 + 照常检索（复用 Deepseek 的建包与 runner）
  perfect            臂2：不检索，直接把每条窗口所在的正确真值句当领域证据注入

不修改他们的脚本：用 import 后覆盖 PACKAGE/OUT 的方式调用，方法学保持一致。
含真值的 trace 全部写到 build/（被 .gitignore），不进仓库。
"""
import argparse, collections, hashlib, importlib.util, json, pathlib, subprocess, sys, time

R = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(R / 'tools'))
sys.path.insert(0, str(R / 'experiments/E024/scripts'))
sys.stdout.reconfigure(encoding='utf-8')
from rag_clean import Cleaner          # noqa: E402
from align_lib import align            # noqa: E402

EXE = R / 'build/e035/text_clean.exe'
OUT = R / 'experiments/E044/results'
TRACE = R / 'build/e044_probe/traces'


def load_rows():
    vids = {}
    for f in sorted((R / 'asr').glob('*.gt.jsonl')):
        rows = [json.loads(s) for s in f.read_text('utf-8').splitlines() if s.strip()]
        vids[f.stem] = [r for r in rows if not r.get('discard')]
    return vids


def score(body, out, rows):
    labels, offset = {}, 0
    for r in rows:
        lab, _ = align(r['text'], r['gt'])
        labels.update({offset + i: v for i, v in lab.items()})
        offset += len(r['text']) + 1
    c = collections.Counter(TP=0, FP=0, wrong=0)
    for i, v in labels.items():
        if out[i] != body[i]:
            c['TP' if out[i] == v else 'FP' if body[i] == v else 'wrong'] += 1
    return dict(counts=dict(c), distance=sum(align(l, r['gt'])[1] for l, r in zip(out.splitlines(), rows)),
                remaining_original_errors=sum(body[i] != v for i, v in labels.items()) - c['TP'])


def run_python_arm(name, package, mod_path, overrides):
    """用 Deepseek 的原脚本跑开卷臂，只覆盖包路径与输出目录。"""
    spec = importlib.util.spec_from_file_location('arm_' + name, mod_path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    argv = sys.argv
    sys.argv = [str(mod_path)]
    try:
        spec.loader.exec_module(m)
        for k, v in overrides.items():
            setattr(m, k, v)
        m.main()
    finally:
        sys.argv = argv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--package', required=True)
    ap.add_argument('--arms', required=True, help='逗号分隔：v1,rag,rag_no_retrieval,openbook,perfect')
    ap.add_argument('--openbook-dir', default='', help='臂1 用的临时真值包目录')
    ap.add_argument('--tag', default='pkg')
    a = ap.parse_args()
    pkg = pathlib.Path(a.package)
    OUT.mkdir(parents=True, exist_ok=True)
    TRACE.mkdir(parents=True, exist_ok=True)
    vids = load_rows()
    results = {}

    for arm in [x for x in a.arms.split(',') if x]:
        per_video = {}
        t0 = time.perf_counter()
        if arm == 'v1':
            for v, rows in vids.items():
                body = '\n'.join(r['text'] for r in rows) + '\n'
                out = subprocess.run([str(EXE), '--no-index-cache'], input=body.encode('utf-8'),
                                     capture_output=True, check=True, cwd=R).stdout.decode('utf-8')
                per_video[v] = score(body, out, rows)
        elif arm in ('rag', 'rag_no_retrieval'):
            c = Cleaner(pkg, EXE, research=True, use_retrieval=(arm == 'rag'))
            for v, rows in vids.items():
                body = '\n'.join(r['text'] for r in rows) + '\n'
                c.store.cache.clear()
                r = c.clean(body)
                res = score(body, r['text'], rows)
                res.update(edits=len(r['edits']), windows=len(r['windows']))
                (TRACE / ('%s.%s.%s.json' % (a.tag, arm, v))).write_text(json.dumps(r, ensure_ascii=False), encoding='utf-8')
                per_video[v] = res
            c.store.db.close()
            del c
        elif arm == 'openbook':
            run_python_arm('openbook', pkg, R / 'experiments/E046/scripts/build_openbook_package.py',
                           {'SRC': pkg, 'OUT': pathlib.Path(a.openbook_dir)})
            run_python_arm('openbook_run', pkg, R / 'experiments/E046/scripts/run_openbook.py',
                           {'PACKAGE': pathlib.Path(a.openbook_dir), 'OUT': TRACE})
            summ = json.loads((TRACE / 'openbook.json').read_text('utf-8'))
            per_video = {k: dict(counts=v['counts'], distance=v['distance'],
                                 remaining_original_errors=v['remaining_original_errors'])
                         for k, v in summ['videos'].items()}
        elif arm == 'perfect':
            run_python_arm('perfect', pkg, R / 'experiments/E046/scripts/run_perfect_evidence.py',
                           {'PACKAGE': pkg, 'OUT': TRACE})
            summ = json.loads((TRACE / 'perfect.json').read_text('utf-8'))
            per_video = {k: dict(counts=v['counts'], distance=v['distance'],
                                 remaining_original_errors=v['remaining_original_errors'])
                         for k, v in summ['videos'].items()}
        counts = collections.Counter()
        for v in per_video.values():
            counts.update(v['counts'])
        results[arm] = dict(counts=dict(counts), distance=sum(v['distance'] for v in per_video.values()),
                            remaining=sum(v['remaining_original_errors'] for v in per_video.values()),
                            seconds=round(time.perf_counter() - t0, 1), by_video=per_video)
        print('%-16s %s 距离 %d 剩余原错 %d 用时 %.0fs' % (
            arm, dict(counts), results[arm]['distance'], results[arm]['remaining'], results[arm]['seconds']), flush=True)

    out = dict(tag=a.tag, package=str(pkg), package_manifest=json.loads((pkg / 'manifest.json').read_text('utf-8')),
               candidate_table_sha=hashlib.sha256((R / 'data/correction/candidates.tsv').read_bytes()).hexdigest(),
               frontend_sha=hashlib.sha256(EXE.read_bytes()).hexdigest(), arms=results,
               scope='七篇全开卷；参数与 E038/E042 一致 a=0 β=1 κ=10 ρ=1 α=.01 H=30 检索50段；无标题简介')
    (OUT / ('arms_%s.json' % a.tag)).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('写出', OUT / ('arms_%s.json' % a.tag))


if __name__ == '__main__':
    main()
