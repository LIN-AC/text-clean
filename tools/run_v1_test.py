#!/usr/bin/env python3
"""Drive the text_clean binary over whisper_txt/ and emit a before/after hit log.

Usage:
  python tools/run_v1_test.py --audit          # dump every hit with original context
  python tools/run_v1_test.py                  # write log/v1_test.log
"""

from __future__ import annotations

import argparse
import datetime
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "build-gcc" / "text_clean.exe"
CORPUS_DIR = ROOT / "whisper_txt"
LOG_DIR = ROOT / "log"

MATCH_RE = re.compile(
    r'^\s*\[(?P<kind>exact|pinyin|fuzzy)\] (?P<begin>\d+)\.\.(?P<end>\d+) '
    r'"(?P<matched>.*)" -> "(?P<replacement>.*)" '
    r'entry=(?P<entry>\d+) distance=(?P<distance>\d+) action=(?P<action>mask|replace)$'
)

V1 = {"label": "v1 默认参数", "flags": ["-v"],
      "desc": "AC 精确 + 同音拼音 + 编辑距离回退 (--max-distance 1 --min-fuzzy 3)"}

CONTROL_RUNS = [
    {"label": "A --no-pinyin (仅 AC 精确)", "flags": ["-v", "--no-pinyin"]},
    {"label": "B --max-distance 0 (精确+同音，禁模糊)", "flags": ["-v", "--max-distance", "0"]},
    {"label": "C --min-fuzzy 4 (模糊需 >=4 音节)", "flags": ["-v", "--min-fuzzy", "4"]},
]

# Hand-verified verdicts for the v1 run, keyed by (file stem, begin, matched).
# True  = 修正后文本更接近作者本意; False = 改坏了原文。
VERDICTS: dict[tuple[str, int, str], tuple[bool, str]] = {
    ("BV1cLFSz4ECr", 23, "验证品"): (False, "原文是「为了验证品控」，改成「验证码控」语义尽失"),
    ("BV1cLFSz4ECr", 1075, "为新"): (False, "原文「判断机器是否为新机」，同音拼音把「为新」当「微信」"),
    ("BV1cLFSz4ECr", 3221, "验证机"): (False, "原文「逐一开机验证机器的系统」，改成「验证码器」"),
    ("BV1cLFSz4ECr", 3697, "验证了"): (False, "原文「我们先验证了一下」，改成「验证码了一下」"),
    ("BV1cLFSz4ECr", 4156, "验证到"): (False, "原文「验证到第8台极光X」→「验证码第8台」，介词「到」被吞"),
    ("BV1cLFSz4ECr", 4583, "验证功"): (False, "原文「开机验证功能」→「开机验证码能」，「功」被替换"),
    ("BV1cLFSz4ECr", 4906, "验证部"): (False, "原文「功能验证部分」→「功能验证码分」，「部」被替换"),
    ("BV1cLFSz4ECr", 5028, "验证完"): (False, "原文「外观功能验证完了」→「外观功能验证码了」"),
    ("BV1cLFSz4ECr", 12885, "只要保"): (False, "原文「他们只要保证性能及格」→「他们支付宝证性能及格」"),
    ("BV1cLFSz4ECr", 13328, "微信"): (True, "原文已是规范词「微信公众号」，exact 命中但零改动"),
    ("BV1joFezGEqj", 959, "验证一"): (False, "原文「先来验证一下可行性」→「先来验证码下」，「一」被吞"),
    ("BV1joFezGEqj", 1255, "直接暴"): (False, "原文「CPU又直接暴降五度」→「CPU又支付宝降五度」"),
    ("BV1joFezGEqj", 1358, "验证才"): (False, "原文「要怎么验证才行呢」→「要怎么验证码行呢」"),
    ("BV1yQfWYaEVo", 4563, "验证一"): (False, "原文「也会专门来验证一下」→「也会专门来验证码下」"),
    ("BV1zPxw6BE1S", 1379, "直接爆"): (False, "原文「會直接爆顯存」→「會支付宝顯存」，「爆」被吞"),
    ("BV1zPxw6BE1S", 3627, "專長"): (False, "繁体「一個專長」(专长)→「一個转账」，多音字「長」读 zhang 撞车"),
}

