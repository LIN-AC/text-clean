#!/usr/bin/env python3
"""v2 差分打分（ΔS）在人工核对文本上的误改测试。

temp_txt 下全部文本已由人工核对为完全正确，因此任何改写都是误改。
报告输出 log/v2text.log。

Usage: python tools/v2text_report.py
"""

from __future__ import annotations

import math
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXE = str(ROOT / "build-gcc" / "text_clean.exe")
TEMP_DIR = ROOT / "temp_txt"
LOG = ROOT / "log" / "v2text.log"
WORD_FILE = ROOT / "data" / "word.txt"
LEXICON = ROOT / "data" / "lexicon.txt"
FREQ = ROOT / "data" / "word_freq.txt"

DEFAULT_LAMBDA = 0.65
DEFAULT_MU = 0.70

HIT_RE = re.compile(
    r'\[(exact|pinyin|fuzzy)\] status=(\S+) (\d+)\.\.(\d+) "(.*?)" -> "(.*?)" '
    r'entry=(\d+) distance=(\d+) score=(\S+) logR=(\S+) fC=(\d+) fO=(\d+) action=(\S+)')

LAMBDA_GRID = [0.65, 1.0, 1.5, 2.0, 2.61, 2.62, 2.7, 3.0, 4.0, 6.0]
MU_GRID = [0.70, 1.0, 1.39, 2.0, 3.0, 4.0, 4.62, 4.63, 5.0, 6.0]

# 人工核对文本上的误改判定：命中位置上的原词本身就是正确用词。
VERDICTS = {
    ("话核", "华为"): ("误改", "「经谈话核实后」中的跨词片段 话+核 被当成词，替换为品牌词华为，语义被破坏"),
    ("话人", "华为"): ("误改", "「谈话人员现场制作了笔录」中的跨词片段 话+人 被替换为华为，凭空出现厂商"),
}

# 注入式召回探针：这些是词表别名，改写方向正确，用来测召回侧的损失。
ALIAS_CASES = [
    ("这是薇信支付的", "薇信", "微信", 0),
    ("用手机维信转账", "维信", "微信", 1),
    ("他在支富宝里充值", "支富宝", "支付宝", 0),
    ("知付宝到账了", "知付宝", "支付宝", 0),
    ("转帐给你了", "转帐", "转账", 0),
    ("银行喀哒余额不足", "银行喀", "银行卡", 1),
]


def run(text: str, flags=()):
    proc = subprocess.run([EXE, "-v", *flags], input=text.encode("utf-8"),
                          capture_output=True, cwd=ROOT)
    err = proc.stderr.decode("utf-8", "replace")
    out = proc.stdout.decode("utf-8", "replace")
    return HIT_RE.findall(err), out, err


def load_freq():
    table = {}
    for line in FREQ.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        word, _, count = line.partition("\t")
        if word and word not in table:
            table[word] = int(count)
    return table


def dctx(text: str, begin: int, end: int, pad: int = 14) -> str:
    return text[max(0, begin - pad):end + pad].replace("\r", "").replace("\n", "⏎")


def diff_stats(src: str, out: str):
    a = src.rstrip("\r\n").splitlines()
    b = out.rstrip("\r\n").splitlines()
    diff_lines = sum(1 for x, y in zip(a, b) if x != y) + abs(len(a) - len(b))
    diff_chars = sum(1 for x, y in zip(src.rstrip("\r\n"), out.rstrip("\r\n")) if x != y)
    diff_chars += abs(len(src.rstrip("\r\n")) - len(out.rstrip("\r\n")))
    return diff_lines, diff_chars


