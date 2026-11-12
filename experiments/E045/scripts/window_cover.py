#!/usr/bin/env python3
"""复算窗长证据的累计覆盖率：4/5/6…字窗口分别能覆盖多少错字（供园长直接看结论）。"""
import json, pathlib, sys

R = pathlib.Path(__file__).resolve().parents[3]
sys.stdout.reconfigure(encoding='utf-8')
d = json.loads((R / 'experiments/E045/results/window_evidence.json').read_text('utf-8'))
runs = {int(k): v for k, v in d['error_run_lengths'].items()}
tot = d['err_chars_total']
for cap in (2, 3, 4, 5, 6, 8):
    inside = sum(k * v for k, v in runs.items() if k <= cap)
    print('窗口上限 %d 字：覆盖 %d/%d 错字（%.1f%%），管不到 %d 字（%.1f%%）' % (
        cap, inside, tot, inside * 100.0 / tot, tot - inside, (tot - inside) * 100.0 / tot))
print('段长分布', runs, '错字总数', tot, '整段未对齐字数', d['unaligned_chars'])
