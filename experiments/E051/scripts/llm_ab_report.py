#!/usr/bin/env python3
"""把 llm_ab.json 摊开成可复核的清单：每类逐条列出窗口、原词、另一版写法、谁对、LLM 选了谁。

用途：判"被带跑/仍选原文"的条目必须人眼过一遍——同音负例里存在两版都说得通的情况
（例如"要想/要向"），模型输了这一条不代表它真错，所以要把这些条目单独交给园长看。
"""
import collections, json, pathlib, sys

R = pathlib.Path(__file__).resolve().parents[2].parent
sys.stdout.reconfigure(encoding='utf-8')
d = json.loads((R / 'experiments/E051/results/llm_ab.json').read_text('utf-8'))
groups = collections.defaultdict(list)
for x in d['items']:
    bad = 'B' if x['correct'] == 'A' else 'A'
    key = (x['kind'] + ('_对' if x['verdict_ok'] else '_弃权' if x['llm'] == '都行' else '_错'))
    groups[key].append(x)
lines = ['分类\t视频\tcue\t长度\t原词\t另一版\t正确\tLLM\t窗口（正确版）\t窗口（错误版）']
for key in sorted(groups):
    for x in groups[key]:
        good = x['A'] if x['correct'] == 'A' else x['B']
        badv = x['B'] if x['correct'] == 'A' else x['A']
        w = lambda t: t[max(0, x['begin'] - 6):x['end'] + 6]
        lines.append('%s\t%s\t%d\t%d\t%s\t%s\t%s\t%s\t%s\t%s' % (
            key, x['video'], x['cue'], x['end'] - x['begin'], x['source'], x['other'],
            x['correct'], x['llm'], w(good), w(badv)))
(R / 'experiments/E051/results/llm_ab_audit.tsv').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print('分类小计：', {k: len(v) for k, v in sorted(groups.items())})
print('写出 experiments/E051/results/llm_ab_audit.tsv（逐条含正确版/错误版对照，交园长复核）')
for key in sorted(k for k in groups if k.endswith('_错')):
    print('\n--- %s（%d 条，需人眼复核）---' % (key, len(groups[key])))
    for x in groups[key][:12]:
        good = x['A'] if x['correct'] == 'A' else x['B']
        badv = x['B'] if x['correct'] == 'A' else x['A']
        print('  %s %d字 %s↔%s｜正确版「%s」｜错版「%s」' % (
            x['video'][:12], x['end'] - x['begin'], x['source'], x['other'],
            good[max(0, x['begin'] - 6):x['end'] + 6], badv[max(0, x['begin'] - 6):x['end'] + 6]))
