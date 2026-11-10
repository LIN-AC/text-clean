#!/usr/bin/env python3
"""E033 第三步：验证二字实体倒排检索能用，并记录耗时。

三件事必须分开看（对应 Astra 报告 §4.2）：
  Q1 只拿"疑点两侧没被改过的文字"当查询 → 能不能取回真正相关的资料（这就是 RAG 该做的）；
  Q2 直接拿候选词本身当查询 → 必然命中含该词的资料，属于自证，不能当优势证据；
  Q3 拿错领域/无关上下文当查询 → 应该取不到相关资料，用来证明 Q1 的命中不是巧合。
本项目已有的疑难词对（魏清→卫青、桑红阳→桑弘羊、填富→田赋、现关→县官）从 asr 真值里自动定位上下文。
"""
import json, pathlib, sqlite3, sys, time

R = pathlib.Path(__file__).resolve().parents[3]
DB = R / 'build/e033_kb/kb.sqlite'
sys.path.insert(0, str(R / 'experiments/E033/scripts'))
from build_kb import norm, TS  # noqa: E402
sys.stdout.reconfigure(encoding='utf-8')

CASES = [('魏清', '卫青'), ('桑红阳', '桑弘羊'), ('填富', '田赋'), ('现关', '县官')]


def q_tokens(text):
    n = norm(text)
    runs = n.split(' ')
    tk = []
    for r in runs:
        tk += list(r) + [r[i:i + 2] for i in range(len(r) - 1)]
    return [t for t in tk if len(t) >= 2]        # 只用二字串查询（单字噪声太大）


def search(db, text, domain=None, k=5):
    toks = q_tokens(text)
    if not toks:
        return [], 0.0
    match = ' OR '.join('"%s"' % t for t in toks[:200])
    sql = ('select segs.seg_id, docs.domain, docs.work, docs.title, substr(segs.text_norm,1,60), '
           'bm25(kb) from kb join segs on segs.seg_id=kb.rowid join docs on docs.doc_id=segs.doc_id '
           'where kb match ? {} order by bm25(kb) limit ?').format('and docs.domain=?' if domain else '')
    t0 = time.perf_counter()
    rows = db.execute(sql, ((match, domain, k) if domain else (match, k))).fetchall()
    return rows, (time.perf_counter() - t0) * 1000


def contexts():
    """从七篇里找出这些词对出现的位点，返回（片名, 别名, 目标词, 左侧上下文, 右侧上下文）。

    别名只出现在**原始 ASR**（r['text']）里，真值 r['gt'] 已经是改正后的写法，所以要从 text 字段找。
    """
    out = []
    for f in sorted((R / 'asr').glob('*.gt.jsonl')):
        rows = [r for r in (json.loads(l) for l in f.read_text(encoding='utf-8').splitlines() if l.strip())
                if not r.get('discard')]
        text = ''.join(''.join(r['text'].split()) for r in rows)
        for alias, target in CASES:
            pos = text.find(alias)
            if pos >= 0:
                out.append((f.stem, alias, target, text[max(0, pos - 24):pos], text[pos + len(alias):pos + len(alias) + 24]))
    return out


def df(db, gram):
    return db.execute('select count(*) from kb where kb match ?', ('"%s"' % gram,)).fetchone()[0]


def run(db, match, domain, k=5):
    sql = ('select segs.seg_id, docs.domain, docs.work, docs.title, substr(segs.text_norm,1,60), bm25(kb) '
           'from kb join segs on segs.seg_id=kb.rowid join docs on docs.doc_id=segs.doc_id '
           'where kb match ? and docs.domain=? order by bm25(kb) limit ?')
    return db.execute(sql, (match, domain, k)).fetchall()


def main():
    db = sqlite3.connect(DB)
    for _, _, target, _, _ in contexts():
        print('  目标词「%s」在历史库里的段数 = %d' % (target, df(db, target)))
    print()
    cs = contexts()
    print('定位到 %d 个疑难位点\n' % len(cs))
    report = []
    for stem, alias, target, left, right in cs:
        ctx = left + right                       # 遮住疑点本身，只用两侧未改文字
        n1, t1 = search(db, ctx, '历史')
        # OR 查询永远有结果，等于没有弃权；再试两种必须共现的查询形式，看能否把"无关段"挤掉
        rare = sorted(set(q_tokens(ctx)), key=lambda g: df(db, g))[:2]
        rows_and = run(db, ' AND '.join('"%s"' % g for g in rare), '历史')
        rows_near = run(db, 'NEAR(%s, 60)' % ' '.join('"%s"' % g for g in rare), '历史')
        n2, t2 = search(db, alias, '历史')       # 自证查询
        n3, t3 = search(db, '今天中午吃什么好呢我们随便聊聊', '历史')   # 无关查询
        print('【%s】别名 %s → 目标 %s' % (stem, alias, target))
        print('  上下文（已遮住疑点）: %s ▢ %s' % (left, right))
        print('  Q1 只查上下文：命中 %d 条，含「%s」的 %d 条，耗时 %.1fms' % (
            len(n1), target, sum(1 for r in n1 if target in r[4]), t1))
        for r in n1[:3]:
            print('      [%s|%s] %s' % (r[1], (r[2] or '')[:14], r[4]))
        print('  Q2 直接查别名「%s」：命中 %d 条，耗时 %.1fms（这种命中不能当证据）' % (alias, len(n2), t2))
        print('  Q3 无关现代话查历史库：命中 %d 条，含「%s」的 %d 条，耗时 %.1fms' % (
            len(n3), target, sum(1 for r in n3 if target in r[4]), t3))
        print('  Q1c 最稀有两个二字串必须共现（AND）：%s → 命中 %d 条，含「%s」的 %d 条' % (
            rare, len(rows_and), target, sum(1 for r in rows_and if target in r[4])))
        print('  Q1d 最稀有两个二字串须邻近（NEAR60）→ 命中 %d 条，含「%s」的 %d 条' % (
            len(rows_near), target, sum(1 for r in rows_near if target in r[4])))
        for r in rows_near[:2]:
            print('      [%s|%s] %s' % (r[1], (r[2] or '')[:14], r[4]))
        print()
        report.append(dict(file=stem, alias=alias, target=target, left=left, right=right,
                           q1=len(n1), q1_with_target=sum(1 for r in n1 if target in r[4]), ms1=round(t1, 1),
                           q2=len(n2), ms2=round(t2, 1), q3=len(n3), ms3=round(t3, 1),
                           rare=rare, q1c=len(rows_and), q1c_target=sum(1 for r in rows_and if target in r[4]),
                           q1d=len(rows_near), q1d_target=sum(1 for r in rows_near if target in r[4]),
                           target_df=df(db, target),
                           top1=[[x for x in r] for r in n1[:3]]))
    print('汇总（四个位点）：OR 查询 top5 含目标词 %d 次；AND 必须共现 %d 次；NEAR 邻近 %d 次；'
          'AND/NEAR 直接 0 命中（可弃权）的位点 %d / %d' % (
              sum(1 for r in report if r['q1_with_target']), sum(1 for r in report if r['q1c_target']),
              sum(1 for r in report if r['q1d_target']),
              sum(1 for r in report if r['q1c'] == 0), len(report)))
    ms = [r['ms1'] for r in report] or [0.0]
    print('二字串倒排检索：单次查询耗时 最小 %.1fms / 中位 %.1fms / 最大 %.1fms（235MB 库，冷连接）' % (
        min(ms), sorted(ms)[len(ms) // 2], max(ms)))
    (R / 'experiments/E033/results/kb_probe.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
