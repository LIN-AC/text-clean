#!/usr/bin/env python3
"""洛神赋朗诵新样本：whisper 输出 ↔ 公版原文 对齐，产真值草稿 + 待标注清单 + 窗长证据。

规则（写清楚，便于园长复核）：
  * 参考文本＝维基文库《洛神賦》{{vtext}} 行（六臣注文選／曹子建集底本，公版），逐字符经本项目繁简表规范化；
    已核对该文不在语料库内（"翩若惊鸿" 0 篇），所以这是独立测试素材，不存在自证。
  * 对齐打分允许"同音也算部分命中"：同字 1.0、同音不同字 0.65、不同音 -1.0、多字/漏字各 -1.0。
    v1 用 difflib（要求字符完全相同）结果 75/78 段"未对齐"——ASR 把古文生僻字听成同音常用字
    （洛神赋→洛神父），字符不相等就整段对不上，故换成 Needleman-Wunsch 半全局对齐。
  * cue 按时间顺序单调推进参考游标（朗诵是顺序读的，不允许跳回前面；没通过的 cue 不推进游标）。
  * 命中比例 >=0.55 且段内无多字/漏字 -> 自动按原文出 gt（标点沿用 whisper，不改造句）；
    比例过低、或有多/漏字（标点对不上）、或整段没对上 -> 进待标注清单交园长。
  * 位点分级：0 对；1 同音不同字（听感一致、字形不一致，可能是真错）；2 不同音或 whisper 多字；
    4 漏字（原文有、whisper 没有）；3 整段未对齐（不计入窗长统计，单独报数）。

窗长证据（园长要测的"四字上限是否合理"）：把每个 whisper 汉字位点连成"连续出错段"，
统计段长分布，以及错字落在长度 >4 的段里的占比——那部分才是 4 字窗口管不到的。

输出口径（园长 2026-11-13 定的）：本篇洛神赋**不进七篇真值评测**（语料库里根本没有洛神赋，
跑现程序评测没意义），只用来验窗长判断。所以草稿与自动清单都写到 `asr/window_check/` 子目录
（现有评测脚本全用 `asr/*.gt.jsonl` 单层 glob，取不到子目录），且**绝不覆盖**
`asr/BV1uN4y1y7Fb.need_label.md`——那份表格里有园长逐段标注，是合并真值的唯一来源。
"""
import collections, importlib.util, json, pathlib, re, sys

R = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(R / 'experiments/E036/scripts'))
sys.stdout.reconfigure(encoding='utf-8')
spec = importlib.util.spec_from_file_location('e036', R / 'experiments/E036/scripts/build_corpus.py')
M = importlib.util.module_from_spec(spec)
argv, sys.argv = sys.argv, ['build_corpus.py']
spec.loader.exec_module(M)
sys.argv = argv
norm = M.norm

BV = 'BV1uN4y1y7Fb'
EXACT, HOMO, WRONG, GAP = 1.0, 0.65, -1.0, 1.0
ACCEPT = 0.55           # 整段命中比例下限
SLACK = 4               # 允许下一段起点比上一段终点早几字（句尾重叠）
LOOKAHEAD = 90          # 每段在游标之后最多搜索这么多原文字

readings = {}
for line in (R / 'data/pronunciation/pronunciation_char.tsv').read_text('utf-8').splitlines():
    if line.startswith('#') or not line.strip() or line.startswith('char\t'):
        continue
    f = line.split('\t')
    if len(f) >= 2:
        readings[f[0]] = set(x.rstrip('012345') for x in re.findall(r'[a-zv:]+[0-5]', f[1]))

# ---------------- 参考文本（原文汉字流）----------------
wik = json.loads((R / 'build/e044_probe/luoshen.json').read_text('utf-8'))[
    'query']['pages'][0]['revisions'][0]['slots']['main']['content']
phrases = [p.strip() for p in re.findall(r'\{\{vtext\|([^}]*)\}\}', wik) if p.strip()]
Rr = [c for c in ''.join(norm(p)[0] for p in phrases) if c != ' ']
Rsy = [readings.get(c, set()) for c in Rr]

# ---------------- whisper cue ----------------
segs = json.loads((R / ('asr/%s.whisper.json' % BV)).read_text('utf-8'))['transcription']
cue_text = [s['text'].strip() for s in segs]
cue_ms = [(s['offsets']['from'] / 1000.0, s['offsets']['to'] / 1000.0) for s in segs]
cue_han = [[c for c in norm(t)[0] if c != ' '] for t in cue_text]
cue_syl = [[readings.get(c, set()) for c in h] for h in cue_han]

W, OWNER = [], []
for i, h in enumerate(cue_han):
    OWNER += [i] * len(h)
    W += h


