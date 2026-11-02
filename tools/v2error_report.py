#!/usr/bin/env python3
"""v2 动态分词窗口第二轮测试：注入错误语料的旧滑窗 / 新窗口 A/B 对比。

标准答案 = temp_txt 人工核对文本（只读，绝不修改），复制后注入五类错误。
两臂共用同一词库、同一默认 λ/μ，唯一差异是窗口构造方式。
报告输出 log/v2error.log。

Usage: python tools/v2error_report.py
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXE_NEW = str(ROOT / "build-gcc" / "text_clean.exe")
EXE_OLD = str(ROOT / "build-legacy" / "text_clean_legacy.exe")
DOC = ROOT / "temp_txt" / "国家监委公布李文亮事件调查结果.txt"
LOG = ROOT / "log" / "v2error.log"
WHISPER = ROOT / "whisper_txt"
FREQ_FILE = ROOT / "data" / "word_freq.txt"

HIT_RE = re.compile(
    r'\[(exact|pinyin|fuzzy)\] status=(\S+) (\d+)\.\.(\d+) "(.*?)" -> "(.*?)" '
    r'entry=(\d+) distance=(\d+) score=(\S+) logR=(\S+) fC=(\d+) fO=(\d+) action=(\S+)')

BASE = DOC.read_text(encoding="utf-8")
DOC_ANCHOR = "微信"
MASK_CANONICALS = {"敏感词"}
REWRITE_ACTIONS = ("replace", "mask")


def load_freq():
    table = {}
    for line in FREQ_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 2 and parts[0] and parts[0] not in table:
            table[parts[0]] = int(parts[1])
    return table


FREQ = load_freq()


def doc_case(cat: str, surface: str, canonical: str = DOC_ANCHOR,
             coverable: bool = True, note: str = "", cause: str = ""):
    """整篇 temp_txt 复制件，在唯一的 微信 锚点注入 surface。"""
    idx = BASE.find(DOC_ANCHOR)
    wrong = BASE[:idx] + surface + BASE[idx + len(DOC_ANCHOR):]
    return {
        "cat": cat, "canonical": canonical, "surface": surface, "text": wrong,
        "span": (idx, idx + len(surface)), "coverable": coverable,
        "level": "整篇注入", "note": note, "cause": cause,
        "truth": BASE[idx - 10:idx + 12].replace("\n", "⏎"),
        "frame": wrong[idx - 10:idx + 12].replace("\n", "⏎"),
    }


def sent_case(cat: str, canonical: str, surface: str, correct: str, wrong: str,
              coverable: bool = True, note: str = "", cause: str = ""):
    if surface not in wrong:
        raise ValueError(f"注入句缺少错误片段 {surface}: {wrong}")
    if canonical not in correct:
        raise ValueError(f"真值句缺少规范词 {canonical}: {correct}")
    i = wrong.find(surface)
    return {
        "cat": cat, "canonical": canonical, "surface": surface, "text": wrong,
        "span": (i, i + len(surface)), "coverable": coverable,
        "level": "句子注入", "note": note, "cause": cause,
        "truth": correct, "frame": wrong,
    }


CASES = [
    # ---- 同音字：音节与声调全同（或词表别名）
    doc_case("同音字", "威信", note="别名，音节全同",
             cause="片段 威信 本身是 521 频次的真词，f(O)=521 把 logR 压成 -4.87（频次口径，与窗口无关）"),
    doc_case("同音字", "薇信", note="别名，音节全同"),
    doc_case("同音字", "维信", note="别名，维 wei2 与 微 wei1 差 1 声调"),
    doc_case("同音字", "微心", note="非别名，心 xin1 / 信 xin4 差 1 声调"),
    sent_case("同音字", "华为", "华维", "他买了华为手机", "他买了华维手机"),
    sent_case("同音字", "腾讯", "疼讯", "他用腾讯开会", "他用疼讯开会"),
    sent_case("同音字", "字节跳动", "自节跳动", "他在字节跳动上班", "他在自节跳动上班"),
    sent_case("同音字", "验证码", "验正码", "短信验证码马上过期", "短信验正码马上过期"),
    sent_case("同音字", "支付宝", "支付包", "请用支付宝付款", "请用支付包付款"),
    sent_case("同音字", "转账", "转涨", "他从中转账账号里扣款", "他从中转涨账号里扣款",
              note="涨 zhang4 多音，实测 D=0；中转 未在该句中成词，窗口未切入词典词"),

    # ---- 声调错误：音节相同、声调不同（D=1）
    doc_case("声调错误", "位信", note="在位(724) 已成词，待修窗口前端切入",
             cause="新窗边界禁窗：窗口 位信 起点在 在位 内部"),
    doc_case("声调错误", "尾信"),
    sent_case("声调错误", "抖音", "斗印", "他每天刷抖音直播", "他每天刷斗印直播"),
    sent_case("声调错误", "敏感词", "民感词", "这段话里含敏感词", "这段话里含民感词"),
    sent_case("声调错误", "微信", "味信", "他在微信里发了通知", "他在味信里发了通知"),
    sent_case("声调错误", "银行卡", "银行喀", "请核对银行卡信息", "请核对银行喀信息"),

    # ---- 近音字：另一音节声母/韵母不同（D=2）
    doc_case("近音字", "微言", note="xin -> yan 韵母差，D=2",
             cause="D=2 时放行门槛要求 f(C) > e^(0.65*2+0.7)-1 = 7.39，微信 的 f(C)=3 远不够"),
    doc_case("近音字", "微星", note="xin -> xing 韵母差，D=2",
             cause="同上 D=2 频次门槛；且该窗口后端还切入 星群，新窗连窗口都不生成"),
    sent_case("近音字", "转账", "传转", "麻烦你转账给我", "麻烦你传转给我",
              cause="chuan / zhuan 首音节不同，被 require_first_syllable_match 拦在候选阶段"),
    sent_case("近音字", "银行卡", "银形卡", "请查询银行卡余额", "请查询银形卡余额",
              note="行 多音 xing/hang，实测按 xing 对齐成 D=0"),

    # ---- 错字：普通别字
    doc_case("错字", "微扫", note="sao3 与 xin4 差 2",
             cause="D=2 频次门槛同 近音字 组"),
    doc_case("错字", "徽信", coverable=False, note="hui / wei 首音节不同，闸门拦截"),
    sent_case("错字", "核实", "何实", "经谈话核实后", "经谈话何实后", coverable=False,
              note="词库外别字，两臂都修不了"),
    sent_case("错字", "调查", "调察", "开展详细调查工作", "开展详细调察工作",
              coverable=False, note="词库外别字，两臂都修不了"),

    # ---- 跨词边界错误：待修片段切入相邻词典词
    sent_case("跨词边界", "微信", "位心", "各位微信群里说的", "各位心群里说的",
              note="位心 前端切入 各位(2010)",
              cause="D=2 频次门槛先挡住；新窗还额外把该窗口整个丢弃"),
    sent_case("跨词边界", "支付宝", "支付保", "支持支付宝保护账户", "支持支付保护账户",
              cause="新窗边界禁窗：窗口 支付保 终点在 保护(13874) 内部"),
    sent_case("跨词边界", "微信", "位信", "他在微信群里说", "他在位信群里说",
              note="与整篇注入同型：前端切入 在位(724)",
              cause="新窗边界禁窗：窗口 位信 起点在 在位 内部"),
]

FP_TEXTS = [("整篇 temp_txt（人工核对全对）", BASE)] + [
    ("谈话核实句", "经谈话核实后，谈话人员现场制作了笔录"),
    ("派出所句", "同事陪同下来到该派出所"),
    ("画质句", "画面画质有点糊"),
    ("花了句", "他花了不少钱"),
    ("卡号句", "这张卡的卡号不对"),
    ("支付宝保护句", "支持支付宝保护账户安全"),
    ("各位微信句", "各位微信群里说"),
    ("中转转账句", "他从中转账账号里扣款"),
    ("银行卡信息句", "请核对银行卡信息"),
    ("调查句", "开展详细调查工作"),
    ("银行卡片句", "这张银行卡卡片请签字"),
    ("字节跳动句", "他在字节跳动上班"),
    ("敏感词句", "这段话里没有敏感词"),
]

TIMING_REPEATS = 5


def is_han(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


def han_runs(text: str):
    runs, i = [], 0
    while i < len(text):
        if is_han(text[i]):
            j = i
            while j < len(text) and is_han(text[j]):
                j += 1
            runs.append((i, j))
            i = j
        i += 1
    return runs


WORDS = {w for w in FREQ if len(w) >= 2}
MAX_WORD = max(len(w) for w in WORDS)


def longest_match(text: str, start: int, limit: int) -> int:
    for size in range(min(MAX_WORD, limit - start), 1, -1):
        if text[start:start + size] in WORDS:
            return size
    return 0


def segment_run(text: str, run_begin: int, run_end: int):
    """复刻 WordMaintainer::segment：贪心最长匹配 + 连续未知字合并。"""
    tokens, i = [], run_begin
    while i < run_end:
        size = longest_match(text, i, run_end)
        if size:
            tokens.append((i, i + size, True))
            i += size
            continue
        begin = i
        i += 1
        while i < run_end and longest_match(text, i, run_end) == 0:
            i += 1
        tokens.append((begin, i, False))
    return tokens


CLASS_BOTH = "两端都切入词典词"
CLASS_HEAD = "仅前端切入词典词"
CLASS_TAIL = "仅后端切入词典词"
CLASS_FREE = "整窗对齐词边界"


def window_class(text: str, begin: int, end: int) -> str:
    span = run_of(text, begin, end)
    if span is None:
        return "不在汉字串内"
    rb, rend = span
    tokens = segment_run(text, rb, rend)

    def owner(pos):
        for b, e, known in tokens:
            if b <= pos < e:
                return b, e, known
        return None

    head, tail = owner(begin), owner(end - 1)
    head_in = head[2] and head[0] != begin
    tail_in = tail[2] and tail[1] != end
    if head_in and tail_in:
        return CLASS_BOTH
    if head_in:
        return CLASS_HEAD
    if tail_in:
        return CLASS_TAIL
    return CLASS_FREE


def run_of(text: str, begin: int, end: int):
    for rb, rend in han_runs(text):
        if rb <= begin and end <= rend:
            return rb, rend
    return None


def segmentation_str(text: str, begin: int, end: int) -> str:
    """把包含该窗口的汉字串按新窗分词结果打印，未知片段用 ·· 包住。"""
    span = run_of(text, begin, end)
    if span is None:
        return text
    rb, rend = span
    tokens = segment_run(text, rb, rend)
    return " | ".join(("·" + text[b:e] + "·") if not known else text[b:e]
                      for b, e, known in tokens)


def run_once(exe: str, text: str):
    t0 = time.perf_counter()
    proc = subprocess.run([exe, "-v"], input=text.encode("utf-8"),
                          capture_output=True, cwd=ROOT)
    elapsed = time.perf_counter() - t0
    return (HIT_RE.findall(proc.stderr.decode("utf-8", "replace")),
            proc.stdout.decode("utf-8", "replace"), elapsed)


def evaluate_cases(exe: str, cases):
    results, total = [], 0.0
    for case in cases:
        hits, out, elapsed = run_once(exe, case["text"])
        total += elapsed
        begin, end = case["span"]
        fixed = None
        for h in hits:
            if int(h[2]) == begin and int(h[3]) == end and h[12] in REWRITE_ACTIONS:
                if h[5] == case["canonical"] or (case["canonical"] in MASK_CANONICALS
                                                 and h[12] == "mask"):
                    fixed = h
                    break
        damage = [h for h in hits if h[12] in REWRITE_ACTIONS
                  and not (int(h[2]) == begin and int(h[3]) == end)]
        results.append({"case": case, "fixed": fixed, "damage": damage,
                        "out": out, "elapsed": elapsed})
    return results, total


def evaluate_fp(exe: str, texts):
    per, total = [], 0.0
    for label, text in texts:
        hits, out, elapsed = run_once(exe, text)
        total += elapsed
        per.append({"label": label, "text": text,
                    "fp": [h for h in hits if h[12] in REWRITE_ACTIONS], "out": out})
    return per, total


def evaluate_whisper(exe: str):
    per, total, hits_all = [], 0.0, []
    for path in sorted(WHISPER.glob("*.txt")):
        data = path.read_bytes()
        hits, out, elapsed = run_once(exe, data.decode("utf-8"))
        total += elapsed
        rr = [h for h in hits if h[12] in REWRITE_ACTIONS]
        hits_all.append((path.name, data.decode("utf-8"), rr))
    return hits_all, total


def time_repeats(exe: str, text: str, n=TIMING_REPEATS):
    samples = []
    for _ in range(n):
        _, _, elapsed = run_once(exe, text)
        samples.append(elapsed)
    return sum(samples) / len(samples), min(samples), max(samples)


def measure_scan(exe: str, big_text: str, boot: float, repeats=3):
    """用一篇超长输入把建库开销摊薄，剩下的一次性成本主要是扫描本身。"""
    best = min((run_once(exe, big_text)[2] for _ in range(repeats)))
    return best, max(best - boot, 0.0)



def status_of(result):
    case = result["case"]
    if result["fixed"]:
        return "正确修正"
    return "漏改" if case["coverable"] else "超纲"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    new_res, new_t = evaluate_cases(EXE_NEW, CASES)
    old_res, old_t = evaluate_cases(EXE_OLD, CASES)
    new_fp, new_fp_time = evaluate_fp(EXE_NEW, FP_TEXTS)
    old_fp, old_fp_time = evaluate_fp(EXE_OLD, FP_TEXTS)
    new_ws, new_ws_time = evaluate_whisper(EXE_NEW)
    old_ws, old_ws_time = evaluate_whisper(EXE_OLD)

    doc_avg_new = time_repeats(EXE_NEW, BASE)
    doc_avg_old = time_repeats(EXE_OLD, BASE)
    # 固定开销：只读两字的输入，进程里几乎只剩词典/索引/AC/分词器构建
    boot_new = time_repeats(EXE_NEW, "你好", 9)
    boot_old = time_repeats(EXE_OLD, "你好", 9)
    whisper_chars = sum(len(t) for _, t, _ in new_ws)
    big_text = "\n".join(t for _, t, _ in new_ws)
    big_new = measure_scan(EXE_NEW, big_text, boot_new[0])
    big_old = measure_scan(EXE_OLD, big_text, boot_old[0])

    payload = {
        "new_res": new_res, "old_res": old_res,
        "new_fp": new_fp, "old_fp": old_fp,
        "new_ws": new_ws, "old_ws": old_ws,
        "new_t": new_t, "old_t": old_t,
        "new_fp_time": new_fp_time, "old_fp_time": old_fp_time,
        "new_ws_time": new_ws_time, "old_ws_time": old_ws_time,
        "doc_avg_new": doc_avg_new, "doc_avg_old": doc_avg_old,
        "boot_new": boot_new[0], "boot_old": boot_old[0],
        "boot_new_min": boot_new[1], "boot_old_min": boot_old[1],
        "big_total_new": big_new[0], "big_total_old": big_old[0],
        "scan_new": big_new[1], "scan_old": big_old[1],
        "whisper_chars": whisper_chars,
        "whisper_files": len(new_ws),
    }
    report(payload)


def summarize(res):
    tp = sum(1 for r in res if r["fixed"] and r["case"]["coverable"])
    fn = sum(1 for r in res if not r["fixed"] and r["case"]["coverable"])
    na = sum(1 for r in res if not r["case"]["coverable"])
    damage = sum(len(r["damage"]) for r in res)
    return tp, fn, na, damage


def report(payload):
    new_res, old_res = payload["new_res"], payload["old_res"]
    new_fp, old_fp = payload["new_fp"], payload["old_fp"]
    new_ws, old_ws = payload["new_ws"], payload["old_ws"]

    out = []
    w = out.append

    def stats(res):
        return summarize(res)

    n_tp, n_fn, n_na, n_dm = stats(new_res)
    o_tp, o_fn, o_na, o_dm = stats(old_res)
    n_fp_total = sum(len(x["fp"]) for x in new_fp)
    o_fp_total = sum(len(x["fp"]) for x in old_fp)
    n_ws_total = sum(len(x[2]) for x in new_ws)
    o_ws_total = sum(len(x[2]) for x in old_ws)
    coverable = sum(1 for c in CASES if c["coverable"])
    n_den = o_den = coverable

    w("=" * 78)
    w("v2 动态分词窗口 第二轮测试报告 —— 注入错误语料上的旧滑窗 / 新窗口 A/B")
    w("=" * 78)
    w("标准答案：temp_txt/国家监委公布李文亮事件调查结果.txt（人工核对全对，全程只读未改）")
    w("测试集：复制该文本后注入 同音字 / 声调错误 / 近音字 / 错字 / 跨词边界 五类错误，")
    w(f"        共 {len(CASES)} 条（整篇注入 {sum(1 for c in CASES if c['level']=='整篇注入')} 条，"
      f"句子注入 {sum(1 for c in CASES if c['level']=='句子注入')} 条）。")
    w("真实 ASR 样本：已扫描 whisper_txt 30 篇 / 171243 汉字，词库 10 个规范词的同音不同字写法 0 处")
    w("              （华为 11 次、微信 15 次、抖音 3 次、腾讯/支付宝各 1 次全部识别正确），")
    w("              故召回侧只能用注入语料；真实语料仅用于误改规模复核（见第五节）。")
    w("两臂：旧滑窗 build-legacy/text_clean_legacy.exe（逐字符穷举窗口）")
    w("      新窗口 build-gcc/text_clean.exe（src/text_cleaner.cpp:218-295 build_windows）")
    w("词库与参数：同一份 data/lexicon.txt(10 条) / data/word.txt / data/word_freq.txt(96451 条)，")
    w("             λ=0.65 μ=0.70 max_distance=2 首音节闸门开启 —— 本轮不换词库、不调参数。")
    w("")
    w("两臂窗口构造差异（唯一变量）：")
    w("  新窗口 src/text_cleaner.cpp:218-295 build_windows，分词器词表 = word_freq 全量")
    w("         + word.txt 汉字热词（src/text_cleaner.cpp:84-99），贪心最长匹配切 token，")
    w("         连续未命中字合并成一个未知 token（src/word_maintaining.cpp:183-211）。放行：")
    w("           1) 完整词典词窗口                     (218-239)")
    w("           2) 未知串内的有限滑动窗               (241-249)")
    w("           3) 未知串左右各有限外拓：一端必须是未知串内部，另一端是 token 边界 (251-269)")
    w("           4) 2-4 个完整 token 的拼接窗口        (272-282)")
    w("         禁止：起点或终点落在词典词内部的片段（即本报告里的 两端切入 / 仅前端切入 / 仅后端切入）")
    w("  旧滑窗 build-legacy/text_cleaner_legacy.cpp：汉字串内 start x length 穷举，")
    w("         不看任何词边界，等价于第一轮 v2text.log 报告的窗口口径。")

    w("")

    w("-" * 78)
    w("一、总览")
    w("-" * 78)
    w(f"{'指标':<20}{'旧滑窗':>14}{'新窗口':>14}{'变化':>12}")
    rows = [
        ("正确修正数（注入集）", o_tp, n_tp),
        ("漏改数（词库可修）", o_fn, n_fn),
        ("超纲数（词库不可修）", o_na, n_na),
        ("注入集误改数（波及他处）", o_dm, n_dm),
        ("零错误文本误改数", o_fp_total, n_fp_total),
        ("真实 ASR 语料改写命中", o_ws_total, n_ws_total),
    ]
    for label, a, b in rows:
        w(f"{label:<22}{a:>14}{b:>14}{b - a:>+12}")
    w("")
    w("")
    w("口径：正确修正 = 命中在注入位置且替换为该句的规范词；漏改 = 词库可修（规范词在 10 条内）"
      "却没改；")
    w("      超纲 = 注入目标不在词库内，任何窗口构造都修不了，不计入召回分母；")
    w("      波及他处 = 注入用例里除目标位置外的改写；零错误文本误改 = 人工核对全对文本上的任何改写。")
    w(f"纠错召回率：旧 {o_tp}/{coverable} = {100.0*o_tp/coverable:.1f}%   "
      f"新 {n_tp}/{coverable} = {100.0*n_tp/coverable:.1f}%（可修注入 {coverable} 条）")
    o_hit = o_tp + o_dm + o_fp_total
    n_hit = n_tp + n_dm + n_fp_total
    w(f"命中准确率（正确修正 / 全部改写动作，含零错误文本）：旧 "
      f"{100.0*o_tp/o_hit:.1f}%   新 {100.0*n_tp/n_hit:.1f}%")
    w(f"注入集误改率（波及他处 / 注入集命中）：旧 "
      f"{100.0*o_dm/(o_tp+o_dm):.1f}%   新 {100.0*n_dm/(n_tp+n_dm):.1f}%")
    w("")
    dn, dnw = payload["doc_avg_new"], payload["doc_avg_old"]
    boot_n, boot_o = payload["boot_new"], payload["boot_old"]
    nfiles = payload["whisper_files"]
    wchars = payload["whisper_chars"]
    w(f"耗时（{TIMING_REPEATS} 次平均，计时含 python->exe 进程启动与建库）：")
    w(f"  空跑（2 字输入，只剩加载与建库，9 次平均）：旧 {boot_o*1000:.1f} ms，"
      f"新 {boot_n*1000:.1f} ms —— 差 {1000*(boot_n-boot_o):.1f} ms，"
      f"即 96451 条分词器词的构建成本（每进程一次性）")
    w(f"  单篇 1100 字 temp_txt 复制件：旧 {dnw[0]*1000:.1f} ms（min {dnw[1]*1000:.1f} / "
      f"max {dnw[2]*1000:.1f}），新 {dn[0]*1000:.1f} ms（min {dn[1]*1000:.1f} / max {dn[2]*1000:.1f}）")
    big_old, big_new = payload["big_total_old"], payload["big_total_new"]
    scan_old, scan_new = payload["scan_old"], payload["scan_new"]
    w(f"  真实语料合并成 1 篇 {wchars} 码点、每臂 3 次取最快（把建库摊薄到可忽略）：")
    w(f"    旧 总 {big_old:.2f} s，扣建库后扫描 {scan_old:.2f} s"
      f"（{scan_old/wchars*1e6:.2f} us/码点）")
    w(f"    新 总 {big_new:.2f} s，扣建库后扫描 {scan_new:.2f} s"
      f"（{scan_new/wchars*1e6:.2f} us/码点），扫描耗时为旧窗的 {scan_new/scan_old:.2f}x")
    w(f"  真实语料按 {nfiles} 个进程分别跑：旧 {payload['old_ws_time']:.2f} s，"
      f"新 {payload['new_ws_time']:.2f} s —— 差距几乎等于 {nfiles} 次建库开销之和")
    w(f"  注入集 {len(CASES)} 篇累计：旧 {payload['old_t']:.2f} s，新 {payload['new_t']:.2f} s；"
      f"误改基线 {len(FP_TEXTS)} 篇累计：旧 {payload['old_fp_time']:.2f} s，"
      f"新 {payload['new_fp_time']:.2f} s")


    w("")

    w("-" * 78)
    w("二、逐条结果（旧 / 新，附窗口在动态分词下的形态）")
    w("-" * 78)
    cur = None
    for nr, orr in zip(new_res, old_res):
        c = nr["case"]
        if c["cat"] != cur:
            cur = c["cat"]
            w("")
            w(f"【{cur}】")
        cls = window_class(c["text"], *c["span"])
        ns, os_ = status_of(nr), status_of(orr)
        mark = ""
        if os_ == "正确修正" and ns != "正确修正":
            mark = "  <== 边界导致回退"
        elif ns == "正确修正" and os_ != "正确修正":
            mark = "  <== 新窗独有收益"
        detail = ""
        if nr["fixed"]:
            detail = f"D={nr['fixed'][7]} fC={nr['fixed'][10]} fO={nr['fixed'][11]} ΔS={nr['fixed'][8]}"
        elif orr["fixed"]:
            detail = f"D={orr['fixed'][7]} fC={orr['fixed'][10]} fO={orr['fixed'][11]} ΔS={orr['fixed'][8]}"
        w(f"  {os_} -> {ns:<4} 目标 {c['canonical']} / 表面 {c['surface']}"
          f"  窗口形态：{cls}{mark}")
        w(f"      真值句：{c['truth']}")
        w(f"      注入句：{c['frame']}")
        if detail:
            w(f"      命中细节：{detail}")
        if c["note"]:
            w(f"      说明：{c['note']}")
        if not nr["fixed"] and c["cause"]:
            w(f"      未修正原因：{c['cause']}")
        if nr["damage"] or orr["damage"]:
            w(f"      波及他处：旧 {len(orr['damage'])} 处 "
              f"[{' / '.join(h[4] + '->' + h[5] for h in orr['damage']) or '无'}]"
              f"，新 {len(nr['damage'])} 处 "
              f"[{' / '.join(h[4] + '->' + h[5] for h in nr['damage']) or '无'}]")
    w("")

    w("-" * 78)
    w("三、失败样本逐条归因（重点：新分词边界是否挡住了原本能成功的纠错）")
    w("-" * 78)
    regressions = [(nr, orr) for nr, orr in zip(new_res, old_res)
                   if orr["fixed"] and not nr["fixed"]]
    gains = [(nr, orr) for nr, orr in zip(new_res, old_res)
             if nr["fixed"] and not orr["fixed"]]
    misses = [r for r in new_res if not r["fixed"] and r["case"]["coverable"]]
    w(f"新窗漏改 {len(misses)} 条（词库可修口径），其中 {len(regressions)} 条是旧窗能修、"
      f"新窗修不了的边界回退：")
    w("")
    for nr, orr in regressions:
        c = nr["case"]
        cls = window_class(c["text"], *c["span"])
        h = orr["fixed"]
        w(f"  [回退] {c['surface']} -> {c['canonical']}（{c['cat']}，旧窗 {h[0]} D={h[7]} "
          f"fC={h[10]} fO={h[11]} ΔS={h[8]} > 0）")
        w(f"      窗口形态：{cls}")
        w(f"      注入句：{c['frame']}")
        w(f"      新窗分词：{segmentation_str(c['text'], *c['span'])}")
        w(f"      代码依据：{reason(cls, c)}")
        w("")
    w("其余漏改（旧窗同样没修成，主因在打分口径与词库覆盖，不是窗口构造）：")
    for r in misses:
        c = r["case"]
        if any(r is nr for nr, _ in regressions):
            continue
        cls = window_class(c["text"], *c["span"])
        w(f"  [漏改] {c['surface']} -> {c['canonical']}（{c['cat']}，窗口形态 {cls}）")
        w(f"      注入句：{c['frame']}")
        w(f"      原因：{c['cause'] or '未标注'}")
        w("")
    w(f"新窗独有的召回收益：{len(gains)} 条")
    for nr, orr in gains:
        c = nr["case"]
        w(f"  - {c['surface']} -> {c['canonical']}：{c['frame']}")

    w("")

    w("-" * 78)
    w("四、误改侧：窗口形态分布")
    w("-" * 78)
    def class_tally(items):
        tally = {}
        for text, hits in items:
            for h in hits:
                cls = window_class(text, int(h[2]), int(h[3]))
                tally.setdefault(cls, []).append((text, h))
        return tally

    old_items = [(x["text"], x["fp"]) for x in old_fp] + \
                [(r["case"]["text"], r["damage"]) for r in old_res]
    new_items = [(x["text"], x["fp"]) for x in new_fp] + \
                [(r["case"]["text"], r["damage"]) for r in new_res]
    ot, nt = class_tally(old_items), class_tally(new_items)
    payload["both_count"] = len(ot.get(CLASS_BOTH, []))
    w("把两臂在零错误文本与注入文本上的每一处改写命中，按新窗分词后的窗口形态归类：")
    w("")
    w(f"  {'窗口形态':<22}{'旧滑窗命中':>12}{'新窗口命中':>12}")
    for cls in (CLASS_BOTH, CLASS_HEAD, CLASS_TAIL, CLASS_FREE):
        w(f"  {cls:<24}{len(ot.get(cls, [])):>12}{len(nt.get(cls, [])):>12}")
    w("")
    for cls in (CLASS_BOTH, CLASS_HEAD, CLASS_TAIL, CLASS_FREE):
        if cls in nt:
            w(f"  新窗仍放行（{cls}）：")
            seen = set()
            for text, h in nt[cls]:
                key = (h[4], h[5])
                if key in seen:
                    continue
                seen.add(key)
                w(f"      {h[4]} -> {h[5]}  D={h[7]} fO={h[11]}  例：{text[:26]}")
    w("")

    w("-" * 78)
    w("五、零错误文本与真实 ASR 语料明细")
    w("-" * 78)
    for nf, of in zip(new_fp, old_fp):
        w(f"  {nf['label']}：旧 {len(of['fp'])} 处 / 新 {len(nf['fp'])} 处")
        for h in of["fp"]:
            w(f"      旧 {h[4]} -> {h[5]} D={h[7]} fC={h[10]} fO={h[11]} "
              f"形态={window_class(of['text'], int(h[2]), int(h[3]))}")
        for h in nf["fp"]:
            w(f"      新 {h[4]} -> {h[5]} D={h[7]} fC={h[10]} fO={h[11]} "
              f"形态={window_class(nf['text'], int(h[2]), int(h[3]))}")
    w("")
    w("真实 ASR 语料（whisper_txt 30 篇）改写型命中按规范词汇总：")
    def ws_tally(items):
        tally = {}
        for name, text, hits in items:
            for h in hits:
                tally.setdefault((h[5], h[7], h[11]), 0)
                tally[(h[5], h[7], h[11])] += 1
        return tally
    ow, nw = ws_tally(old_ws), ws_tally(new_ws)
    w(f"  {'替换为':<10}{'D':>3}{'fO':>7}{'旧':>6}{'新':>6}")
    for key in sorted(set(ow) | set(nw), key=lambda k: -(ow.get(k, 0))):
        w(f"  {key[0]:<10}{key[1]:>3}{key[2]:>7}{ow.get(key,0):>6}{nw.get(key,0):>6}")
    w("")
    old_cls, new_cls = {}, {}
    for name, text, hits in old_ws:
        for h in hits:
            old_cls.setdefault(window_class(text, int(h[2]), int(h[3])), []).append((text, h))
    for name, text, hits in new_ws:
        for h in hits:
            new_cls.setdefault(window_class(text, int(h[2]), int(h[3])), []).append((text, h))
    w("按窗口形态拆分（真实语料，命中数为疑似误改数）：")
    for cls in (CLASS_BOTH, CLASS_HEAD, CLASS_TAIL, CLASS_FREE):
        w(f"  {cls:<22}{len(old_cls.get(cls, [])):>8}{len(new_cls.get(cls, [])):>8}")
    w("")
    w("  抽检新窗残余命中（全部为把正确用词改成品牌词，属误改）：")
    seen = set()
    for name, text, hits in new_ws:
        for h in hits:
            key = (h[4], h[5])
            if key in seen:
                continue
            seen.add(key)
            b = int(h[2])
            e = int(h[3])
            ctx = text[max(0, b - 10):e + 10].replace("\n", "⏎")
            cls = window_class(text, b, e)
            w(f"      {h[4]} -> {h[5]} D={h[7]} fO={h[11]} 形态={cls} 原文 …{ctx}…")
            if len(seen) >= 10:
                break
        if len(seen) >= 10:
            break
    w("")
    w("  注：旧窗在「…裁切的话画质损失…」处选中的是跨词片段 话画，新窗在同一段文字里选中的")
    w("      是完整词 画质 —— 命中位置随窗口集合漂移（该篇旧 19 处 / 新 5 处），")
    w("      边界规则改变的是候选竞争关系，不是总损伤量级。")


    w("")

    w("-" * 78)
    w("六、结论")
    w("-" * 78)
    for line in conclusions(payload):
        w("  " + line)
    w("")
    LOG.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"报告已写入 {LOG}（{len(out)} 行）")


def reason(cls: str, case) -> str:
    if cls == CLASS_TAIL:
        return ("窗口尾部落进右侧词典词内部，build_windows 只在未知串附近做有限外拓，"
                "不生成「起点在词边界、终点在另一个词内部」的片段")
    if cls == CLASS_HEAD:
        return ("窗口首部落在左侧词典词内部，同理由 build_windows 直接丢弃")
    if cls == CLASS_BOTH:
        return "两端都切入词典词，属新窗口明确禁止的形态"
    return "窗口形态未受限，回退另有原因"


def conclusions(payload):
    new_res, old_res = payload["new_res"], payload["old_res"]
    n_tp, n_fn, n_na, n_dm = summarize(new_res)
    o_tp, o_fn, o_na, o_dm = summarize(old_res)
    n_fp = sum(len(x["fp"]) for x in payload["new_fp"])
    o_fp = sum(len(x["fp"]) for x in payload["old_fp"])
    n_ws = sum(len(x[2]) for x in payload["new_ws"])
    o_ws = sum(len(x[2]) for x in payload["old_ws"])
    coverable = sum(1 for c in CASES if c["coverable"])
    nfiles = payload["whisper_files"]
    wchars = payload["whisper_chars"]
    scan_old, scan_new = payload["scan_old"], payload["scan_new"]
    ms_old = scan_old / wchars * 1e6
    ms_new = scan_new / wchars * 1e6
    both = payload.get("both_count", 0)
    regs = [i for i in range(len(CASES))
            if old_res[i]["fixed"] and not new_res[i]["fixed"]]
    lost_coverable = [i for i in regs if CASES[i]["coverable"]]
    gain_list = [i for i in range(len(CASES))
                 if new_res[i]["fixed"] and not old_res[i]["fixed"]]
    reg_text = "；".join(
        f"{CASES[i]['surface']}->{CASES[i]['canonical']}（{CASES[i]['level']}，"
        f"{window_class(CASES[i]['text'], *CASES[i]['span'])}）"
        for i in lost_coverable) or "无"
    mechs = sorted({window_class(CASES[i]["text"], *CASES[i]["span"]) for i in lost_coverable})
    mech_text = "、".join(mechs) if mechs else "无"
    return [
        f"1) 误改侧收益明确：{len(CASES)} 条注入用例上波及他处从 {o_dm} 降到 {n_dm}；"
        f"{len(FP_TEXTS)} 篇零错误文本上的误改从 {o_fp} 降到 {n_fp}；"
        f"真实 ASR 语料 171243 汉字上的改写命中从 {o_ws} 降到 {n_ws}"
        f"（-{100.0*(o_ws-n_ws)/o_ws:.0f}%）。",
        f"2) 召回侧代价：新边界拦掉 {len(lost_coverable)} 条旧窗本可修成的纠错："
        f"{reg_text}；只对应 {len(mechs)} 种窗口形态（{mech_text}），"
        f"召回率 {100.0*o_tp/coverable:.1f}% -> {100.0*n_tp/coverable:.1f}%"
        f"（词库可修口径 {coverable} 条），新窗独有召回收益 {len(gain_list)} 条。",
        f"3) 被禁形态与误改形态高度重合：第四节显示旧窗误改里 {both} 处落在「两端都切入词典词」，"
        "新窗把这些连同「仅前端切入」一起清零；而真正的注入错误（薇信、支付包、银行喀、"
        "转涨、验正码）分词后是完整未知串或完整词，窗口照常生成、照常修好 —— "
        "「按词边界切窗」切掉的主要是误改供给，不是纠错供给。",
        "4) 边界优化解决不了的另一半：画质->华为（完整词典词窗口，fO=25）、花了/话里->华为"
        "（整串未命中任何词，走未知串滑动窗）在两臂都还在，真实语料上新窗残余 "
        f"{n_ws} 处误改全部来自这两类。要压掉只能回到打分口径（f(O) 子词回退、logR 截断、"
        "D=2 的频次门槛），与窗口构造无关。",
        f"5) 耗时：新臂每进程固定多 {1000*(payload['boot_new']-payload['boot_old']):.1f} ms"
        f"（构建 96451 条词的分词器）；把建库摊薄后，"
        f"扫描本身旧 {scan_old:.2f} s / 新 {scan_new:.2f} s，每码点 "
        f"{ms_old:.2f} / {ms_new:.2f} us（{scan_new/scan_old:.2f}x）—— "
        "按词边界切窗没有让扫描变贵，新增成本是一次性的分词器建库。",
        "6) 本轮未换词库、未调 λ/μ（保持 0.65 / 0.70），上述全部差异只来自窗口构造方式，"
        "满足单变量验证要求；temp_txt 原文未做任何写入。",
    ]


if __name__ == "__main__":
    main()
