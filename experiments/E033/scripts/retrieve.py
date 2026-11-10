#!/usr/bin/env python3
"""E033 第三步修复版：可靠的查询词 + 必须共现的检索 + 按文档去重的词形计数 + 明确弃权。

四处修复对应上一轮查出的四个坑：
  (a) 切块留重叠（build_kb 已改，这里只消费）；
  (b) 三字以上词展开成单字相邻短语查询（build_kb 的 token 流是"先全部单字、再全部二字串"，
      所以 "桑 弘 羊" 这种短语正好落在单字块上，相邻即命中）；
  (c) 查询词不能从含错原文里随便挑：这里只取 **whisper 与 FunASR 两个字都写一致**的连续片段，
      并按资料库里的文档频率卡一个带（太稀有多半是 ASR 噪声，太常见没有区分力）；
  (d) 判决不再看"top5 里有没有目标词"，改成两阶段：先用上下文取回一批同主题资料段，
      再在这批段里数 target 与 alias 各自出现在多少份**独立文档**里；样本不足直接弃权（未知）。
每个位点还带一个自证对照（直接拿词当查询）和一个错领域对照。
"""
import difflib, json, pathlib, sqlite3, sys

R = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(R / 'experiments/E033/scripts'))
from build_kb import norm  # noqa: E402
sys.stdout.reconfigure(encoding='utf-8')

DB = R / 'build/e033_kb/kb.sqlite'
CASES = [('BV1uUak6pEdK', '魏清', '卫青'), ('BV1uUak6pEdK', '桑红阳', '桑弘羊'),
         ('BV1uUak6pEdK', '填富', '田赋'), ('BV1uUak6pEdK', '现关', '县官')]
K = 300                 # 取回多少段同主题资料
USE_ALIAS = '--no-alias' not in sys.argv      # 异写归一可整体关掉做消融
MIN_DOCS = 2            # 少于这个独立文档数不成立
BAND = (3, 5000)        # 查询串的文档频率带：太稀有当噪声，太常见无区分力


def asr_and_truth(stem):
    rows = [r for r in (json.loads(l) for l in (R / 'asr' / (stem + '.gt.jsonl')).read_text(encoding='utf-8')
                        .splitlines() if l.strip()) if not r.get('discard')]
    return ''.join(r['text'] for r in rows), ''.join(r['gt'] for r in rows)


def whisper_chars(stem):
    d = json.loads((R / 'whisper-test/segments' / (stem + '_whole.json')).read_text(encoding='utf-8'))
    return norm(''.join(s['text'] for s in d['transcription']))


def funasr_chars(stem):
    return norm(json.loads((R / 'D:/FunASR/out' / (stem + '.json')).read_text(encoding='utf-8'))['text'])


def agree_flags(src, other):
    """src 每个字符是否在另一个模型的输出里也以同样写法出现（对齐后的逐位一致）。"""
    flags = [False] * len(src)
    sm = difflib.SequenceMatcher(None, src, other, autojunk=False)
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            flags[a + k] = True      # a 是 src（原始 ASR）里的下标
    return flags


def reliable_runs(text, flags, min_len=6):
    """连续被两个模型共同确认的片段（这些字才配当查询词）。"""
    runs, cur = [], []
    for i, ch in enumerate(text):
        if flags[i] and ch != ' ':
            cur.append(ch)
        else:
            if len(cur) >= min_len:
                runs.append(''.join(cur))
            cur = []
    if len(cur) >= min_len:
        runs.append(''.join(cur))
    return runs


def terms(runs, df):
    out = []
    for r in runs:
        for i in range(len(r) - 1):
            g = r[i:i + 2]
            if BAND[0] <= df(g) <= BAND[1] and g not in out:
                out.append(g)
    return out


def alias_map():
    f = R / 'build/e033_kb/alias_forms.tsv'
    out = {}
    if not f.exists():
        return out
    for line in f.read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.startswith('#') or line.startswith('target'):
            continue
        t, v = line.split('	')[0], line.split('	')[1]
        out.setdefault(t, []).append(v)
    return out


