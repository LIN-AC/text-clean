#!/usr/bin/env python3
"""候选词库复核（只读，不改表）：结构 + 拼音合法性 + 词表覆盖 + 别名自指 + 重复 + 单字目标。

判定标准全部来自现有装配代码与既有结论，不新增口径：
  * 字段数 5、status ∈ {0,1}、canonical/alias 内不得有空白或制表；
  * 拼音按 prepare_rag_package.readings 的同一规则切（[a-zv:]+[0-5]），音节数必须等于目标字数；
  * 每个音节必须是读音表里出现过的合法音节（不是拼写像拼音就行，"lwu4" 这种要抓出来）；
  * 别名等于目标词本身 → 该条不可能标注错误形式，属数据异味；
  * 同 (canonical, alias) 重复行、同一别名映射到多个启用目标（会互相抢）；
  * 启用目标长度为 1 → 现有窗口下限 min_syllables_for_exact_pinyin=2，结构上永远不可能触发；
  * 目标词查不到词表证据（data/frequency/word_freq.tsv）→ 结合人工判读是否为切分残留。
"""
import collections, csv, json, pathlib, re, sys

R = pathlib.Path(__file__).resolve().parents[3]
sys.stdout.reconfigure(encoding='utf-8')
TBL = R / 'data/correction/candidates.tsv'
PRON = R / 'data/pronunciation/pronunciation_char.tsv'
WORDPRON = R / 'data/pronunciation/pronunciation.tsv'
WORD = R / 'data/frequency/word_freq.tsv'
SYL = re.compile(r'[a-zv:]+[0-5]')


def rows(path):
    with path.open(encoding='utf-8') as f:
        return list(csv.DictReader((l for l in f if not l.startswith('#')), delimiter='\t'))


data = rows(TBL)
legal_syl = set()
for r in rows(PRON):
    for form in (r['readings'] or '').split('|'):
        legal_syl.update(SYL.findall(form))
table_words = {r['entry'] for r in rows(WORDPRON)}
words = set()
with WORD.open(encoding='utf-8') as f:
    for r in csv.DictReader((l for l in f if not l.startswith('#')), delimiter='\t'):
        words.add(r['word'])

flag = collections.defaultdict(list)
seen_pair, alias_multi = set(), collections.defaultdict(set)
for r in data:
    c, p, a, src, st = r['canonical'], r['pinyin'], r['alias'], r['source'], r['status']
    who = '%s\t%s\t%s\t%s\t%s' % (c, p, a, src, st)
    if st not in ('0', '1'):
        flag['status非法'].append(who)
    if not c or c != c.strip() or re.search(r'\s', c):
        flag['目标词空白或空值'].append(who)
    syls = SYL.findall(p)
    if ''.join(syls) != p:
        flag['拼音未能完整切分'].append(who)
    if len(syls) != len(c):
        flag['音节数与字数不符'].append(who)
    bad = [s for s in syls if s not in legal_syl]
    if bad:
        flag['非法音节'].append('%s | 坏音节 %s' % (who, ','.join(bad)))
    if a:
        for one in a.split('|'):
            if one == c:
                flag['别名等于目标词'].append(who)
            if re.search(r'\s', one):
                flag['别名含空白'].append(who)
            if st == '1':
                alias_multi[one].add(c)
    if (c, a, src, st) in seen_pair:
        flag['整行重复'].append(who)
    seen_pair.add((c, a, src, st))
    if st == '1':
        # 装配器对启用行的硬性要求：别名非空时必须与目标词等长且两者全汉字，否则整个词典加载抛错
        if a:
            if len(a) != len(c):
                flag['启用行别名与目标词不等长(加载会抛错)'].append(who)
            if not re.fullmatch(r'[一-鿿]+', c) or not re.fullmatch(r'[一-鿿]+', a):
                flag['启用行含非汉字(加载会抛错)'].append(who)
        # 行内 pinyin 只在读音表查不到该词时被使用（装配器优先词级读音），所以分两种情形报
        in_table = c in table_words
        if len(syls) != len(c):
            (flag['行内拼音音节数不符（读音表有此词，实际未用）'] if in_table
             else flag['行内拼音音节数不符（读音表无此词，条目会没有读音）']).append(
                '%s | 读音表 %s | 坏音节 %s' % (who, '有' if in_table else '无', ','.join(
                    s for s in syls if s not in legal_syl) or '-'))
        if len(c) == 1:
            flag['启用单字目标(结构不可达)'].append(who)
        if c not in words:
            flag['启用目标查无词表证据'].append(who)
        if p.endswith('0') or '0' in [s[-1] for s in syls]:
            flag['启用目标含未知声调0'].append(who)

conflict = {k: sorted(v) for k, v in alias_multi.items() if len(v) > 1}
out = dict(file=str(TBL), sha256=__import__('hashlib').sha256(TBL.read_bytes()).hexdigest(),
           rows=len(data), enabled_rows=sum(1 for r in data if r['status'] == '1'),
           enabled_targets=len({r['canonical'] for r in data if r['status'] == '1'}),
           legal_syllables=len(legal_syl), word_table_rows=len(words),
           flags={k: v for k, v in sorted(flag.items())}, alias_conflicts=conflict)
dst = R / 'experiments/E043/results/candidate_audit.json'
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
print('总行 %d，启用行 %d，启用目标 %d，合法音节 %d' % (
    out['rows'], out['enabled_rows'], out['enabled_targets'], out['legal_syllables']))
for k, v in out['flags'].items():
    print('\n[%s] %d 条' % (k, len(v)))
    for x in v[:14]:
        print('   ', x)
if conflict:
    print('\n[同一别名映射多个启用目标] %d 个' % len(conflict))
    for k, v in list(conflict.items())[:12]:
        print('   ', k, '→', v)
print('\n写出', dst)
