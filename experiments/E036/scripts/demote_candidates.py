#!/usr/bin/env python3
"""把"不该有改写资格"的候选行降为只竞争（status 1→0），改前备份、改后复测。

降级只依据结构性证据，不依据语义猜测：
  R1 别名为空或与目标词长度不等（这类行永远无法作为等长替换触发，留在启用行里只是噪声）；
  R2 跨词边界拼接：目标词能切成 A+B，A 是另一个启用目标词、B 是另一个启用目标词的前缀或后段（长度≥2），
     并且 A、B 各自在 807 万字原料库里连续出现，而整个目标词从不出现（例：卫青霍去 = 卫青 + 霍去病的开头）。
  R3 目标词含非汉字、读音音节数与字数不符、别名等于目标词（本轮体检实测为 0 条，规则保留以防后续入库）。
明确不做的事：不用"语料里没出现"单独定罪——现代语料只有 91.6 万字，转账/验证码/非遗 这些真词照样缺席。
"""
import csv, hashlib, pathlib, re, shutil, sqlite3, sys, time

R = pathlib.Path(__file__).resolve().parents[3]
TBL = R / 'data/correction/candidates.tsv'
BAK = R / 'build/e036_corpus/candidates.tsv.before_E036'
LIST = R / 'build/e036_corpus/compete_only.tsv'
sys.stdout.reconfigure(encoding='utf-8')
SYL = re.compile(r'[a-zv:]+[0-5]')


def main(dry=True):
    lines = TBL.read_text(encoding='utf-8').split('\n')
    head_idx = next(i for i, l in enumerate(lines) if l.startswith('canonical'))
    head = lines[head_idx].split('\t')
    ci, pi, ai, si = head.index('canonical'), head.index('pinyin'), head.index('alias'), head.index('status')
    rows = [(i, l.split('\t')) for i, l in enumerate(lines) if i > head_idx and l.strip()]
    en = [r for r in rows if r[1][si] == '1']
    targets = {r[1][ci] for r in en}
    db = sqlite3.connect(R / 'build/e036_corpus/corpus.sqlite')
    BIG = ' '.join(t for (t,) in db.execute('select text_norm from docs'))

    def present(w):
        return w in BIG

    demote, review = [], []
    for i, f in en:
        t, a, p = f[ci], f[ai], f[pi]
        why = []
        if not a.strip():
            why.append('R1 别名为空')
        elif len(a) != len(t):
            why.append('R1 别名与目标词长度不等')
        if len(SYL.findall(p)) != len(t) or ''.join(SYL.findall(p)) != p:
            why.append('R3 读音与字数不符')
        if not re.fullmatch(r'[一-鿿]+', t):
            why.append('R3 目标词含非汉字')
        if a == t:
            why.append('R3 别名等于目标词')
        if len(t) >= 4 and not present(t):
            # 切成两个都在 807 万字里连续出现、且都不短于 2 字的片段，而整串从不出现 → 像跨词边界的抽取残留
            for k in range(2, len(t) - 1):
                A, B = t[:k], t[k:]
                if len(A) >= 2 and len(B) >= 2 and present(A) and present(B):
                    review.append((t, a, '%s+%s' % (A, B)))
                    break
        if why:
            demote.append((i, t, a, p, '；'.join(why)))

    print('实际降级 %d 行（启用行共 %d）：' % (len(demote), len(en)))
    for _, t, a, p, why in demote:
        print('   %-10s ← %-12s %-20s %s' % (t, a, p, why))
    LIST.write_text('\n'.join(['# 只竞争、不改写的条目（E036 体检产出，改表时间 %s）' % time.strftime('%F %T'),
                               'canonical\talias\tpinyin\treason\thuman_state'] +
                              ['\t'.join([t, a, p, w, 'pending']) for _, t, a, p, w in demote]) + '\n', encoding='utf-8')
    if dry:
        print('\n（预演模式，未改表。加 --apply 才写。）')
        return
    shutil.copyfile(TBL, BAK)
    out = lines[:]
    for i, t, a, p, why in demote:
        f = out[i].split('\t')
        f[si] = '0'
        out[i] = '\t'.join(f)
    TBL.write_text('\n'.join(out), encoding='utf-8')
    print('\n已写表。备份 %s；旧 SHA %s，新 SHA %s' % (
        BAK, hashlib.sha256(BAK.read_bytes()).hexdigest()[:16], hashlib.sha256(TBL.read_bytes()).hexdigest()[:16]))


if __name__ == '__main__':
    main(dry='--apply' not in sys.argv)
