#!/usr/bin/env python3
"""E051 第二轮：LLM 直接二选一，位置不靠 V1 筛，答案不透露。

题面来源（与 V1 完全无关）：
  * 正例（该改）：人工真值与 whisper 的差异段——一版含真值词、一版保持 whisper 原样，正确项＝含真值词那版。
    取段用 align_lib.align（与评测同一口径），不看 V1 改没改，也不碰 V1 的候选表。
  * 负例（不该改）：whisper 本来就等于真值、本身是词、且与错段隔开 8 字以上的片段，
    换成同音的另一写法造出错误版本，正确项＝保持原样那版。
    替代写法优先取"七篇里真被听错过的同音写法"（来自人工真值与 whisper 的差异，不来自 V1 判决），
    取不到才退回公开词表 word_freq.tsv 中同读音、zipf>=3.0 的词。
  * A/B 位置随机（固定种子 20261113 可复现），提示词不说哪版被改过，也不给真值。
答案口径：{"choice":"A"|"B"|"都行"}，允许"都行"，不逼模型硬猜。

用法：python experiments/E051/scripts/llm_ab.py [--per-video 10] [--limit 0] [--seed 20261113]
"""
import argparse, collections, json, pathlib, random, re, sys, urllib.request

R = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(R / 'experiments/E024/scripts'))
sys.stdout.reconfigure(encoding='utf-8')
from align_lib import align

OUT = R / 'experiments/E051/results'
OUT.mkdir(parents=True, exist_ok=True)
OLLAMA = 'http://127.0.0.1:11434/api/generate'
MODEL = 'qwen3:14b-q4_K_M'
HAN = lambda c: '\u4e00' <= c <= '\u9fff'

ap = argparse.ArgumentParser()
ap.add_argument('--per-video', type=int, default=10, help='每篇各取多少正例/负例')
ap.add_argument('--limit', type=int, default=0, help='总条数上限，0=不限')
ap.add_argument('--seed', type=int, default=20261113)
args = ap.parse_args()
rng = random.Random(args.seed)

# ---------- 读音表与公开词表（同音替代词来源，不用本项目候选表）----------
readings = {}
for line in (R / 'data/pronunciation/pronunciation_char.tsv').read_text('utf-8').splitlines():
    if line.startswith('#') or not line.strip() or line.startswith('char\t'):
        continue
    f = line.split('\t')
    if len(f) >= 2:
        rs = [x.rstrip('012345') for x in re.findall(r'[a-zv:]+[0-5]', f[1])]
        if rs:
            readings[f[0]] = rs[0]

words = {}
for line in (R / 'data/frequency/word_freq.tsv').read_text('utf-8').splitlines():
    if line.startswith('#') or not line.strip() or line.startswith('word\t'):
        continue
    f = line.split('\t')
    if len(f) < 2:
        continue
    w = f[0].strip()
    if not (1 <= len(w) <= 4) or not all(HAN(c) for c in w):
        continue
    try:
        words[w] = float(f[1])
    except ValueError:
        continue


def sound(word):
    parts = []
    for c in word:
        if c not in readings:
            return None
        parts.append(readings[c])
    return ' '.join(parts)


buckets = collections.defaultdict(list)
for w, z in words.items():
    if z < 3.0:                       # 生僻词不当替代品，否则负例明显不是人话、白送分
        continue
    s = sound(w)
    if s:
        buckets[(len(w), s)].append(w)
for k in buckets:
    buckets[k].sort()

# ---------- 第一遍：读七篇，取错段（正例）+ "真被听错过的同音写法"索引 ----------
cues, positives, err_index = [], [], collections.defaultdict(set)
for f in sorted((R / 'asr').glob('*.gt.jsonl')):
    keep = [r for r in (json.loads(s) for s in f.read_text('utf-8').splitlines() if s.strip())
            if not r.get('discard')]
    for k, r in enumerate(keep):
        text = r['text']
        lab, _ = align(text, r['gt'])
        errset = {p for p in range(len(text)) if HAN(text[p]) and lab.get(p) and text[p] != lab[p]}
        cues.append((f.stem, k, text, lab, errset))
        p = 0
        while p < len(text):
            if p in errset:
                q = p
                while q + 1 in errset:
                    q += 1
                if q - p + 1 <= 4:
                    src = text[p:q + 1]
                    truth = ''.join(lab[i] for i in range(p, q + 1))
                    positives.append(dict(video=f.stem, cue=k, begin=p, end=q + 1, source=src,
                                          truth=truth, sentence=text))
                    s = sound(truth)
                    if s and len(src) == len(truth):
                        err_index[(len(truth), s)].add(src)   # 真实发生过的同音听错写法
                p = q + 1
            else:
                p += 1