def align(cue, syl, lo, hi):
    """cue 对 Rr[lo:hi] 的半全局对齐（参考串首尾空位免费）。
    返回 (归一化分, 起点, 终点, ops)；ops 每项 = (类, 原文位)：
    e 同字 / h 同音不同字 / x 不同音 / i whisper 多字（原文位 None）/ d 漏字（无 cue 位）。"""
    n, m = len(cue), hi - lo
    if not n or m <= 0:
        return -9.0, lo, lo, [('i', None)] * n
    NEG = -1e9
    dp = [[NEG] * (m + 1) for _ in range(n + 1)]
    bt = [[None] * (m + 1) for _ in range(n + 1)]
    for j in range(m + 1):
        dp[0][j] = 0.0
    for i in range(1, n + 1):
        dp[i][0], bt[i][0] = dp[i - 1][0] - GAP, 'up'
        ch, sy = cue[i - 1], syl[i - 1]
        for j in range(1, m + 1):
            rc, rs = Rr[lo + j - 1], Rsy[lo + j - 1]
            sub = dp[i - 1][j - 1] + (EXACT if ch == rc else HOMO if sy and rs and (sy & rs) else WRONG)
            dele, ins = dp[i][j - 1] - GAP, dp[i - 1][j] - GAP
            best, op = sub, 'sub'
            if dele > best:
                best, op = dele, 'del'
            if ins > best:
                best, op = ins, 'up'
            dp[i][j], bt[i][j] = best, op
    j = max(range(1, m + 1), key=lambda k: dp[n][k])
    score, ops, i = dp[n][j], [], n
    while i > 0:
        op = bt[i][j]
        if op == 'sub':
            rc = Rr[lo + j - 1]
            kind = ('e' if cue[i - 1] == rc else
                    'h' if (syl[i - 1] and Rsy[lo + j - 1] and (syl[i - 1] & Rsy[lo + j - 1])) else 'x')
            ops.append((kind, lo + j - 1))
            i, j = i - 1, j - 1
        elif op == 'del':
            ops.append(('d', lo + j - 1))
            j -= 1
        else:
            ops.append(('i', None))
            i -= 1
    ops.reverse()
    start = lo + j
    used = [v for _, v in ops if v is not None]
    return score / n, start, (max(used) + 1 if used else start), ops


# ---------------- 单调游标逐 cue 对齐 ----------------
res, cursor = {}, 0
for i, cue in enumerate(cue_han):
    if not cue:
        res[i] = (0.0, None, [])
        continue
    lo0 = max(0, cursor - SLACK)
    hi0 = min(len(Rr), lo0 + max(LOOKAHEAD, len(cue) + 10))
    sc, st, en, ops = align(cue, cue_syl[i], lo0, hi0)
    res[i] = (sc, (st, en), ops)
    if sc >= ACCEPT:
        cursor = en

# ---------------- 位点分级（窗长证据）----------------
lab = [3] * len(W)
unaligned = 0
covered = set()
for i, cue in enumerate(cue_han):
    sc, rng, ops = res[i]
    if rng is None or sc < ACCEPT:
        unaligned += len(cue)
        continue
    base = OWNER.index(i)
    covered.update(range(rng[0], rng[1]))
    k = 0
    for kind, pos in ops:
        if kind == 'd':
            continue                     # 漏字没有自己的位点，挂在段尾统一处理
        lab[base + k] = {'e': 0, 'h': 1, 'x': 2, 'i': 2}[kind]
        k += 1
    ndel = sum(1 for kind, _ in ops if kind == 'd')
    if ndel and base + len(cue) - 1 < len(lab):
        lab[base + len(cue) - 1] = 4     # 漏字挂在段末，让连续段能跨过漏字延伸

runs, runs_homo, err_total = collections.Counter(), collections.Counter(), 0
run_len = run_homo = 0
for v in lab + [0]:
    if v and v != 3:
        run_len += 1
        run_homo = run_homo + 1 if v == 1 else 0
    else:
        if run_len:
            runs[run_len] += 1
            err_total += run_len
            if run_homo == run_len:
                runs_homo[run_len] += 1
        run_len, run_homo = 0, 0
over4 = sum(k * v for k, v in runs.items() if k > 4)


def splice(text, chars):
    """cue 内汉字按序换成原文汉字，标点位置不动。"""
    out, k = [], 0
    for c in text:
        if norm(c)[0].strip():
            out.append(chars[k] if k < len(chars) else c)
            k += 1
        else:
            out.append(c)
    return ''.join(out)


