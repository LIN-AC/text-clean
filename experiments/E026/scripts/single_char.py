#!/usr/bin/env python3
"""E026 补充：S1a 单字错误（占真值错误 70.6%）到底是什么性质。

问题：这类错误能不能靠"补更长的词"顺带解决，还是必须允许单字窗口？
"""
import collections, json, pathlib, sys

R = pathlib.Path(__file__).resolve().parents[3]
O = R / 'experiments/E026/results'
sys.path.insert(0, str(R / 'experiments/E026/scripts'))
import replica as RP
sys.stdout.reconfigure(encoding='utf-8')

errors = json.loads((O / 'errors.json').read_text(encoding='utf-8'))
applied = json.loads((O / 'run_cache.json').read_text(encoding='utf-8'))['run']['Z2']

single = [e for e in errors if len(e['original']) == 1]
fixed = [e for e in single if e['Z2']['applied']]
print('单字错误实例=%d，其中 Z2 已改对=%d（全靠更大的窗口顺带改掉）' % (len(single), len(fixed)))

tone_same = tone_diff = base_diff = unreachable = 0
rescue_by_pool = 0
longer_target = collections.Counter()
no_evidence = []
for e in single:
    o, t = e['original'], e['truth']
    ro, rt = RP.CHAR_READS.get(o, set()), RP.CHAR_READS.get(t, set())
    if not ro or not rt:
        unreachable += 1
    elif {RP.base_of(x) for x in ro} & {RP.base_of(y) for y in rt}:
        if any(x == y for x in ro for y in rt):
            tone_same += 1
        else:
            tone_diff += 1
    else:
        base_diff += 1
    # 是否存在"包含该位置的 2~4 字窗口，其真值本身就是启用目标词"
    for n in (2, 3, 4):
        for st in range(max(0, e['local'] - n + 1), e['local'] + 1):
            span_t = e['line_truth'][st:st + n]
            span_o = e['line_text'][st:st + n]
            if len(span_t) == n and span_t in RP.TARGETS and span_o != span_t:
                longer_target[n] += 1
                rescue_by_pool += 1
                break
        else:
            continue
        break
print('  同音节同声调(严格同音)=%d  同基音不同调=%d  基音不同(近音)=%d  读音表缺字=%d' % (
    tone_same, tone_diff, base_diff, unreachable))
print('  可通过"包含该字的更长启用目标词"顺带命中的实例=%d，按窗口长度分布=%s' % (
    rescue_by_pool, dict(sorted(longer_target.items()))))

zc = collections.Counter()
for e in single:
    zo, zt = RP.CHAR_ZIPF.get(e['original']), RP.CHAR_ZIPF.get(e['truth'])
    if zo is None or zt is None:
        zc['字频缺项'] += 1
    elif zt >= zo:
        zc['真值字比 ASR 字更常见'] += 1
    else:
        zc['ASR 字更常见(方向相反)'] += 1
print('  单字层面的频率方向:', dict(zc))

# 上报候选：真值字本身极生僻 / 真值疑似错字
sus = []
for e in single:
    if e['Z2']['applied']:
        continue
    zo, zt = RP.ZIPF.get(e['original']), RP.ZIPF.get(e['truth'])
    cz = RP.CHAR_ZIPF.get(e['truth'], 0)
    if cz < 1.5 and zo:
        sus.append((e, zo, cz))
sus.sort(key=lambda x: x[2])
print('\n=== 单字里真值字极生僻（zipf<1.5）的实例 %d 个，前 10（仅上报，不改）===' % len(sus))
for e, zo, cz in sus[:10]:
    print('  %s:%d  ASR"%s" → 真值"%s"  字频 zipf: ASR=%.2f 真值=%.2f  上下文…%s…' % (
        e['video'], e['begin'], e['original'], e['truth'], RP.CHAR_ZIPF.get(e['original'], -1), cz,
        e['line_text'][max(0, e['local'] - 5):e['local'] + 6]))
json.dump(dict(single_total=len(single), single_fixed=len(fixed), tone_same=tone_same, tone_diff=tone_diff,
               base_diff=base_diff, no_reading=unreachable, longer_window_rescuable=rescue_by_pool,
               longer_by_n=dict(longer_target), rare_truth=len(sus)),
          (O / 'single_char_summary.json').open('w', encoding='utf-8'), ensure_ascii=False, indent=1)
