#!/usr/bin/env python3
"""E051 最小测试：让本地 qwen3:14b 当"该不该改"的裁判，对着人工真值算账。

数据来源（都是已有产物，不重跑检索、不改任何正式件）：
  * whisper 原文与人工真值：asr/*.gt.jsonl（七篇，闭卷口径不变）；
  * 待审改动：用当前 V1 默认设置跑 build/e035/text_clean.exe 得到的**实际改动**，
    每处改动按真值分成两类——「该改」（改完正好等于真值）与「不该改」（原文本来就对，
    或改完仍是错字）。这正好复现园长说的"把正确候选塞入的文本"里的正例，同时自带负例。

给 LLM 的信息只有：整句原文 + 「第 N 字起的 A 改为 B」。**不含真值、不含任何提示哪个是对的**。
判决口径：改 / 保留。四格账：
  该改+判改 = 采纳正确｜该改+判保留 = 误杀（该改没让改）
  不该改+判改 = 放行错误｜不该改+判保留 = 正确拦下
用法：python experiments/E051/scripts/llm_judge.py [--videos 7] [--per-class 6] [--batch 8]
"""
import argparse, collections, json, pathlib, subprocess, sys, urllib.request

R = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(R / 'experiments/E024/scripts'))
sys.stdout.reconfigure(encoding='utf-8')
from align_lib import align

OUT = R / 'experiments/E051/results'
OUT.mkdir(parents=True, exist_ok=True)
OLLAMA = 'http://127.0.0.1:11434/api/generate'
MODEL = 'qwen3:14b-q4_K_M'

ap = argparse.ArgumentParser()
ap.add_argument('--videos', type=int, default=7, help='取前 N 篇（按文件名排序）')
ap.add_argument('--per-class', type=int, default=6, help='每篇每类最多取几条（该改 / 不该改）')
ap.add_argument('--batch', type=int, default=8, help='每次请求给 LLM 的条数')
ap.add_argument('--limit', type=int, default=0, help='总条数上限，0=不限')
args = ap.parse_args()

# ---------- 1. 组料：whisper 原文 / 真值 / V1 实际改动 ----------
rows = {}
for f in sorted((R / 'asr').glob('*.gt.jsonl')):
    keep = [r for r in (json.loads(s) for s in f.read_text('utf-8').splitlines() if s.strip())
            if not r.get('discard')]
    if keep:
        rows[f.stem] = keep
videos = list(rows)[:args.videos]
counts = collections.Counter()
items = []
for video in videos:
    keep = rows[video]
    body = '\n'.join(r['text'] for r in keep) + '\n'
    out = subprocess.run([str(R / 'build/e035/text_clean.exe'), '--no-index-cache'],
                         input=body.encode('utf-8'), capture_output=True, check=True, cwd=R).stdout.decode('utf-8')
    assert len(out) == len(body), 'V1 改动不应改变长度'
    truth = {}
    off = 0
    for r in keep:
        lab, _ = align(r['text'], r['gt'])
        truth.update({off + i: v for i, v in lab.items()})
        off += len(r['text']) + 1
    # 连续改动位点合并成一条候选
    spans = []
    p = 0
    while p < len(body):
        if body[p] != out[p]:
            q = p
            while q + 1 < len(body) and body[q + 1] != out[q + 1]:
                q += 1
            spans.append((p, q + 1))
            p = q + 1
        else:
            p += 1
    starts = []
    pos = 0
    for r in keep:
        starts.append(pos)
        pos += len(r['text']) + 1
    for b, e in spans:
        src, tgt = body[b:e], out[b:e]
        # 真值判定：改完正好等于真值 → 该改；否则不该改
        right = all(tgt[i] == truth.get(b + i, src[i]) for i in range(e - b))
        ok_truth = all(truth.get(b + i) is not None for i in range(e - b))
        if not ok_truth:
            counts['无真值_跳过'] += 1
            continue
        k = max(i for i, s in enumerate(starts) if s <= b)
        sent = keep[k]['text']
        base = b - starts[k]
        items.append(dict(video=video, cue=k, begin=b, end=e, source=src, target=tgt,
                          should_change=right, sentence=sent, offset=base))
        counts['该改' if right else '不该改'] += 1

