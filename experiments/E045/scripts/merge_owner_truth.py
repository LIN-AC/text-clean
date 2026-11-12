#!/usr/bin/env python3
"""把园长的逐段标注并进真值：产出"窗口判断专用"素材，不进七篇真值评测的 glob。

园长口径（2026-11-13）：
  * 表格最后一列是园长标注，全部按园长文字进真值；`删掉` 的那段做 discard（沿用项目既有 discard 字段口径）；
  * 汉字数与 cue 相同时，标点沿用 whisper（只改字不改造句，与评测 align 口径一致）；
    汉字数不等时整段用园长原文（含其标点），并在 note 里记明；
  * 本篇不进 asr/*.gt.jsonl：现有 all-asr 脚本都用单层 glob 取真值，故真值写到 asr/window_check/ 子目录，
    只作"窗长上限判断"用途（洛神赋不在语料库内，跑现程序评测没意义）。
"""
import importlib.util, json, pathlib, re, sys

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
OUT = R / 'asr/window_check'
OUT.mkdir(parents=True, exist_ok=True)


def han(t):
    return [c for c in norm(t)[0] if c != ' ']


def splice(text, chars):
    out, k = [], 0
    for c in text:
        if norm(c)[0].strip():
            out.append(chars[k] if k < len(chars) else c)
            k += 1
        else:
            out.append(c)
    return ''.join(out)


draft = {}
for line in (OUT / ('%s.draft.jsonl' % BV)).read_text('utf-8').splitlines():
    d = json.loads(line)
    draft[d['index']] = d

segs = json.loads((R / ('asr/%s.whisper.json' % BV)).read_text('utf-8'))['transcription']
cue_text = [s['text'].strip() for s in segs]
cue_ms = [(s['offsets']['from'] / 1000.0, s['offsets']['to'] / 1000.0) for s in segs]

owner, drop = {}, {}
for line in (R / ('asr/%s.need_label.md' % BV)).read_text('utf-8').splitlines():
    if not line.startswith('|'):
        continue
    cells = [c.strip() for c in line.strip().strip('|').split('|')]
    if len(cells) < 6 or not re.fullmatch(r'\d+', cells[0]):
        continue
    i, note = int(cells[0]), cells[5]
    if not note:
        continue
    if '删掉' in note or '无意义' in note:
        drop[i] = note
    else:
        owner[i] = note

rows, stat = [], {}
for i, t in enumerate(cue_text):
    d = draft.get(i, {'index': i, 'text': t, 'gt': t, 'pending': ['草稿里没有这段']})
    gt, note, disc = d['gt'], '', None
    if i in drop:
        disc = drop[i]
        note = '园长判为无意义（whisper 幻觉）'
    elif i in owner:
        ow = owner[i]
        if len(han(ow)) == len(han(t)):
            gt = splice(t, han(ow))
            note = '园长标注（汉字数相同，标点沿用 whisper）'
        else:
            gt = ow
            note = '园长标注（汉字数与 cue 不同，整段用园长原文含其标点）'
    rows.append({'index': i, 't': '%02d:%02d:%02d,%03d' % (
        int(cue_ms[i][0] // 3600), int(cue_ms[i][0] % 3600 // 60), int(cue_ms[i][0] % 60),
        int(round(cue_ms[i][0] % 1 * 1000))), 'text': t, 'gt': gt,
        'applied': [], 'terms': [], 'pending': [],
        **({'discard': disc} if disc else {'note': note})})
    stat[('删除' if disc else ('园长标注' if i in owner else '自动'))] = \
        stat.get(('删除' if disc else ('园长标注' if i in owner else '自动')), 0) + 1

(OUT / ('%s.gt.jsonl' % BV)).write_text(
    '\n'.join(json.dumps(x, ensure_ascii=False) for x in rows) + '\n', encoding='utf-8', newline='\n')
kept = [x for x in rows if not x.get('discard')]
print('写出 asr/window_check/%s.gt.jsonl：%d 行（保留 %d、删除 %d）分类 %s' % (
    BV, len(rows), len(kept), len(rows) - len(kept), stat))
print('汉字位点改动统计：园长标注 %d 段、自动 %d 段' % (len(owner), stat.get('自动', 0)))
