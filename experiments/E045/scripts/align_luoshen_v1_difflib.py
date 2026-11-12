#!/usr/bin/env python3
"""洛神赋朗诵新样本：whisper 输出 ↔ 公版原文 对齐，产真值草稿 + 待标注清单 + 窗长证据。

规则（写清楚，便于园长复核）：
  * 参考文本＝维基文库《洛神賦》{{vtext}} 行（六臣注文選／曹子建集底本，公版），逐字符经 CEDICT 繁简表规范化；
  * 对齐在"规范化后的汉字流"上做（difflib），再按位投回每个 whisper cue；
  * cue 内匹配率高 → 自动按原文出 gt；匹配率低或属于讲解/片尾 → 进待标注；
  * 只改字不改造句：cue 的标点沿用 whisper，避免把古文句读强加给 ASR 分段；
  * 差异分级：同音异形（可能只是异体/繁简，不算错）、同音不同字（真错）、异音（多半是漏字/多字或原文歧义）。
"""
import collections, difflib, importlib.util, json, pathlib, re, sys

R = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(R / 'experiments/E036/scripts'))
sys.stdout.reconfigure(encoding='utf-8')
spec = importlib.util.spec_from_file_location('e036', R / 'experiments/E036/scripts/build_corpus.py')
M = importlib.util.module_from_spec(spec)
argv, sys.argv = sys.argv, ['build_corpus.py']
spec.loader.exec_module(M)
sys.argv = argv
norm, TS = M.norm, M.TS

# 读音表（本项目自己的口径）
readings = {}
for line in (R / 'data/pronunciation/pronunciation_char.tsv').read_text('utf-8').splitlines():
    if line.startswith('#') or not line.strip() or line.startswith('char\t'):
        continue
    f = line.split('\t')
    if len(f) >= 2:
        readings[f[0]] = set(x.rstrip('012345') for x in re.findall(r'[a-zv:]+[0-5]', f[1]))


def syl(ch):
    return readings.get(ch, set())


def same_sound(a, b):
    return bool(syl(a) & syl(b))


# --- 参考文本 ---
wik = json.loads((R / 'build/e044_probe/luoshen.json').read_text('utf-8'))[
    'query']['pages'][0]['revisions'][0]['slots']['main']['content']
phrases = [p.strip() for p in re.findall(r'\{\{vtext\|([^}]*)\}\}', wik) if p.strip()]
ref_raw = ''.join(phrases)
ref_norm = ''.join(norm(ref_raw)[0])                      # 繁体→简体，非汉字变空格
ref_units = [re.sub(r'\s+', ' ', p).strip() for p in phrases]

# --- whisper ---
w = json.loads((R / 'asr/BV1uN4y1y7Fb.whisper.json').read_text('utf-8'))
segs = w['transcription']
cue_text = [s['text'].strip() for s in segs]
cue_ms = [(s['offsets']['from'] / 1000.0, s['offsets']['to'] / 1000.0) for s in segs]


def han_only(t):
    return [c for c in norm(t)[0] if c != ' ']


W = []                                                     # 扁平汉字流 + 每字所属 cue
owner = []
for i, t in enumerate(cue_text):
    for c in han_only(t):
        W.append(c)
        owner.append(i)
Rr = han_only(ref_raw)

sm = difflib.SequenceMatcher(None, ''.join(W), ''.join(Rr), autojunk=False)
blocks = sm.get_matching_blocks()
# 每个 whisper 位置 → 原文位置（未匹配为 None）
pos = [None] * len(W)
for a, b, n in blocks:
    for k in range(n):
        pos[a + k] = b + k

cov = collections.Counter()
for i, t in enumerate(cue_text):
    idxs = [j for j in range(len(W)) if owner[j] == i]
    cov[i] = (sum(1 for j in idxs if pos[j] is not None), len(idxs))

# 每个 cue 覆盖的原文区间 → 该 cue 的原文文本（用于出 gt 与判断漏读）
cue_ref = {}
for i, t in enumerate(cue_text):
    idxs = [j for j in range(len(W)) if owner[j] == i]
    hit = [pos[j] for j in idxs if pos[j] is not None]
    cue_ref[i] = (min(hit), max(hit) + 1) if hit else None