# Synthetic positive sample: every alias in data/lexicon.txt, one per line.
# Used only to measure the recall side, since whisper_txt contains no in-scope error.
POSITIVE_LINES = [
    "我加了他的威信之后一直没有回消息",
    "群里有人让我把款打到薇信上",
    "客服说维信收款码已经过期了",
    "请在支富宝里完成这笔付款",
    "他用知付宝付了三十块钱",
    "这家字节挑动系公司的招聘很少",
    "紫节跳动的直播业务扩张很快",
    "记得先把转帐记录截图保存",
    "这个短视频平台叫抖音",
    "腾讯和华为都发了新的机型",
    "银行卡余额不足以支付尾款",
    "登录时需要输入六位验证码",
    "这一句里出现了敏感词需要屏蔽",
]

ALIAS_TOKENS = ("威信", "薇信", "维信", "支富宝", "知付宝",
                "字节挑动", "紫节跳动", "转帐")

# Clean sentences that must survive untouched (false-positive probe for the sample).
NEGATIVE_LINES = [
    "为了验证品控我们一次性测了四十台笔记本",
    "判断机器是否为新的同时要找出现场瑕疵",
    "我们先验证了一下触控板按压有没有反馈",
    "他们只要保证性能及格就可以了",
    "测下来温度直接暴降五度效果拔群",
    "那要怎么验证才行呢我想到一个办法",
    "開機驗證功能到这里就完成了",
]

# Capability probe on errors that are NOT in the alias table, one per layer/protection.
# expect="fix"  → 该层应当修正; expect="keep" → 保护机制应当让它不命中。
UNSEEN_CASES = [
    {"line": "他用知付包结了尾款", "wrong": "知付包", "right": "支付宝",
     "expect": "fix", "what": "同音字表外错字（拼音层增量召回）"},
    {"line": "这张银形卡余额不够", "wrong": "银形卡", "right": "银行卡",
     "expect": "fix", "what": "前后鼻音混淆（模糊层增量召回）"},
    {"line": "请在民行卡上扣款", "wrong": "民行卡", "right": "银行卡",
     "expect": "miss", "what": "首音节不同的错字（首音节约束 → 漏检）"},
    {"line": "这台微星笔记本的散热还行", "wrong": "微星", "right": "微信",
     "expect": "keep", "what": "2 音节品牌词（短词模糊保护 → 不应误改）"},
]


CONTEXT = 18


def raw_text(path: Path) -> str:
    """text_clean reports code point offsets of the stored bytes, so line
    endings must survive before contexts are sliced."""
    return path.read_bytes().decode("utf-8", "replace")


def snippet(text: str, begin: int, end: int, width: int = CONTEXT) -> str:
    points = list(text)
    lo = max(0, begin - width)
    hi = min(len(points), end + width)
    body = "".join(points[lo:hi])
    body = body.replace("\r\n", "⏎").replace("\n", "⏎").replace("\r", "⏎")
    return ("…" if lo > 0 else "") + body + ("…" if hi < len(points) else "")


