#!/usr/bin/env python3
"""第五臂：错领域资料 与 随机资料 的假阳性对照。

命题：如果"检索证据"真的在起作用，那么把资料换成错领域或随机抽样后，支持率必须明显掉下来；
掉不下来说明它只是一个词频偏置，不是理解上下文。
位点自动从正式候选表 + 七篇原始 ASR/真值里找（别名出现在 ASR、目标词出现在真值，两者同长度），
历史片用历史库，其余用现代库；同一批位点跑三臂：正确领域 / 错领域 / 随机 K 段（3 个固定种子）。
"""
import json, pathlib, random, sqlite3, sys

R = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(R / 'experiments/E033/scripts'))
from build_kb import norm  # noqa: E402
from retrieve import agree_flags, reliable_runs, terms, asr_and_truth, whisper_chars, funasr_chars  # noqa: E402
sys.stdout.reconfigure(encoding='utf-8')
import itertools

DB = R / 'build/e033_kb/kb.sqlite'
K, MIN_DOCS = 300, 2
HIST_FILE = 'BV1uUak6pEdK'
SEEDS = (7, 21, 99)


def load_pairs():
    lines = [l.rstrip('\n').split('\t') for l in (R / 'data/correction/candidates.tsv').read_text(encoding='utf-8')
             .splitlines() if l.strip() and not l.startswith('#')]
    head, body = lines[0], lines[1:]
    ci, ai, si = head.index('canonical'), head.index('alias'), head.index('status')
    return [(r[ci], r[ai]) for r in body if r[si] == '1']


def sites(db):
    out = []
    for f in sorted((R / 'asr').glob('*.gt.jsonl')):
        stem = f.stem[:-3]
        asr, gt = asr_and_truth(stem)
        n_asr, n_gt = norm(asr), norm(gt)
        if len(n_asr) < 200:
            continue
        dom = '历史' if stem == HIST_FILE else '现代'
        for target, alias in load_pairs():
            if len(alias) != len(target) or alias == target:
                continue
            pa, pt = n_asr.find(alias), n_gt.find(target)
            if pa < 0 or pt < 0:
                continue
            out.append(dict(stem=stem, domain=dom, target=target, alias=alias, pos=pa))
    print('自动定位到 %d 个位点（历史 %d，现代 %d）' % (
        len(out), sum(1 for x in out if x['domain'] == '历史'), sum(1 for x in out if x['domain'] == '现代')))
    return out


_AGREE = {}
_DF = {}


def agree_map(stem):
    """同一篇只做一次全篇对齐（每篇 3 万次字符比较，逐位点重做就是这一轮全部的耗时来源）。"""
    if stem not in _AGREE:
        asr, _ = asr_and_truth(stem)
        n_asr = norm(asr)
        _AGREE[stem] = [a and b for a, b in zip(agree_flags(n_asr, whisper_chars(stem)),
                                                agree_flags(n_asr, funasr_chars(stem)))]
    return _AGREE[stem]


def q_terms(db, s):
    asr, _ = asr_and_truth(s['stem'])
    n_asr = norm(asr)
    pos = n_asr.find(s['alias'])
    flags = agree_map(s['stem'])
    left, right = n_asr[max(0, pos - 90):pos], n_asr[pos + len(s['alias']):pos + len(s['alias']) + 90]
    return terms(reliable_runs(left, flags) + reliable_runs(right, flags), lambda g: df(db, g))


def df(db, g):
    if g not in _DF:
        q = '"%s"' % (' '.join(g) if len(g) > 2 else g)
        _DF[g] = db.execute('select count(*) from kb where kb match ?', (q,)).fetchone()[0]
    return _DF[g]


def docs_with(db, seg_ids, form):
    if not seg_ids:
        return 0
    q = '"%s"' % (' '.join(form) if len(form) > 2 else form)
    ph = ','.join(map(str, seg_ids))
    return db.execute('select count(distinct doc_id) from segs join kb on kb.rowid=segs.seg_id '
                      'where kb match ? and segs.seg_id in (%s)' % ph, (q,)).fetchone()[0]


def retrieve(db, tk, domain):
    if len(tk) < 3:
        return []
    match = ' OR '.join('"%s"' % t for t in tk[:120])
    return [r[0] for r in db.execute(
        'select kb.rowid from kb join segs on segs.seg_id=kb.rowid join docs on docs.doc_id=segs.doc_id '
        'where kb match ? and docs.domain=? order by bm25(kb) limit ?', (match, domain, K)).fetchall()]


_RCACHE = {}


def random_segs(db, domain, seed):
    key = (domain, seed)
    if key not in _RCACHE:
        ids = [r[0] for r in db.execute('select segs.seg_id from segs join docs on docs.doc_id=segs.doc_id '
                                        'where docs.domain=?', (domain,))]
        _RCACHE[key] = random.Random(seed).sample(ids, min(K, len(ids)))
    return _RCACHE[key]


def main():
    db = sqlite3.connect(DB)
    st = sites(db)
    res = []
    for s in st:
        tk = q_terms(db, s)
        if len(tk) < 3:
            continue
        good = retrieve(db, tk, s['domain'])
        bad = retrieve(db, tk, '现代' if s['domain'] == '历史' else '历史')
        rows = dict(stem=s['stem'], domain=s['domain'], target=s['target'], alias=s['alias'], terms=len(tk),
                    segs=len(good))
        for name, segs in (('正确领域', good), ('错领域', bad)):
            dt, da = docs_with(db, segs, s['target']), docs_with(db, segs, s['alias'])
            rows[name] = (dt, da, dt >= MIN_DOCS and dt >= 2 * max(1, da))
        rnd = []
        for seed in SEEDS:
            segs = random_segs(db, s['domain'], seed)
            dt, da = docs_with(db, segs, s['target']), docs_with(db, segs, s['alias'])
            rnd.append((dt, da, dt >= MIN_DOCS and dt >= 2 * max(1, da)))
        rows['随机'] = rnd
        res.append(rows)
        if len(res) % 25 == 0:
            print('   ...已完成 %d 个位点，正确领域支持 %d' % (len(res), sum(1 for r in res if r['正确领域'][2])), flush=True)
        print('  %-16s %s %s→%s 查询串 %3d 段 %3d ｜正确领域 %s ｜错领域 %s ｜随机 %s' % (
            s['stem'], s['domain'], s['alias'], s['target'], len(tk), len(good),
            rows['正确领域'], rows['错领域'], [(a, b, ok) for a, b, ok in rnd]), flush=True)

    def rate(k):
        return sum(1 for r in res if r[k][2])

    rnd_ok = sum(1 for r in res for _, _, ok in r['随机'] if ok)
    print('\n=== 汇总（位点 %d 个）===' % len(res))
    print('  正确领域检索：判"支持改" %d / %d = %.0f%%' % (rate('正确领域'), len(res), 100.0 * rate('正确领域') / len(res)))
    print('  错领域检索　 ：判"支持改" %d / %d = %.0f%%' % (rate('错领域'), len(res), 100.0 * rate('错领域') / len(res)))
    print('  随机抽样资料 ：判"支持改" %d / %d = %.0f%%（每个位点 3 个种子）' % (
        rnd_ok, 3 * len(res), 100.0 * rnd_ok / (3 * len(res))))
    (R / 'experiments/E033/results/control_arms.json').write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