def alternatives(seg):
    """同音替代写法：先取真实听错过的写法，再退回公开词表同音词。"""
    s = sound(seg)
    if not s:
        return []
    out = [w for w in sorted(err_index.get((len(seg), s), set())) if w != seg]
    out += [w for w in buckets.get((len(seg), s), []) if w != seg and w not in out]
    return out


# ---------- 第二遍：造负例（原文正确，但能换成同音错写法）----------
negatives = []
for video, k, text, lab, errset in cues:
    last = -99
    for p in range(len(text)):
        if p - last < 8:
            continue
        for L in (2, 1):
            if p + L > len(text):
                continue
            seg = text[p:p + L]
            if not all(HAN(c) for c in seg):
                continue
            if any(i in errset for i in range(p - 1, p + L + 1)):
                continue              # 与错段挨着的片段不当负例
            if any(lab.get(i) is None or text[i] != lab[i] for i in range(p, p + L)):
                continue              # 必须逐字等于真值，才谈得上"本来就该保留"
            if seg not in words:
                continue              # 原片段本身得是词，否则对负例不公平
            alt = alternatives(seg)
            if not alt:
                continue
            negatives.append(dict(video=video, cue=k, begin=p, end=p + L, source=seg,
                                  wrong=alt[rng.randrange(len(alt))], sentence=text,
                                  from_error=bool(sorted(err_index.get((L, sound(seg) or ''), set())
                                                        - {seg}))))
            last = p
            break

print('题库：正例（该改）%d 条｜负例（不该改）%d 条｜同音替代读音串 %d 个' % (
    len(positives), len(negatives), len(buckets)))
print('  负例的替代写法来自"真实听错记录"的占比 %.1f%%' % (
    100.0 * sum(1 for x in negatives if x['from_error']) / max(len(negatives), 1)))

# ---------- 取样：每篇各取 per_video 条，A/B 位置随机，正负混排 ----------
items = []
for video in sorted({x['video'] for x in positives} | {x['video'] for x in negatives}):
    for flag in (True, False):
        pool = [x for x in (positives if flag else negatives) if x['video'] == video]
        rng.shuffle(pool)
        for x in pool[:args.per_video]:
            asr_v = x['sentence']
            other = x['truth'] if flag else x['wrong']
            other_v = asr_v[:x['begin']] + other + asr_v[x['end']:]
            a_ok = rng.random() < 0.5
            good, bad = (other_v, asr_v) if flag else (asr_v, other_v)   # good＝正确选项那版
            items.append(dict(kind='该改' if flag else '不该改', video=x['video'], cue=x['cue'],
                              begin=x['begin'], end=x['end'], source=x['source'], other=other,
                              A=good if a_ok else bad, B=bad if a_ok else good,
                              correct='A' if a_ok else 'B'))
if args.limit:
    items = items[:args.limit]
rng.shuffle(items)
print('送审 %d 条：该改 %d、不该改 %d' % (
    len(items), sum(1 for x in items if x['kind'] == '该改'), sum(1 for x in items if x['kind'] == '不该改')))

# ---------- 问 LLM（一条一问：上一轮证明送审粒度会改变答案）----------
HEAD = ('下面是一句话的两个版本 A 和 B，两版只有一处用词不同，其余完全一样。'
        '这句话来自语音识别转写，可能本来就对，也可能有一处听错。\n'
        '请判断哪一版更可能是说话人原本要表达的内容：结合整句语境、常用搭配与常识。\n'
        '只输出 JSON：{"choice":"A"} 或 {"choice":"B"}；若两版都说得通、确实无法区分，输出 {"choice":"都行"}。'
        '不要解释，不要多余文字。\n')