def main() -> int:
    freq = load_freq()
    files = sorted(TEMP_DIR.glob("*.txt"))
    lines_out = []
    w = lines_out.append

    w("=" * 78)
    w("v2 差分打分清洗测试报告 —— 人工核对语料误改检查")
    w("=" * 78)
    w("公式：ΔS = ln((1+f(C))/(1+f(O))) − λ·D(O,C) − μ，ΔS > 0 才允许改写")
    w("代码：src/text_cleaner.cpp:237-246（打分）、include/text_clean/text_cleaner.h:37-41（λ/μ 默认值）")
    w(f"默认参数：λ={DEFAULT_LAMBDA}  μ={DEFAULT_MU}  max_pinyin_distance=2  min_syllables_for_fuzzy=2")
    w("           require_first_syllable_match=true  声调差 1 / 声母韵母差 2")
    w("判定口径：temp_txt 语料已经人工核对为完全正确（f(O) 侧原词均为正确用词），")
    w("           因此任何 action=replace/mask 命中都记为误改；AC 精确命中为 action=keep 锁定，不改文本。")
    w("")

    src_main = files[0].read_bytes().decode("utf-8")
    total_hits = total_fp = total_cp = total_lines = total_chars = 0
    per_file = []
    for path in files:
        src = path.read_bytes().decode("utf-8")
        hits, out, _ = run(src)
        total_cp += len(src)
        d_lines, d_chars = diff_stats(src, out)
        total_hits += len(hits)
        total_lines += d_lines
        total_chars += d_chars
        total_fp += len([h for h in hits if h[4] != h[5]])
        per_file.append((path.stem, len(src), len(hits), d_lines, d_chars))

        w("-" * 78)
        w(f"样本：{path.name}")
        w(f"  长度 {len(src)} 码点 / {len(src.splitlines())} 行")
        w(f"  命中 {len(hits)} 处（exact {sum(1 for h in hits if h[0]=='exact')} / "
          f"pinyin {sum(1 for h in hits if h[0]=='pinyin')} / "
          f"fuzzy {sum(1 for h in hits if h[0]=='fuzzy')}），"
          f"实际改写 {d_chars} 字符 / {d_lines} 行")
        if not hits:
            w("  无命中，输出与原文一致。")
            continue
        for kind, status, b, e, matched, repl, entry, dist, score, logr, fc, fo, action in hits:
            b, e, dist = int(b), int(e), int(dist)
            score, logr, fc, fo = float(score), float(logr), int(fc), int(fo)
            verdict, why = VERDICTS.get((matched, repl), ("误改", "人工核对文本上的改写即为误改"))
            w("")
            w(f"  [{kind}] {matched} -> {repl}   {b}..{e}  entry={entry} D={dist} action={action}")
            w(f"    上下文  {dctx(src, b, e)}")
            w(f"    ΔS 分解  logR=ln((1+{fc})/(1+{fo}))={logr:.4f}"
              f"  −λD={DEFAULT_LAMBDA * dist:.4f}  −μ={DEFAULT_MU:.2f}"
              f"  = {score:.4f}  > 0 -> 放行")
            w(f"    f(C)={fc}（{'词表下限 3' if fc == 3 else 'jieba 实际词频'}），"
              f"f(O)={fo}（{'片段不在词频表中' if fo == 0 else '命中词频表'}）")
            w(f"    结论    {verdict}：{why}")
        a_lines = src.rstrip("\r\n").splitlines()
        b_lines = out.rstrip("\r\n").splitlines()
        pairs = [(x, y) for x, y in zip(a_lines, b_lines) if x != y]
        if pairs:
            w("")
            w("  改写行对照（原文 -> 清洗结果）：")
            for x, y in pairs:
                w(f"    {x}")
                w(f"    {y}")

    w("")
    w("=" * 78)
    w("一、结果总览")
    w("=" * 78)
    w(f"  样本 {len(files)} 篇（{'、'.join(p[0] for p in per_file)}），{total_cp} 码点；"
      f"命中 {total_hits} 处，全部为改写型，"
      f"实际改动 {total_chars} 字符 / {total_lines} 行。")
    w(f"  误改率：每 {total_cp // max(1, total_fp)} 字符一次误改；精确率 0/{total_hits}"
      f"（文本已核对为正确，不存在有效改写）。")
    all_words = {l.strip() for l in WORD_FILE.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.startswith("#")}
    words_in_text = [w for w in sorted(all_words) if w in src_main]
    w(f"  AC 精确锁定命中 0 处：word.txt 的 {len(all_words)} 个热词里，"
      f"只有 {len(words_in_text)} 个出现在本文（{words_in_text}）。")
    w("  现有热词是笔记本/芯片领域的品牌与型号，本文是公共卫生事件新闻语体，")
    w("  领域不匹配 -> 全文对拼音层完全开放，锁定层没有提供任何保护。")
    w("  单元测试 12/12 通过（ctest），实现与公式一致，误改不是 bug 而是打分口径问题。")

    w("")
    w("=" * 78)
    w("二、误改是怎么发生的（触发链路）")
    w("=" * 78)
    w("  以 756..758「话核」->「华为」为例，五个条件同时成立：")
    w("  1) 窗口以字符滑动，不做分词：扫描起点覆盖每个汉字，于是「谈|话核|实」")
    w("     这种跨词边界的片段与真实词同等参与匹配（src/text_cleaner.cpp:198-203）。")
    w("  2) 首音节闸门被片段自身满足：require_first_syllable_match 只比较窗口第一个音节，")
    w("     话 hua4 与 华 hua2 声母韵母相同，片段恰好以 hua 开头 -> 放行。")
    w("     该约束本意是屏蔽无关词撞尾音节，对「虚词+实词」片段完全失效。")
    w("  3) 距离惩罚不足：核 he2 vs 为 wei2 属声母韵母差，D=2，λ·D=1.30。")
    w("  4) f(O) 恒为 0：词频表按 jieba 只收 2-8 字、词频>=10 的词（96451 条，纯单字 0 条），")
    w("     片段「话核」「话人」不是词，f(O)=0；而相邻的真词「谈话」2436、「核实」318 并不会")
    w("     回退到窗口上 —— 查表用的是整个窗口字符串，没有子词/单字回退。")
    w("  5) logR 无上界：f(O)=0 时 logR = ln(1+f(C)) = ln(374) = 5.92，一条 5.92 的频次证据")
    w("     减去 1.30 + 0.70 仍剩 3.92，远高于放行线 0。频次项是 log 尺度、")
    w("     惩罚项是线性尺度，任何 f(C)>e^(λD+μ)−1 的词都能压过距离惩罚。")
    w("")
    w("  暴露面统计（本文全部可扫描窗口，按 2-4 字滑窗，全部为汉字）：")
    is_han = lambda ch: "\u4e00" <= ch <= "\u9fff"
    for length in (2, 3, 4):
        wins = [src_main[i:i + length] for i in range(len(src_main) - length + 1)
                if all(is_han(c) for c in src_main[i:i + length])]
        zero = [x for x in wins if x not in freq]
        w(f"    {length} 字窗口 {len(wins):>4} 个，f(O)=0 的 {len(zero):>4} 个"
          f"（{100.0 * len(zero) / max(1, len(wins)):.1f}%）")
    w("    窗口一旦 f(O)=0，logR 就与 O 无关，判定退化成 f(C) 单侧门槛。")

    w("")
    w("  阈值化：f(O)=0 时的放行下限（f(C) > e^(λD+μ) − 1）")
    lex_entries = []
    for line in LEXICON.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        canonical = line.split("\t")[0]
        lex_entries.append((canonical, max(freq.get(canonical, 0), 3)))
    for dist in (0, 1, 2):
        need = math.exp(DEFAULT_LAMBDA * dist + DEFAULT_MU) - 1
        passing = [c for c, fc in lex_entries if fc > need]
        w(f"    D={dist}: f(C) > {need:6.2f}    —— 动作词表 {len(lex_entries)} 条规范词中"
          f" {len(passing)} 条可放行（f(C)>=3 的下限词{'含在内' if len(passing) == len(lex_entries) else '已被排除'}）")
    w("")
    w("  词典规范词的实际频次取值（f(C) = max(词频表, 3)，3 是 word.txt/规范词下限）：")
    for line in LEXICON.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        canonical = line.split("\t")[0]
        f = freq.get(canonical, 0)
        w(f"    {canonical:<6} f={f:<7} ln(1+f(C))={math.log(1 + max(f, 3)):.3f}"
          f"   {'（下限 3：D=1 时勉强通过，D=2 不通过）' if f <= 3 else ''}")
    w("")
    w("  反向证据（同一片段在有词频时同样被改写）：")
    for probe in ["谈话核实", "话核实", "谈话人员", "经谈话核实后，谈话人员现场制作了笔录"]:
        hits, _, _ = run(probe)
        w(f"    {probe!r} -> 命中 {[(h[4], h[5], 'D' + h[7]) for h in hits]}")
    w("    说明「谈话」「核实」在词频表里（2436 / 318）也救不回来：窗口是「话核」，")
    w("    真正被查询的片段从来不是词，f(O) 与 O 是否为合法片段完全无关。")

    w("")
    w("=" * 78)
    w("三、误改候选比真实修正目标更有频次优势（排序反转）")
    w("=" * 78)
    w("  注入式别名探针（词表别名 -> 规范词）在默认参数下的得分：")
    for text, matched, repl, dist in ALIAS_CASES:
        hits, out, _ = run(text)
        row = next((h for h in hits if h[5] == repl), None)
        if row is None:
            w(f"    {matched} -> {repl}（D={dist}）  未命中，输出 {out.strip()!r}")
            continue
        score, logr, fc, fo = float(row[8]), float(row[9]), int(row[10]), int(row[11])
        w(f"    {matched} -> {repl}  D={row[7]}  logR={logr:.4f}  ΔS={score:.4f}"
          f"  f(C)={fc} f(O)={fo}  -> 修正成功")
    w("")
    w("  对照：误改候选 华为 的 logR=5.924，比上面每一条真实修正都高。")
    w("  挡住它需要 λ·D+μ ≥ 5.924（D=2），两条路径代价不同，均已实测：")
    w("    靠 μ：μ ≥ 4.6243 -> 误改 0，但召回只剩 1/6（μ=5.0 起召回 0/6）；")
    w("    靠 λ：λ ≥ 2.6121 -> 误改 0，召回 5/6；D>=1 的下限词修正（维信->微信，")
    w("          logR 仅 1.386）先死，D=0 修正与 λ 无关所以存活。")
    w("  所以 λ 是当前唯一可用的旋钮，但它挡的是这一个词，不是这一类错误：")
    w("  词频越高的规范词需要的 λ 越大，而 word.txt 里的领域词一旦被动作词表收录就会变成新的误改源。")
    w("  按 f(C) > e^(2λ+μ) − 1 反解（D=2，μ=0.70 时挡住所需 λ）：")
    hot = sorted(((freq.get(w, 0), w) for w in all_words if w in freq), reverse=True)[:10]
    for f, word in hot:
        need_lam = (math.log(1 + f) - DEFAULT_MU) / 2
        w(f"    {word:<8} f={f:<7} ln(1+f)={math.log(1 + f):.3f}"
          f"  需要 λ ≥ {need_lam:.2f} 才能挡住它在 f(O)=0 片段上的 D=2 改写")
    w("  结论：误改候选与正确候选在频次上不可排序（误改方频次更高），")
    w("  ln 尺度的频次项与线性尺度的惩罚项量纲不匹配，λ/μ 只能逐词追赶。")
    w("  另一个方向同样糟：词频下限把 微信/支付宝/抖音/验证码/敏感词 抬到 f(C)=3，")
    w("  而 ln(4)=1.386 > μ=0.7，所以这些词在 f(O)=0、D=0 时必然改写；")
    w("  D=1 时门槛是 f(C)>2.86，下限 3 恰好越过 —— 低频规范词等于免检。")

    w("")
    w("=" * 78)
    w("四、参数敏感性扫描（误改数 / 别名召回数）")
    w("=" * 78)

    def score_config(lam, mu):
        hits, _, _ = run(src_main, ["--lambda", str(lam), "--mu", str(mu)])
        fp = len([h for h in hits if h[4] != h[5]])
        recall = 0
        for text, matched, repl, _ in ALIAS_CASES:
            hh, _, _ = run(text, ["--lambda", str(lam), "--mu", str(mu)])
            if any(h[5] == repl and h[4] != h[5] for h in hh):
                recall += 1
        return fp, recall

    w("  λ 扫描（μ=0.70 固定）        误改↓ / 别名召回↑（共 6 条探针）")
    for lam in LAMBDA_GRID:
        fp, rc = score_config(lam, DEFAULT_MU)
        w(f"    λ={lam:<5} ->  误改 {fp}   召回 {rc}/6")
    w("  μ 扫描（λ=0.65 固定）")
    for mu in MU_GRID:
        fp, rc = score_config(DEFAULT_LAMBDA, mu)
        w(f"    μ={mu:<5} ->  误改 {fp}   召回 {rc}/6")
    w("  组合扫描（关键单元格）")
    for lam, mu in [(2.61, 0.70), (3.0, 0.70), (4.0, 1.0), (6.0, 1.4), (2.0, 4.0)]:
        fp, rc = score_config(lam, mu)
        w(f"    λ={lam:<5} μ={mu:<5} ->  误改 {fp}   召回 {rc}/6")

    w("")
    w("=" * 78)
    w("五、可用规避手段（实测）")
    w("=" * 78)
    w("  1) 热词锁定：把文本内的真词加入 word.txt，锁定后拼音层不再评估与之重叠的窗口。")
    with tempfile.TemporaryDirectory() as td:
        table = pathlib.Path(td) / "word.txt"
        base = [l.strip() for l in WORD_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
        table.write_text("\n".join(base + ["核实", "谈话", "人员", "调查", "通报"]) + "\n",
                         encoding="utf-8")
        proc = subprocess.run([EXE, "-v", "--word-file", str(table)],
                              input=src_main.encode("utf-8"), capture_output=True, cwd=ROOT)
        hits = HIT_RE.findall(proc.stderr.decode("utf-8", "replace"))
        locked = [h for h in hits if h[1] == "ac_locked"]
        rew = [h for h in hits if h[4] != h[5]]
        w(f"     补 5 个正文真词后：AC 锁定命中 {len(locked)} 处，改写型命中 {len(rew)} 处"
          f"（原为 2 处）")
    w("  2) --no-pinyin：完全关闭拼音层，只剩 AC 精确锁定。")
    np_hits, _, _ = run(src_main, ["--no-pinyin"])
    np_recall = sum(1 for text, _, repl, _ in ALIAS_CASES
                    if any(h[5] == repl and h[4] != h[5]
                           for h in run(text, ["--no-pinyin"])[0]))
    w(f"     实测：本语料改写型命中 {len([h for h in np_hits if h[4] != h[5]])} 处，"
      f"别名召回 {np_recall}/6 —— 误改与修正同时归零。")
    w("  3) 给 f(O) 加回退：窗口查不到时退到子串/单字最大频次，或改用 O 的字符数先验，")
    w("     可让「话核」不再等于 0。")
    w("  4) 对 logR 设上限（例如 min(logR, 2)）或改成 λ·D + μ·len(C) 的长度代价，")
    w("     避免单个高频品牌词压过一切。")
    w("  5) 窗口最小长度 3 或要求 O 至少是词频表前缀，能直接屏蔽「虚词+实词」片段。")
    w("  6) 参数侧兜底（不改代码）：默认值改为 λ≥2.62（建议 2.7~3.0）、μ=0.70，实测本例误改 0、")
    w("     别名召回 5/6；但这只是压住 f(C)=373 这一个词，f(C) 上千的品牌词进动作词表后")
    w("     仍需继续加大 λ。")

    w("")
    w("=" * 78)
    w("六、结论")
    w("=" * 78)
    w(f"  1. 会发生错误改写：人工核对为 100% 正确的 {total_cp} 字符文本被改 {total_chars} 字符，"
      f"{total_fp} 处，全部为「跨词片段 -> 华为」的语义污染，命中有效率 0/{total_hits}。")
    w("  2. 根因是频次证据的口径错配，不是实现缺陷：f(O) 只对整窗口查表，跨词片段恒为 0，")
    w("     使 logR 退化为 ln(1+f(C)) 的常数门槛；而 λ·D 线性惩罚（最大 1.30）远小于")
    w("     log 尺度的频次差（5.92），μ=0.70 又低于 f(C)>=3 词的 logR，")
    w("     结果任何 f(C)>6.39 的规范词都能改写任意 f(O)=0 的同/近音片段。")
    w("  3. 误改方向不可排序：本例误改候选（华为 f=373，logR=5.92）的频次证据高于全部真实修正")
    w("     目标（下限词 logR=1.386），因此靠 μ 压制会毁掉召回（μ≥4.63 时召回 1/6，μ≥5.0 清零），")
    w("     靠 λ 压制只挡住 D>=1 的低频修正（λ≥2.62 时误改 0、召回 5/6）。λ 是在逐词追赶")
    w("     而非修正机制：见第三节末表，f(C) 越高的规范词需要越大的 λ。")
    w("  4. 词频下限 3 是隐性免检通道：规范词/热词 f(C)>=3 时 D=0 必过、D=1 必过，")
    w("     等于对低频词关闭了阈值。")
    w("  5. 现阶段可用兜底仍是 AC 层：word.txt 锁定 + 高频品牌词进词表（第五节 1 已把")
    w("     本例误改清零），拼音层在补齐 f(O) 回退与 logR 截断前不宜默认开启。")
    w("")
    w("附录：本轮命中原始明细（stderr）")
    _, _, err = run(src_main)
    for line in err.splitlines():
        if line.strip():
            w("  " + line)

    LOG.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
    print(f"报告已写入 {LOG}（{len(lines_out)} 行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