draft, need = [], []
for i, t in enumerate(cue_text):
    matched, total = cov[i]
    rate = matched / total if total else 0.0
    rng = cue_ref[i]
    gt = t
    note = ''
    if rng and rate >= 0.60:
        # 用原文片段替换：保留 cue 内的非汉字（标点），只把汉字流换成对齐到的原文汉字
        seg_ref = ''.join(Rr[rng[0]:rng[1]])
        gt = ''.join(norm(seg_ref)[0]).replace(' ', '')
        if rate < 0.85 or len(seg_ref) > total * 1.6 or len(seg_ref) < total * 0.55:
            note = 'cue 与原文长度/匹配偏差较大（匹配 %.0f%%，cue %d 字 vs 原文 %d 字）' % (
                rate * 100, total, len(seg_ref))
    else:
        note = '未对齐或匹配率过低（匹配 %d/%d）' % (matched, total)
    draft.append({'index': i, 't': '%02d:%02d:%02d,%03d' % (
        int(cue_ms[i][0] // 3600), int(cue_ms[i][0] % 3600 // 60), int(cue_ms[i][0] % 60),
        int(round(cue_ms[i][0] % 1 * 1000))), 'text': t, 'gt': gt,
        'applied': [], 'terms': [], 'pending': [] if not note else [note]})
    if note:
        need.append((i, cue_ms[i], t, gt, note))

out = R / 'asr/BV1uN4y1y7Fb.gt.jsonl'
out.write_text('\n'.join(json.dumps(d, ensure_ascii=False) for d in draft) + '\n', encoding='utf-8', newline='\n')
(R / 'asr/BV1uN4y1y7Fb.whisper.txt').write_text(
    '\n'.join('%d\t[%.1f-%.1f]\t%s' % (i, cue_ms[i][0], cue_ms[i][1], cue_text[i]) for i in range(len(segs))) + '\n',
    encoding='utf-8', newline='\n')

md = ['# 洛神赋新样本｜需要园长标注的部分\n',
      '参考文本：维基文库《洛神賦》（六臣注文選／曹子建集，公版），共 %d 个短语 / %d 汉字；'
      'whisper：%d 段 / %d 汉字（large-v3-turbo，-l zh -t 8 -np，与旧七篇同配置）。\n'
      % (len(ref_units), len(Rr), len(segs), len(W)),
      '自动判定：cue 与原文匹配率 ≥60%% 才按原文出真值；其余列在下面。共 **%d 段待标注**。\n' % len(need),
      '## 逐段\n', '| # | 时间 | whisper | 我的草稿/建议 | 为什么拿不准 |', '|---|---|---|---|---|']
for i, tm, t, gt, note in need:
    md.append('| %d | %.0f-%.0fs | %s | %s | %s |' % (i, tm[0], tm[1], t.replace('|', '/'),
                                                      gt.replace('|', '/'), note.replace('|', '/')))
(R / 'asr/BV1uN4y1y7Fb.need_label.md').write_text('\n'.join(md) + '\n', encoding='utf-8', newline='\n')

# --- 窗长证据：错误连段长度分布（只在已对齐部分算）---
err_total = 0
mismatch = []
for j in range(len(W)):
    if pos[j] is None:
        mismatch.append(2)          # 无法核对（漏读/多字/未匹配）
    else:
        mismatch.append(0 if W[j] == Rr[pos[j]] else 1)   # 1 = whisper 与原文同位置不同字
# 合并成连段
run_len, run_kinds = 0, collections.Counter()
dist = collections.Counter()
for j, m in enumerate(mismatch + [0]):
    if m == 1:
        run_len += 1
    else:
        if run_len:
            dist[run_len] += 1
            err_total += run_len
        run_len = 0
print('whisper 汉字流 %d；与原文同位不同字（候选真错）连段长度分布：%s' % (
    len(W), dict(sorted(dist.items()))))
print('其中连段长度 >4 字的段数 %d，占错字 %d 个' % (
    sum(v for k, v in dist.items() if k > 4), sum(k * v for k, v in dist.items() if k > 4)))
d = R / 'experiments/E045/results'
d.mkdir(parents=True, exist_ok=True)
(d / 'window_evidence.json').write_text(json.dumps(dict(
    ref_units=len(ref_units), ref_han=len(Rr), whisper_han=len(W), cues=len(segs), pending_cues=len(need),
    same_pos_diff_run_lengths={str(k): v for k, v in sorted(dist.items())},
    err_chars_total=err_total, unmatched_chars=sum(1 for m in mismatch if m == 2)),
    ensure_ascii=False, indent=2), encoding='utf-8')
print('写出 asr/BV1uN4y1y7Fb.gt.jsonl（草稿）与 need_label.md；证据 experiments/E045/results/window_evidence.json')