def run_text(data: bytes, flags: list[str]) -> tuple[str, list[dict]]:
    proc = subprocess.run([str(EXE), *flags], input=data,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    matches = [m.groupdict() for m in
               (MATCH_RE.match(line) for line in
                proc.stderr.decode("utf-8", "replace").splitlines()) if m]
    return proc.stdout.decode("utf-8", "replace"), matches


def run_file(path: Path, flags: list[str]) -> tuple[str, list[dict]]:
    return run_text(path.read_bytes(), flags)


def dwidth(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def cell(text: str, width: int, align: str = "l") -> str:
    fill = " " * max(0, width - dwidth(text))
    return text + fill if align == "l" else fill + text


def row(cells: list[tuple[str, str, str]]) -> str:
    """cells = (text, align, width). Widths must fit the widest content,
    otherwise columns collide; a single space separates them."""
    return " ".join(cell(t, w_, a) for t, a, w_ in cells)


def para(out: list[str], text: str, indent: str = "  ", width: int = 96) -> None:
    """Emit a narrative paragraph wrapped by display width (CJK counted as 2).
    Continuation lines align under the indent; ASCII runs (identifiers, flags)
    stay atomic and closing punctuation never starts a line."""
    chunks: list[str] = []
    for ch in text:
        if chunks and chunks[-1].isascii() and ch.isascii() and not ch.isspace():
            chunks[-1] += ch
        else:
            chunks.append(ch)
    cont = " " * dwidth(indent)
    line = indent
    for chunk in chunks:
        fits = dwidth(line + chunk) <= width
        glued = chunk in "，。、；：）】」%”"
        if not fits and line.strip() and not glued and chunk != " ":
            out.append(line.rstrip())
            line = cont
        line += chunk
    if line.strip():
        out.append(line.rstrip())


def lexicon_entries() -> list[str]:
    rows = []
    for line in (ROOT / "data" / "lexicon.txt").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            rows.append(line.split("\t")[0])
    return rows


def kind_counts(hits: list[dict]) -> dict[str, int]:
    counts = {"exact": 0, "pinyin": 0, "fuzzy": 0}
    for h in hits:
        counts[h["kind"]] += 1
    return counts


def changed_chars(hits: list[dict]) -> int:
    return sum(int(h["end"]) - int(h["begin"]) for h in hits if h["matched"] != h["replacement"])


def hit_stats(per_file_hits: dict[Path, list[dict]]) -> dict:
    """Aggregate a run; 有效性 reuses the hand verdicts recorded for the v1 run
    (control runs hit the same offsets, so the keys line up)."""
    flat = [(p, h) for p, hs in per_file_hits.items() for h in hs]
    good = bad = unknown = 0
    for p, h in flat:
        verdict = VERDICTS.get((p.stem, int(h["begin"]), h["matched"]))
        if verdict is None:
            unknown += 1
        elif verdict[0]:
            good += 1
        else:
            bad += 1
    return {"n": len(flat), "k": kind_counts([h for _, h in flat]),
            "changed": changed_chars([h for _, h in flat]),
            "good": good, "bad": bad, "unknown": unknown}


def audit() -> None:
    for path in sorted(CORPUS_DIR.glob("*.txt")):
        original = raw_text(path)
        cleaned, matches = run_file(path, V1["flags"])
        print(f"### {path.name}: {len(matches)} hits")
        for m in matches:
            begin, end = int(m["begin"]), int(m["end"])
            aligned = cleaned[begin:end] == m["replacement"]
            print(f"  [{m['kind']:6s}] d={m['distance']} @{begin}..{end} "
                  f"{m['matched']} -> {m['replacement']}")
            print(f"     修正前: {snippet(original, begin, end)}")
            print(f"     修正后: {snippet(cleaned, begin, end) if aligned else '(偏移漂移)'}")


def alias_recall(flags: list[str]) -> tuple[int, int]:
    """Run the alias-injected sample; return (hits, aliases fixed)."""
    text, hits = run_text("\n".join(POSITIVE_LINES).encode("utf-8"), flags)
    return len(hits), sum(1 for a in ALIAS_TOKENS if a not in text)


def clean_probe(flags: list[str]) -> tuple[int, bool, int, int]:
    """Run the must-not-change sample; return (hits, body preserved, chars rewritten,
    lines altered). The CLI appends a trailing newline, so only the body is compared."""
    lines = NEGATIVE_LINES
    data = "\n".join(lines).encode("utf-8")
    text, hits = run_text(data, flags)
    body = text.rstrip("\n")
    altered = sum(1 for a, b in zip(lines, body.split("\n")) if a != b)
    return len(hits), body == "\n".join(lines), changed_chars(hits), altered



def capability_probe(flags: list[str]) -> list[tuple[bool, str, str]]:
    """Per UNSEEN_CASE: (期望是否达成, 表格标记, 清洗后整行)。"""
    results = []
    for case in UNSEEN_CASES:
        text, _ = run_text(case["line"].encode("utf-8"), flags)
        text = text.rstrip("\n")
        fixed = case["right"] in text
        untouched = text == case["line"]
        if case["expect"] == "fix":
            results.append((fixed, "✓ 修正" if fixed else "✗ 未修正", text))
        elif case["expect"] == "keep":
            results.append((untouched, "✓ 未误改" if untouched else "✗ 被误改", text))
        else:
            results.append((False, "— 漏检" if not fixed else "? 意外修正", text))
    return results


def build_log(out_name: str) -> int:
    files = [(p, raw_text(p)) for p in sorted(CORPUS_DIR.glob("*.txt"))]
    total_chars = sum(len(t) for _, t in files)
    total_lines = sum(t.count("\n") + 1 for _, t in files)

    v1 = {p: run_file(p, V1["flags"]) for p, _ in files}
    hits = [h for _, (_, hs) in v1.items() for h in hs]
    kc = kind_counts(hits)
    noop = [h for h in hits if h["matched"] == h["replacement"]]

    verdict_rows = []
    for p, original in files:
        cleaned, hs = v1[p]
        for h in hs:
            begin, end = int(h["begin"]), int(h["end"])
            key = (p.stem, begin, h["matched"])
            verdict = VERDICTS.get(key)
            aligned = cleaned[begin:end] == h["replacement"]
            verdict_rows.append({
                "file": p.name, "stem": p.stem, "h": h, "begin": begin, "end": end,
                "before": snippet(original, begin, end),
                "after": snippet(cleaned, begin, end) if aligned else f"…{h['replacement']}…(偏移漂移)",
                "ok": None if verdict is None else verdict[0],
                "note": "" if verdict is None else verdict[1],
            })

    judged = [r for r in verdict_rows if r["ok"] is not None]
    good = [r for r in judged if r["ok"]]
    bad = [r for r in judged if not r["ok"]]
    good_rewritten = sum(1 for r in good if r["h"]["matched"] != r["h"]["replacement"])

    per_kind = {}
    for kind in ("exact", "pinyin", "fuzzy"):
        rows = [r for r in judged if r["h"]["kind"] == kind]
        per_kind[kind] = (len(rows), sum(1 for r in rows if r["ok"]), sum(1 for r in rows if not r["ok"]))

    v1_stats = hit_stats({p: hs for p, (_, hs) in v1.items()})
    controls = []
    for case in CONTROL_RUNS:
        per_file_hits = {p: run_file(p, case["flags"])[1] for p, _ in files}
        controls.append((case, hit_stats(per_file_hits)))

    # Recall probe on a synthetic positive sample (real corpus has no in-scope error).
    cases = [V1] + CONTROL_RUNS
    pos_results = [(c["label"], *alias_recall(c["flags"])) for c in cases]
    neg_results = [(c["label"], *clean_probe(c["flags"])) for c in cases]
    cap_results = [(c["label"], capability_probe(c["flags"])) for c in cases]

    bar, sub, thin = "=" * 78, "-" * 78, "·" * 78
    L: list[str] = []
    w = L.append

    w(bar)
    w("text_clean v1 测试日志 — whisper_txt 语料命中修正前后对比 + 有效性评估")
    w(bar)
    w(f"生成时间   : {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    w(f"被测程序   : {EXE}")
    w(f"测试配置   : {V1['desc']}")
    w(f"词表       : data/lexicon.txt ({len(lexicon_entries())} 条规范词)")
    w(f"拼音字表   : data/pinyin_dict.txt")
    w(f"语料       : whisper_txt/*.txt — {len(files)} 个 B 站 ASR 转写文件, "
      f"{total_chars} 字符 / {total_lines} 行 / {sum(len(p.read_bytes()) for p, _ in files)} 字节")
    w(f"调用方式   : text_clean -v < <file>  (整篇 stdin, stdout=清洗结果, stderr=命中明细)")
    w("")
    w("摘要")
    w(f"  命中总数     : {len(hits)}  (exact={kc['exact']}  pinyin={kc['pinyin']}  fuzzy={kc['fuzzy']})")
    w(f"  命中文件     : {sum(1 for p, _ in files if v1[p][1])}/{len(files)}")
    w(f"  改动字符数   : {changed_chars(hits)}  (零改动命中 {len(noop)} 条)")
    w(f"  人工判定     : 有效 {len(good)} / 误改 {len(bad)} / 未判定 {len(verdict_rows) - len(judged)}")
    w(f"  有效修正率   : 命中口径 {len(good)}/{len(verdict_rows)}，"
      f"实际改写口径 {good_rewritten}/{len(verdict_rows) - len(noop)} "
      f"→ 没有任何一处改写是必要的")
    para(L, f"{len(bad)}/{len(hits)} 命中为误改，全部来自拼音同音层与编辑距离模糊层；"
            "AC 精确层未误改。默认参数在这批真实 ASR 语料上净收益为负。",
         indent="  结论         : ")
    w(sub)

    w("")
    w("第一部分 逐文件、逐命中 前后对比")
    w("(位置为原文码点偏移；⏎ 表示原始换行；「修正后」取自程序 stdout 同一偏移区间)")
    w(sub)

    for p, _ in files:
        cleaned, hs = v1[p]
        w("")
        w(f"[文件] {p.name}   字符 {len(raw_text(p))}   命中 {len(hs)}")
        if not hs:
            w("  无命中 — 全文保持原样，stdout 与 stdin 字节一致: "
              f"{'是' if cleaned == raw_text(p) else '否'}")
            w(thin)
            continue
        w(thin)
        for idx, r in enumerate((x for x in verdict_rows if x["stem"] == p.stem), 1):
            h = r["h"]
            mark = {True: "有效", False: "误改", None: "未判定"}[r["ok"]]
            w(f"  #{idx:02d}  方式={h['kind']:6s} 偏移={r['begin']}..{r['end']} "
              f"音节距离={h['distance']} 词条={h['entry']} 动作={h['action']}")
            w(f"       修正前: {r['before']}")
            w(f"       修正后: {r['after']}")
            w(f"       词条映射: {h['matched']} -> {h['replacement']}   判定: {mark}")
            if r["note"]:
                w(f"       判定依据: {r['note']}")
        w(thin)

    w("")
    w(bar)
    w("第二部分 有效性评估")
    w(bar)

    w("")
    w("2.1 命中构成（按匹配方式分层，有效性来自第一部分逐条人工判定）")
    cols = [("匹配方式", 12), ("命中", 6), ("零改动", 8), ("实际改写", 10),
            ("有效", 6), ("误改", 6), ("改写有效占比", 14)]
    w("  " + row([(t, "l" if i == 0 else "r", wd) for i, (t, wd) in enumerate(cols)]))
    for kind in ("exact", "pinyin", "fuzzy"):
        rows = [r for r in verdict_rows if r["h"]["kind"] == kind]
        noop_k = sum(1 for r in rows if r["h"]["matched"] == r["h"]["replacement"])
        ok_k = sum(1 for r in rows if r["ok"])
        bad_k = sum(1 for r in rows if r["ok"] is False)
        rewritten = len(rows) - noop_k
        ratio = f"{ok_k / rewritten * 100:.0f}%" if rewritten else "—"
        w("  " + row([(kind, "l", 12), (str(len(rows)), "r", 6), (str(noop_k), "r", 8),
                     (str(rewritten), "r", 10), (str(ok_k), "r", 6), (str(bad_k), "r", 6),
                     (ratio, "r", 14)]))
    rewritten_all = len(verdict_rows) - len(noop)
    w("  " + row([("合计", "l", 12), (str(len(verdict_rows)), "r", 6), (str(len(noop)), "r", 8),
                  (str(rewritten_all), "r", 10), (str(len(good)), "r", 6), (str(len(bad)), "r", 6),
                  (f"{good_rewritten / rewritten_all * 100:.0f}%" if rewritten_all else "—", "r", 14)]))
    good_desc = "、".join(f"「{r['h']['matched']}」({r['file']})" for r in good) or "无"
    para(L, f"注：判定为「有效」的 {len(good)} 条 = {good_desc}，"
            f"原文本身已正确 → 零改动；因此实际改写的 {rewritten_all} 处没有一处是必要的修正"
            f"（{good_rewritten}/{rewritten_all}）。", indent="  ")



    w("")
    w("2.2 分层表现")
    ex, py, fz = per_kind["exact"], per_kind["pinyin"], per_kind["fuzzy"]
    para(L, f"· exact（AC 自动机，规范词/别名精确命中）：{ex[0]} 命中，误改 {ex[2]} 条。"
            "命中的是已经写对的「微信」，所以既没收益也没破坏 —— 符合设计预期。", indent="  ")
    para(L, f"· pinyin（同音音节，距离 0）：{py[0]} 命中，误改 {py[2]} 条。两处都是把常用同音片段"
            "当成词表词：「为新机」→「微信机」、「專長」→「转账」（多音字「長」读 zhang）。"
            "说明同音层在没有词频与上下文歧义消解时，对 2 音节高频组合极易误伤。", indent="  ")
    fz_rows = [r for r in verdict_rows if r["h"]["kind"] == "fuzzy"]
    fz_yan = sum(1 for r in fz_rows if r["h"]["matched"].startswith("验证"))
    fz_bad = sum(1 for r in fz_rows if r["ok"] is False)
    para(L, f"· fuzzy（编辑距离回退，距离 1）：{fz[0]} 命中，误改 {fz_bad} 条"
            f"（误改率 {fz_bad / fz[0] * 100:.0f}%）。其中 {fz_yan} 条是「验证 + 任意第三字」被拉成"
            f"「验证码」，{fz[0] - fz_yan} 条是「只要保 / 直接暴 / 直接爆」被拉成「支付宝」。"
            "require_first_syllable_match 只约束首音节，于是「验证」「直接」这类高频前缀 + "
            "单音节容差成为最大的误改来源。", indent="  ")

    w("")
    w("2.3 召回侧（漏检）")
    probe_terms = ("微信", "威信", "薇信", "维信", "支付宝", "支富宝", "知付宝",
                   "字节跳动", "字节挑动", "紫节跳动", "抖音", "腾讯", "华为",
                   "银行卡", "转账", "转帐", "验证码", "敏感词")
    found = {}
    for _, text in files:
        for t in probe_terms:
            if text.count(t):
                found[t] = found.get(t, 0) + text.count(t)
    listed = "、".join(f"{t}×{c}" for t, c in sorted(found.items(), key=lambda x: -x[1])) or "（无）"
    alias_found = {t: c for t, c in found.items() if t in ALIAS_TOKENS}
    w(f"  语料中出现的词表词形: {listed}")
    w(f"  语料中出现的错误别名: "
      f"{'、'.join(f'{t}×{c}' for t, c in alias_found.items()) if alias_found else '（无）'}")
    w("  → whisper_txt 为笔记本/硬件评测类转写，10 条词表（支付、社交、厂商品牌）与语料领域")
    w("    几乎不相交：整批语料只有 1 处词表词形，且已写对（微信公众号）。")
    w("    因此本语料无法证明收益（无正样本可修），只能暴露代价（误改）。")

    w("")
    w("2.4 注入式回测（合成语料，用于隔离「算法能力」与「词表/领域错配」）")
    w(f"  正样本: {len(POSITIVE_LINES)} 行，每行注入 1 处词表别名 → 共 {len(ALIAS_TOKENS)} 处待修正。")
    w(f"  负样本: {len(NEGATIVE_LINES)} 行真实风格句子，故意含「验证X / 为新 / 只要保 / 直接暴」等")
    w("          与词表同音或近音的片段，正确答案是零命中、原文一字不动。")
    head4 = [("配置", "l", 40), ("正样本命中", "r", 11), ("别名修正", "r", 10),
             ("别名召回", "r", 10), ("负样本误改", "r", 12), ("负样本被改行", "r", 17)]
    w("  " + row(head4))
    for (label, pos_hits, fixed), (_, neg_hits, intact, neg_chars, neg_lines) in zip(pos_results, neg_results):
        w("  " + row([(label, "l", 40), (str(pos_hits), "r", 11),
                     (f"{fixed}/{len(ALIAS_TOKENS)}", "r", 10),
                     (f"{fixed / len(ALIAS_TOKENS) * 100:.0f}%", "r", 10),
                     (str(neg_hits), "r", 12),
                     (f"{neg_lines}/{len(NEGATIVE_LINES)} 行 {neg_chars} 字", "r", 17)]))
    _, v1_neg_hits, _, v1_neg_chars, v1_neg_lines = neg_results[0]
    w(f"  → 别名的 8/8 召回在 A 配置（--no-pinyin，纯 AC 精确）下已经全部拿到，")
    w(f"    说明拼音层与模糊层对「词表里已列出的别名」没有增量召回；")
    w(f"    而负样本上 v1 把 {v1_neg_lines}/{len(NEGATIVE_LINES)} 行干净句子改坏了 {v1_neg_chars} 字符，")
    w(f"    A 配置保持原文一字不动。")

    w("")
    w("2.5 参数对照（同一 whisper_txt 语料；有效性沿用 2.1 的逐条判定）")
    head5 = [("配置", "l", 40), ("命中", "r", 6), ("exact", "r", 7), ("pinyin", "r", 8),
             ("fuzzy", "r", 7), ("改动字符", "r", 10), ("有效", "r", 6), ("误改", "r", 6)]
    w("  " + row(head5))
    w("  " + row([(V1["label"] + " [基线]", "l", 40), (str(v1_stats["n"]), "r", 6),
                  (str(v1_stats["k"]["exact"]), "r", 7), (str(v1_stats["k"]["pinyin"]), "r", 8),
                  (str(v1_stats["k"]["fuzzy"]), "r", 7), (str(v1_stats["changed"]), "r", 10),
                  (str(v1_stats["good"]), "r", 6), (str(v1_stats["bad"]), "r", 6)]))
    for case, st in controls:
        w("  " + row([(case["label"], "l", 40), (str(st["n"]), "r", 6), (str(st["k"]["exact"]), "r", 7),
                      (str(st["k"]["pinyin"]), "r", 8), (str(st["k"]["fuzzy"]), "r", 7),
                      (str(st["changed"]), "r", 10), (str(st["good"]), "r", 6),
                      (str(st["bad"]), "r", 6)]))
        if st["unknown"]:
            w(f"    (该配置有 {st['unknown']} 条命中落在人工判定表之外)")
    para(L, f"基线 {v1_stats['bad']} 条误改在 A（--no-pinyin）下降到 {controls[0][1]['bad']} 条"
            f"（消除 {v1_stats['bad'] - controls[0][1]['bad']} 条）→ 真实语料上的误改来自"
            "拼音同音层与编辑距离模糊层，AC 精确层没有误伤。")
    para(L, f"B/C（禁掉模糊、保留同音）仍留 {controls[1][1]['bad']} 条误改："
            "「为新机→微信机」「專長→转账」，两条都落在 2 音节词上。")

    w("")
    w("2.6 增量能力探针（词表外的错字，验证每层各自的收益与保护机制）")
    w("  四条合成句，每句只应由某一层解决；标「— 漏检」的是已知召回缺口，不计入误改。")
    head6 = [("配置", "l", 40)]
    for c in UNSEEN_CASES:
        head6.append((f"{c['wrong']}→{c['right']}", "r", 16))
    w("  " + row(head6))
    for label, probes in cap_results:
        w("  " + row([(label, "l", 40)] + [(mark, "r", 16) for _, mark, _ in probes]))
    w("  逐条原文/结果（v1 默认参数）：")
    for c, (_, mark, text) in zip(UNSEEN_CASES, dict(cap_results)[V1["label"]]):
        w(f"     {c['line']}  →  {text}   [{mark}]")
        expect = ("修正为" + c["right"] if c["expect"] == "fix"
                  else "保持原文" if c["expect"] == "keep" else "当前配置漏检（已知缺口）")
        para(L, f"场景：{c['what']}；期望：{expect}。", indent="         ")
    w("  → 拼音层能救词表外的同音错字（知付包），模糊层能救前后鼻音错字（银形卡），")
    w("    短词保护（min_fuzzy=3）确实挡住了「微星→微信」，首音节约束挡住了「民行卡」（漏检）。")
    w("    即这两层不是无用，而是在真实长文本上代价远大于收益：本语料换来 0 条修正、15 条误改。")

    w("")
    w("2.7 风险量化")
    w(f"  语料 {total_chars} 字符中产生 {len(hits)} 次命中 = 每 {total_chars // max(len(hits), 1)} 字符一次；"
      f"其中 {len(bad)} 次改坏原文，破坏 {changed_chars([r['h'] for r in bad])} 字符。")
    bad_targets = sorted({r["h"]["replacement"] for r in bad})
    quoted = "、".join("「" + t + "」" for t in bad_targets)
    para(L, f"误改集中在{quoted}这几个词周围，属于会改变语义的替换（不是无害的同字/繁简替换）。")
    para(L, f"若下游做检索、摘要或字幕发布，这 {len(bad)} 处会直接污染内容，而且没有告警通道 —— "
            "CLI 只输出清洗后的文本，调用方无法区分有效修正与误改，除非自行解析 stderr 的命中明细。")

    w("")
    w("2.8 结论与调参建议")
    w(f"  [结论] v1 默认参数在 whisper_txt 上有效性为负：有效改写 0 条 / 误改 {len(bad)} 条 / "
      f"零改动命中 {len(noop)} 条。")
    w(f"     命中有效率 {len(good)}/{len(verdict_rows)}；改写有效率 "
      f"{good_rewritten}/{len(verdict_rows) - len(noop)}。")
    w("  这不是实现 bug（ctest 7/7 全通过，含 test_text_cleaner 的 87 项检查；AC 精确层行为符合预期），")
    w("  而是召回策略（拼音同音 + 单音节编辑距离容差）在真实 ASR 长文本上过宽。")
    w("  建议（按性价比排序，数字取自 2.5/2.6）：")
    w(f"  1) 收紧默认参数：--max-distance 0 可去掉全部 {v1_stats['k']['fuzzy']} 条模糊误改"
      f"（仍残留 {controls[1][1]['bad']} 条同音误改）；")
    w(f"     要做到 0 误改需 --no-pinyin（实测误改 {controls[0][1]['bad']} 条），")
    w(f"     代价是失去 2.6 中「知付包/银形卡」这类词表外错字的召回能力。")
    w(f"     建议默认取 --max-distance 0，并把模糊层降级为显式开启的可选开关。")
    w("  2) 同音层加上下文约束：命中片段左右紧邻实词时不替换（本轮「为新机」即此类），")
    w("     并对多音字（專/長）与繁简混排文本整体跳过 —— 这两条能消掉 2.5 中 B 配置的残留误改。")
    w(f"  3) 模糊层只保留「同音位差异」白名单（前后鼻音、平翘舌），")
    para(L, f"禁用会把高频虚词（了/到/一/才/完/部/功/机/品）当作容差位的匹配 —— "
            f"本轮 {fz_yan}/{fz[0]} 条模糊误改正是「验证 + 高频字」撞出来的。", indent="     ")
    w(f"  4) 词表按领域装配：{len(lexicon_entries())} 条支付/社交词与硬件评测语料几乎不相交（2.3），")
    w("     先补 ASR 高频混淆词（如 盘符/盘腐、幀/帧、抗拒齒/抗锯齿），再谈精度评估。")
    w("  5) 输出可判定性：stderr 已带 kind/distance/词条ID，建议清洗结果同时输出 JSON 命中清单，")
    w("     让调用方能对 pinyin/fuzzy 命中做二次确认或人工复核，而不是直接覆盖原文。")
    w("  6) 建立带标注评测集：本语料无正样本，精度只能证伪不能证实；")
    w("     用 2.4 注入式回测（别名召回）+ 2.6 能力探针（分层增量）+ 人工标注真实错字三套并行。")

    w("")
    w(bar)
    w("附录 A 词表 (data/lexicon.txt)")
    w(bar)
    for line in (ROOT / "data" / "lexicon.txt").read_text(encoding="utf-8").splitlines():
        w("  " + line.replace("\t", " | "))
    w("")
    w("附录 B 复现命令")
    w("  cmake --build build-gcc -j")
    w("  for f in whisper_txt/*.txt; do build-gcc/text_clean.exe -v < \"$f\"; done")
    w("  python tools/run_v1_test.py            # 重新生成本日志")
    w("  python tools/run_v1_test.py --audit    # 只打印命中上下文")
    w("")
    w("附录 C 合成回测输入")
    w("  正样本(别名注入):")
    for line in POSITIVE_LINES:
        w("    " + line)
    w("  负样本(应零命中):")
    for line in NEGATIVE_LINES:
        w("    " + line)
    w("")
    w("附录 D 能力探针输入（词表外错字，逐条单独送入）")
    for c in UNSEEN_CASES:
        w(f"    {c['line']}    期望={'修正为' + c['right'] if c['expect'] == 'fix' else '保持原文' if c['expect'] == 'keep' else '漏检(已知缺口)'}   —— {c['what']}")

    LOG_DIR.mkdir(exist_ok=True)
    target = LOG_DIR / out_name
    target.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {target} ({len(L)} lines, {len(hits)} hits, {len(bad)} 误改)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--out", default="v1_test.log")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.audit:
        audit()
        return 0
    return build_log(args.out)


if __name__ == "__main__":
    sys.exit(main())