def main():
    db = sqlite3.connect(DB)
    AM = alias_map()

    def df(g):
        q = '"%s"' % (' '.join(g) if len(g) > 2 else g)
        return db.execute('select count(*) from kb where kb match ?', (q,)).fetchone()[0]

    def docs_of(gram, seg_ids, expand=True):
        """取回段里出现该词形（含已审定的异写/简称）的独立文档数。"""
        if not seg_ids:
            return 0, []
        forms = [gram] + (AM.get(gram, []) if (expand and USE_ALIAS) else [])
        ph = ','.join(str(x) for x in seg_ids)
        got = set()
        for g in forms:
            q = ' '.join(g) if len(g) > 2 else g
            got |= {r[0] for r in db.execute(
                'select distinct doc_id from segs join kb on kb.rowid=segs.seg_id '
                'where kb match ? and segs.seg_id in (%s)' % ph, ('"%s"' % q,))}
        return len(got), [g for g in forms if g != gram]

    report = []
    for stem, alias, target in CASES:
        asr, gt = asr_and_truth(stem)
        n_asr = norm(asr)
        pos = n_asr.find(norm(alias))
        flags = [a and b for a, b in zip(agree_flags(n_asr, whisper_chars(stem)),
                                         agree_flags(n_asr, funasr_chars(stem)))]
        left = n_asr[max(0, pos - 90):pos]
        right = n_asr[pos + len(norm(alias)):pos + len(norm(alias)) + 90]
        runs = reliable_runs(left, flags) + reliable_runs(right, flags)
        tk = terms(runs, df)
        print('【%s】%s → %s' % (stem, alias, target))
        print('  疑点原文（已遮住）: …%s ▢%s… ' % (left[-22:], right[:22]))
        print('  两模型一致可用的查询片段 %d 段，进入查询的二字串 %d 个（文档频率带 %s）' % (len(runs), len(tk), BAND))
        print('    例如 %s' % ' '.join(tk[:12]))
        if len(tk) < 3:
            print('  判定：未知（可靠查询词不足，弃权）\n')
            report.append(dict(case=alias, verdict='未知(查询词不足)'))
            continue
        match = ' OR '.join('"%s"' % t for t in tk[:120])
        segs = [r[0] for r in db.execute(
            'select kb.rowid from kb join segs on segs.seg_id=kb.rowid join docs on docs.doc_id=segs.doc_id '
            'where kb match ? and docs.domain=? order by bm25(kb) limit ?', (match, '历史', K)).fetchall()]
        if len(segs) < 20:
            print('  取回资料段 %d 条 < 20 → 判定：未知（资料不足，弃权）\n' % len(segs))
            report.append(dict(case=alias, verdict='未知(资料不足)', segs=len(segs)))
            continue
        dt, used = docs_of(target, segs)
        da, _ = docs_of(alias, segs, expand=False)
        verdict = '支持改' if dt >= MIN_DOCS and dt >= 2 * max(1, da) else ('反对改（别名更常见）' if da > dt else '未知（差距太小）')
        print('  取回资料段 %d 条；出现目标词「%s」的独立文档 %d 份%s，出现别名「%s」的 %d 份' % (
            len(segs), target, dt, ('（已计入异写/简称 %s）' % '、'.join(used)) if used else '', alias, da))
        print('  判定：%s' % verdict)
        for r in db.execute('select docs.work, substr(segs.text_norm,1,52) from segs join docs on docs.doc_id=segs.doc_id '
                            'join kb on kb.rowid=segs.seg_id where kb match ? and segs.seg_id in (%s) order by bm25(kb) limit 2'
                            % ','.join(map(str, segs[:80])), ('"%s"' % (' '.join(target) if len(target) > 2 else target),)):
            print('     出处[%s] %s' % (r[0][:16], r[1]))
        # 对照一：直接拿词当查询（自证，不能当证据）；对照二：拿现代日常话查历史库
        n_self = db.execute('select count(*) from kb where kb match ?', ('"%s"' % alias,)).fetchone()[0]
        ctx_bad = ' '.join(norm('今天中午吃什么好我们随便聊聊这个项目进度还行'))
        n_ctrl = db.execute('select count(*) from kb join segs on segs.seg_id=kb.rowid '
                            'join docs on docs.doc_id=segs.doc_id where kb match ? and docs.domain=?',
                            (' OR '.join('"%s"' % g for g in ('今天', '中午', '项目')), '历史')).fetchone()[0]
        print('  对照：直接查别名「%s」全库命中 %d 段（自证，不计入）；无关现代话查历史库返回 %d 段（说明必须有阈值）' % (alias, n_self, n_ctrl))
        print()
        report.append(dict(case=alias, target=target, terms=len(tk), segs=len(segs),
                           docs_target=dt, docs_alias=da, verdict=verdict, self_hit=n_self, ctrl_hit=n_ctrl))
    (R / 'experiments/E033/results/retrieve_fixed.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    ok = sum(1 for r in report if str(r.get('verdict', '')).startswith('支持'))
    unk = sum(1 for r in report if str(r.get('verdict', '')).startswith('未知'))
    print('四个位点汇总：支持改 %d，未知/弃权 %d，其余 %d' % (ok, unk, len(report) - ok - unk))


if __name__ == '__main__':
    main()