def ask(item):
    prompt = '%s【A】%s\n【B】%s\n' % (HEAD, item['A'], item['B'])
    payload = json.dumps(dict(model=MODEL, prompt=prompt, stream=False, think=False,
                              options=dict(temperature=0, num_predict=24)), ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(OLLAMA, data=payload, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode('utf-8')).get('response', '')


def parse(text):
    m = re.search(r'"choice"\s*:\s*"([^"]*)"', text)
    if not m:
        return None
    v = m.group(1).strip()
    return 'A' if v.startswith('A') else 'B' if v.startswith('B') else '都行' if ('都行' in v or '不确定' in v) else None


raw = []
for n, x in enumerate(items, 1):
    ans = ask(x)
    raw.append(ans)
    x['llm'] = parse(ans) or '未答'
    if n % 20 == 0:
        print('  已判 %d/%d' % (n, len(items)), flush=True)

# ---------- 算账 ----------
cell = collections.Counter()
for x in items:
    bad = 'B' if x['correct'] == 'A' else 'A'
    if x['llm'] == '都行':
        cell[x['kind'] + '_弃权'] += 1
    elif x['llm'] == '未答':
        cell[x['kind'] + '_未答'] += 1
    elif x['kind'] == '该改':
        cell['该改_选中真值' if x['llm'] == x['correct'] else '该改_仍选原文'] += 1
    else:
        cell['不该改_守住原文' if x['llm'] == x['correct'] else '不该改_被带跑'] += 1
    x['verdict_ok'] = (x['llm'] == x['correct'])
pos = [x for x in items if x['kind'] == '该改']
neg = [x for x in items if x['kind'] == '不该改']
right = sum(1 for x in items if x['verdict_ok'])
tie = cell['该改_弃权'] + cell['不该改_弃权']
pick_a = sum(1 for x in items if x['llm'] == 'A')
pick_b = sum(1 for x in items if x['llm'] == 'B')
print('\n==== 二选一结果（送审 %d 条；A/B 随机，未说明哪版被改）====' % len(items))
for k in sorted(cell):
    print('  %-14s %d 条' % (k, cell[k]))
print('  判对率 %d/%d＝%.1f%%｜正例抓到真值 %d/%d＝%.1f%%｜负例守住原文 %d/%d＝%.1f%%' % (
    right, len(items), 100.0 * right / max(len(items), 1),
    cell['该改_选中真值'], len(pos), 100.0 * cell['该改_选中真值'] / max(len(pos), 1),
    cell['不该改_守住原文'], len(neg), 100.0 * cell['不该改_守住原文'] / max(len(neg), 1)))
print('  弃权"都行" %d 条（%.1f%%）｜选 A %d 次、选 B %d 次（位置偏好，理想各半）' % (
    tie, 100.0 * tie / max(len(items), 1), pick_a, pick_b))
by_len = collections.defaultdict(collections.Counter)
for x in items:
    by_len[x['end'] - x['begin']]['对' if x['verdict_ok'] else '错'] += 1
print('  按片段长度：', {str(k): dict(v) for k, v in sorted(by_len.items())})

(OUT / 'llm_ab.json').write_text(json.dumps(dict(
    model=MODEL, think=False, temperature=0, seed=args.seed, per_video=args.per_video,
    pool=dict(positives=len(positives), negatives=len(negatives),
              neg_from_real_error_pct=round(100.0 * sum(1 for x in negatives if x['from_error']) /
                                            max(len(negatives), 1), 1)),
    bucket_sound_strings=len(buckets), asked=len(items), cells=dict(cell),
    accuracy=round(right / max(len(items), 1), 4), pick_A=pick_a, pick_B=pick_b,
    by_length={str(k): dict(v) for k, v in sorted(by_len.items())},
    items=items), ensure_ascii=False, indent=2), encoding='utf-8')
tsv = ['kind\tvideo\tcue\tbegin\tend\t长度\t原词\t另一版写法\t正确选项\tLLM\t判对\t窗口']
for x in items:
    tsv.append('%s\t%s\t%d\t%d\t%d\t%d\t%s\t%s\t%s\t%s\t%s\t%s' % (
        x['kind'], x['video'], x['cue'], x['begin'], x['end'], x['end'] - x['begin'], x['source'], x['other'],
        x['correct'], x['llm'], '对' if x['verdict_ok'] else '错',
        x['A'][max(0, x['begin'] - 6):x['end'] + 6]))
(OUT / 'llm_ab_items.tsv').write_text('\n'.join(tsv) + '\n', encoding='utf-8')
(OUT / 'llm_ab_raw.txt').write_text('\n'.join(raw), encoding='utf-8')
print('写出 experiments/E051/results/llm_ab.json、llm_ab_items.tsv')
