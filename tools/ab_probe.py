#!/usr/bin/env python3
"""A/B 快速核对：旧滑窗 arm vs 新动态分词窗口 arm。"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parents[1]
NEW = str(ROOT / "build-gcc" / "text_clean.exe")
OLD = str(ROOT / "build-legacy" / "text_clean_legacy.exe")
HIT_RE = re.compile(
    r'\[(exact|pinyin|fuzzy)\] status=(\S+) (\d+)\.\.(\d+) "(.*?)" -> "(.*?)" '
    r'entry=(\d+) distance=(\d+) score=(\S+) logR=(\S+) fC=(\d+) fO=(\d+) action=(\S+)')


def run(exe: str, text: str, flags=()):
    proc = subprocess.run([exe, "-v", *flags], input=text.encode("utf-8"),
                          capture_output=True, cwd=ROOT)
    return HIT_RE.findall(proc.stderr.decode("utf-8", "replace")), \
           proc.stdout.decode("utf-8", "replace")


CASES = [
    "经谈话核实后，谈话人员现场制作了笔录",
    "李文亮医生在微信群中转发发布",
    "转帐给你了",
    "这是薇信支付的",
    "用手机维信转账",
    "他在支富宝里充值",
    "银行喀哒余额不足",
    "同事陪同下来到该派出所",
]

for case in CASES:
    print("=" * 70)
    print("输入:", case)
    for label, exe in (("旧滑窗", OLD), ("新窗口", NEW)):
        hits, out = run(exe, case)
        print(f"  {label}: {len(hits)} 命中 -> {out.strip()}")
        for h in hits:
            print(f"     [{h[0]}] {h[2]}..{h[3]} {h[4]}->{h[5]} D={h[7]} "
                  f"fC={h[10]} fO={h[11]} action={h[12]}")