# ---------------- 真值草稿 ----------------
draft = []
for i, t in enumerate(cue_text):
    sc, rng, ops = res[i]
    kinds = collections.Counter(k for k, _ in ops)
    gt, note = t, ''
    if rng is None or sc < ACCEPT:
        note = '整段没对上（命中 %.0f%%，同音不同字 %d、不同音/多字 %d、漏字 %d）' % (
            sc * 100, kinds['h'], kinds['x'] + kinds['i'], kinds['d'])
    elif kinds['i'] or kinds['d']:
        note = '命中 %.0f%% 但有多字 %d/漏字 %d，标点对不上，需人工确认' % (
            sc * 100, kinds['i'], kinds['d'])
    else:
        gt = splice(t, Rr[rng[0]:rng[1]])
    draft.append({'index': i, 't': '%02d:%02d:%02d,%03d' % (
        int(cue_ms[i][0] // 3600), int(cue_ms[i][0] % 3600 // 60), int(cue_ms[i][0] % 60),
        int(round(cue_ms[i][0] % 1 * 1000))), 'text': t, 'gt': gt,
        'applied': [], 'terms': [], 'pending': [note] if note else []})
(R / 'asr/window_check').mkdir(parents=True, exist_ok=True)
(R / ('asr/window_check/%s.draft.jsonl' % BV)).write_text(
    '\n'.join(json.dumps(d, ensure_ascii=False) for d in draft) + '\n', encoding='utf-8', newline='\n')
(R / ('asr/%s.whisper.txt' % BV)).write_text(
    '\n'.join('%d\t[%.1f-%.1f]\t%s' % (i, cue_ms[i][0], cue_ms[i][1], cue_text[i])
              for i in range(len(segs))) + '\n', encoding='utf-8', newline='\n')

pend = [d for d in draft if d['pending']]
auto = len(draft) - len(pend)
md = ['# 洛神赋新样本｜需要园长标注的部分\n',
      '参考文本：维基文库《洛神賦》（六臣注文選／曹子建集，公版）规范化后 **%d** 汉字；'
      'whisper：**%d** 段 / **%d** 汉字（large-v3-turbo，-l zh -t 8 -np，与旧七篇同配置）。\n'
      % (len(Rr), len(segs), len(W)),
      '判定口径：整段命中比例 >=**%.0f%%** 且段内无多字/漏字 -> 自动按原文出真值（标点沿用 whisper）；'
      '其余交园长。自动 **%d** 段、待标注 **%d** 段。\n' % (ACCEPT * 100, auto, len(pend)),
      '## 窗长证据：四字上限是否合理\n',
      '连续出错段长度分布：%s\n' % dict(sorted(runs.items())),
      '错字总数 **%d**，其中落在长度 >4 的连续段内 **%d** 字（**%.1f%%**）——这部分 4 字窗口管不到。\n'
      % (err_total, over4, over4 * 100.0 / err_total if err_total else 0.0),
      '全是"同音不同字"的连续段分布：%s\n' % dict(sorted(runs_homo.items())),
      '整段没对上的字数：%d（讲解/片尾或生僻句，不计入窗长统计）。\n' % unaligned,
      '## 逐段', '', '| # | 时间 | whisper | 我的草稿 | 为什么拿不准 |', '|---|---|---|---|---|']
for d in pend:
    i = d['index']
    md.append('| %d | %.1f-%.1fs | %s | %s | %s |' % (
        i, cue_ms[i][0], cue_ms[i][1], d['text'].replace('|', '/'), d['gt'].replace('|', '/'),
        d['pending'][0].replace('|', '/')))
(R / ('asr/window_check/%s.need_label.auto.md' % BV)).write_text(
    '\n'.join(md) + '\n', encoding='utf-8', newline='\n')

out = R / 'experiments/E045/results'
out.mkdir(parents=True, exist_ok=True)
(out / 'window_evidence.json').write_text(json.dumps(dict(
    sample=BV, ref_han=len(Rr), whisper_han=len(W), cues=len(segs),
    accept_line=ACCEPT, auto_cues=auto, pending_cues=len(pend),
    error_run_lengths={str(k): v for k, v in sorted(runs.items())},
    homophone_only_run_lengths={str(k): v for k, v in sorted(runs_homo.items())},
    err_chars_total=err_total, err_chars_in_runs_over_4=over4,
    share_over_4=round(over4 / err_total, 4) if err_total else None,
    unaligned_chars=unaligned, ref_covered_chars=len(covered), ref_total_chars=len(Rr),
    label_key={'0': '对', '1': '同音不同字', '2': '不同音/多字', '4': '漏字', '3': '整段未对齐'}),
    ensure_ascii=False, indent=2), encoding='utf-8')

print('原文 %d 字｜whisper %d 段 %d 字｜自动出真值 %d 段、待标注 %d 段｜自动段覆盖原文 %d 字（%.1f%%）' % (
    len(Rr), len(segs), len(W), auto, len(pend), len(covered), len(covered) * 100.0 / len(Rr)))
print('连续出错段长度分布', dict(sorted(runs.items())))
print('错字 %d 个，其中落在长度>4 的段内 %d 个（%.1f%%）' % (
    err_total, over4, over4 * 100.0 / err_total if err_total else 0.0))