# ---------- 2. 最小取样：每篇每类各取 per_class 条，均匀取 ----------
picked = []
for video in videos:
    for flag in (True, False):
        pool = [x for x in items if x['video'] == video and x['should_change'] == flag]
        if not pool:
            continue
        step = max(1, len(pool) // args.per_class)
        picked += pool[::step][:args.per_class]
if args.limit:
    picked = picked[:args.limit]
print('V1 实际改动 %d 处：该改 %d、不该改 %d；本次送审 %d 条（该改 %d／不该改 %d）' % (
    len(items), counts['该改'], counts['不该改'], len(picked),
    sum(1 for x in picked if x['should_change']), sum(1 for x in picked if not x['should_change'])))

# ---------- 3. 问 LLM ----------
PROMPT_HEAD = (
    '你是中文文本校对裁判。下面是语音识别得到的整句原文，以及一处"拟改动"（把原文某个片段换成另一个词）。\n'
    '请逐条判断这处改动该不该采纳：改动后的词在这句话的语境里是否比原词更通顺、更符合常用搭配与常识。\n'
    '只输出 JSON 数组，每个元素形如 {"id":1,"verdict":"改"} 或 {"id":1,"verdict":"保留"}，'
    '不要输出解释、不要多余文字。\n'
    '示范（仅示范格式）：\n【原文】他在一偏之缘上不肯让步。 拟改动：第 3 字起的「一偏之缘」改为「一面之缘」\n'
    '输出：[{"id":0,"verdict":"改"}]\n\n现在判断：\n')


def ask(batch):
    lines = []
    for n, x in enumerate(batch):
        lines.append('【原文】%s 拟改动：第 %d 字起的「%s」改为「%s」' % (
            x['sentence'], x['offset'], x['source'], x['target']))
    payload = json.dumps(dict(model=MODEL, prompt=PROMPT_HEAD + '\n'.join(lines), stream=False,
                              think=False, options=dict(temperature=0, num_predict=8 * len(batch) + 60)),
                        ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(OLLAMA, data=payload, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode('utf-8')).get('response', '')


def parse(text, n):
    m = text.find('[')
    arr = json.loads(text[m:text.rfind(']') + 1]) if m >= 0 and text.rfind(']') > m else []
    got = {}
    for i, o in enumerate(arr):
        if isinstance(o, dict) and 'verdict' in o:
            v = str(o['verdict']).strip()
            got[i] = '改' if '改' in v and '保留' not in v else '保留' if '保留' in v else None
    return [got.get(i) for i in range(n)]


verdicts, raw = [], []
for s in range(0, len(picked), args.batch):
    batch = picked[s:s + args.batch]
    ans = ask(batch)
    raw.append(ans)
    got = parse(ans, len(batch))
    if all(v is None for v in got):
        raise SystemExit('第 %d 批 LLM 没按格式回答，中止：\n%s' % (s, ans[:400]))
    for x, v in zip(batch, got):
        x = dict(x)
        x['llm'] = v or '未答'
        verdicts.append(x)
    print('  已判 %d/%d' % (min(s + args.batch, len(picked)), len(picked)), flush=True)

# ---------- 4. 算账 ----------
cell = collections.Counter()
for x in verdicts:
    if x['should_change']:
        cell['该改_采纳' if x['llm'] == '改' else '该改_误杀'] += 1
    else:
        cell['不该改_放行' if x['llm'] == '改' else '不该改_拦下'] += 1
n = len(verdicts)
said_change = sum(1 for x in verdicts if x['llm'] == '改')
print('\n==== qwen3:14b 判决 vs 人工真值（共 %d 条）====' % n)
for k in ('该改_采纳', '该改_误杀', '不该改_放行', '不该改_拦下', '未答'):
    if cell.get(k):
        print('  %-10s %d 条' % (k, cell[k]))
print('  它说"改" %d 条、"保留" %d 条；判对率 %.1f%%' % (
    said_change, n - said_change,
    (cell['该改_采纳'] + cell['不该改_拦下']) * 100.0 / n if n else 0.0))
print('  若按它的判决否决：可拦下错误改动 %d 处，代价是误杀正确改动 %d 处（净 %+d）' % (
    cell['不该改_拦下'], cell['该改_误杀'], cell['不该改_拦下'] - cell['该改_误杀']))
(OUT / 'llm_judge.json').write_text(json.dumps(dict(
    model=MODEL, think=False, temperature=0, exe='build/e035/text_clean.exe --no-index-cache',
    candidate_table_sha='dab7d80a6497271f', videos=videos,
    v1_edits_by_truth={'should_change': counts['该改'], 'should_not': counts['不该改'],
                       'no_truth_skipped': counts['无真值_跳过']},
    asked=len(verdicts), cells=dict(cell), said_change=said_change,
    accuracy=round((cell['该改_采纳'] + cell['不该改_拦下']) / n, 4) if n else None,
    items=verdicts), ensure_ascii=False, indent=2), encoding='utf-8')
tsv = ['video\tcue\tbegin\tend\tsource\ttarget\tshould_change\tllm\tsentence']
for x in verdicts:
    tsv.append('%s\t%d\t%d\t%d\t%s\t%s\t%s\t%s\t%s' % (
        x['video'], x['cue'], x['begin'], x['end'], x['source'], x['target'],
        '该改' if x['should_change'] else '不该改', x['llm'], x['sentence'].replace('\t', ' ')))
(OUT / 'llm_judge_items.tsv').write_text('\n'.join(tsv) + '\n', encoding='utf-8')
(OUT / 'llm_raw_responses.txt').write_text('\n-----\n'.join(raw), encoding='utf-8')
print('写出 experiments/E051/results/llm_judge.json、llm_judge_items.tsv')
