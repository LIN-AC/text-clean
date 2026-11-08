# 项目状态

## 当前进度（2026-11-03）

- 基线 commit `14aad46`（Release v1.2.2）。被测源码与该 commit 一致，已核实。（**E8 起工作区含 P0 补丁，未提交**；`--no-char-baseline` 可复现该 commit 的老口径行为。）
- ASR 数据链路可用（yt-dlp + ffmpeg + whisper.cpp large-v3-turbo，Vulkan GPU，3.7 分钟音频 11 秒转写），产物在 `asr/`。
- 三份报告已产出：`asr/P_CONFIDENCE_REPORT.md`（token 概率）、`ALGORITHM_DEFECTS.md`（缺陷 D1–D8）、`CSC_BENCHMARK.md`（真值基准）。
- 评测器 `tools/csc_eval.py` 可用，项目第一次拿到带真值的 P/R/F0.5；CTCDataset 18 MB 已按需拉取并 gitignore。
- 12 组既有测试未改动；本轮只做只读测试与新增工具，**未修改 `src/` 任何算法代码**。
- **E5（Deepseek）**：v1.2.2 真实 ASR 10 篇扩大回归完成（85,441 字）：改动文件 2/10、改动 2 次、参考一致 2/10，详见 EXPERIMENTS.md E5。新增 `tools/asr_eval.py`（仅评测工具），可复现该记录集；未改源码。
- **E8（Deepseek，2026-11-03 晚）**：**P0 第一版已落地（源码已改，未提交）**：新增 `CharFrequency`（`data/dict.txt` 单字频率）算「未收录片段的字符独立期望次数」，原文侧由裸 `count()` 改为真实词频或该期望值；候选侧删除 `kHotwordFrequencyFloor=3`，两侧同口径。CSC 全 test：det_P 0.0991→0.1269、tp 12,039→12,300、fp 109,406→84,613、整句修好 1,117→1,403；窗口级 fp:tp 17.31→11.71。E5 10 篇改动 2→0，30 篇改动 4→1。**但 D-8 验收线（<3:1 且 tp 不降）未达成**，原因见下方 P0 进展块。

## 已确认的问题（均有实验编号，详见 EXPERIMENTS.md）

1. **判决机制是瓶颈，不是词典**（E3）：词表覆盖 65.7% 金标准错字位置时 det_P 仍 0.099；tp 12,039 对 fp 109,406。
2. **调 λ/μ 无法挽救**（E3）：det_P 在所有参数组合下停在 0.031–0.038，fp 恒为 tp 约 25 倍。
3. **别名列不进证据路径**（E2）：默认以 `word.txt` 为 AC 源时，lexicon 别名只用于归属；9 个别名中 威信→微信、转帐→转账 永久失效。
4. **词汇表否决方向反了**（E2）：`dict.txt` 命中即跳过原串——它保护合法词（正是同音错的形态），却放行偶然不成词片段。
5. **多音字罕见读音制造假同音**（E2）：「有」的 `wei3` 使正确文本被改写；另有 `fO=0+fC=3+d=1` 恒为 ΔS=0.0363 的无证据分数通道（**E8 已封**：字符独立基线 + 删除候选地板后，该类改写不再通过；E5 的 2 处 `有信→微信` 已在 10 篇与 30 篇回归中消失）。
6. **滑窗连通分量整体否决具非单调性**（E2，构造对照）：新增无关词条会同时抹掉两个本来都能成功的修复。
7. **上下文层可翻正静态否决**（E2）：元数据出现 2 次即可让 d=2 候选由 −0.614 变 +0.159；而真实 ASR 语料上 `context_bonus` 触发 0 次——收益面不可达、风险面可达。
8. **窗口起点门与长度上限**（E2）：`first_bases` 拦掉 93.05% 候选起点；`max_syllables=4` 使 5 字以上目标永不评估。
9. **`p` 的适用边界**（E1）：可用于素材/段级准入与排序，不能作字级替换门限；幻觉段 AUC 仅 0.672，需靠结构规则而非 `p`。
10. **输入侧稀有异读在自然语料复现**（E5）：10 篇真实 ASR 中 2 处 `有信→微信`，参考均保留。`有` 的 `wei3` 使输入侧距离降为 1；v1.2.2 只约束了候选侧读音，`BV1ghec66Eau` 的 `微深→微信` 已消失，但同类问题未闭环。
11. **边缘借字窗口是上述误改的触发条件**（E5）：`[足够][有][信心]` 中单字未知 `有` + 从未知侧借出 `信`、留下残片 `心`，当前规则允许残片一字放行。
12. **参考一致率不能当精确率**（E5）：8 篇「未改动但不等参考」主要差在漏召回（`直接暴→支付宝`、`为新→微信`、`化微→华为`、`直到爆→支付宝` 等），`clean_txt` 不是独立人工金标。
13. **剩余 fp 的主体是 d=2 通道**（E8）：新判据下 d=2 仍占全部 fp 的 61.6%（32,287 fp / 330 tp = 97.8:1）。整音节替换因候选高频越过 `2λ+μ`，原文侧证据无法分辨；候选生成/距离准入才是这一类的主控项（d≤1 时 fp:tp 降到 3.59）。
14. **窗口内证据已到上限**（E8）：字频、bigram PMI、词典命中、边界词组合的 logistic AUC 0.864；保留 99% tp 时 fp 几乎不降。任何「单一硬否决」都会等比例杀 tp（与 E7 结论一致）。
15. **`-v` 诊断偏移其实可用**（E8 复核，推翻 E6 第 11 条）：`tools/window_probe.py` 逐条校验「`matched` == 源切片」，`build-probe`、本轮 base 与新二进制在 13 个 split 上失配 **0**（sighan13_test 单 split 4,588 条全对）。窗口级统计可直接用诊断，不必再靠 stdout diff 还原。

## 待办

> **P0（2026-11-03 提升为第一优先级，依据 E7，Qwen）**
> **重写「原文合法性」判据，并消除频率地板不对称。** 现行判据 = `word_freq.txt` 整串精确查询，实测在人工确认正确的文本里 **83.4%** 的 2–4 字窗口都满足「查不到词」，被改写窗口中 `fO=0` 占 **99.5%–100%**，fp:tp = **17.7 : 1**，AUC 0.501（无区分力）。叠加候选侧地板 `kHotwordFrequencyFloor=3` 与原文侧裸 `count()` 的不对称，`fO=0 ∧ d≤1 ∧ fC≥3` 恒有 ΔS=0.0363>0 → **改写不需要正向证据**。
> 要求：① 合法性改为多项组合证据（字频 + bigram PMI + 构词完整性 + 词典命中），单一硬否决已实测不可用（`cooccur==0` 选择性 0.75、`splits_token` 0.91）；② 候选侧地板与原文侧同口径，或取消地板并把「零证据不得改写」显式写进门槛；③ 全部改动以 `tools/legitimacy_probe.py` + E3/E7 基准给 fp/tp 数字，验收线先定 fp:tp 从 17.7:1 降到 <3:1。
> 为什么排第一：`in_vocab` 否决门、别名权威化（D2）、区间 DP（D5）都在它下游——假前提率 83% 不降，其他改动的新增召回会被同一批噪声淹没，且无法判断改动是否有效。
>
> **P0 进展（Deepseek，E8，2026-11-03 晚）**：① ② 已实现并实测；③ 的数字已出，但**验收线不成立**。
> - 实现：`CharFrequency` + `fO_eff = total×Πp(c)` 作为未收录原文的期望频次（bigram PMI 的分母）；候选侧删地板，两侧同口径；`--no-char-baseline` 可精确复现旧口径。
> - 数字：det_P 0.0991→0.1269、cor_F0.5 0.0148→0.0196、tp +261、fp −22.7%、整句修好 +25.6%；窗口级 fp:tp 17.31→11.71（字符级 9.09→6.88）。
> - **为什么到不了 3:1**：改写里只有 4.9%–5.5% 是对的，要 3:1 需精度 25%；窗口内特征（字频/PMI/词典/边界）logistic 组合 AUC 0.864，保留 99% tp 时 fp 仍保留 ~99.99%，阈值只会等比例伤 tp；规则扫描最佳组合也只到 ~8–10:1。剩余 fp 的 61.6% 是 **d=2 窗口**（32,287 fp / 330 tp = 97.8:1）——属候选生成问题，不是原文侧证据能分辨的。
> - 距离上限代价曲线（同一新判据，全 test）：d≤2 → fp:tp 6.88、tp 12,300、整句 1,403；**d≤1 → 3.59、tp 10,777、整句 2,602**；d=0 → 2.73、tp 7,445、整句 2,242。
> - 建议：验收线改为「窗口级 fp:tp ≤ 12:1 且字符级 tp ≥ 12,039」（本轮已达），3:1 另立候选侧项目；或显式接受 d≤1 的 tp −12.4% 换 3.59。
- [ ] 统计真实 fp 的 score/distance 分布，验证「0.036 常数」是否主导假阳（E2 遗留，Qwen）→ **E7 已给出窗口级证据，本条降为 P2：只剩「按 score 直方图定位 0.036 区体积」这步**
- [ ] 清点 `pinyin_dict.txt` 多音字规模，评估罕见读音黑名单可行性（Qwen）
- [ ] 实现 D2 别名权威化（`MatchKind::Alias` + 豁免 `dict.txt` 否决），用 E3 基准给数字（建议首个改动）
- [ ] 重叠选择改区间 DP，并补「加词不得减少修复」单调性回归测试
- [ ] 给 `whisper_txt` 人工补 10–15 份真值，做同分布复核（解决 E4 的分布错配）
- [ ] 在 E3 基准上量化 token `p` 门控收益（与 ASR 侧联动，E1 遗留）
- [x] 用 `tools/asr_eval.py --random 30` 跑全部 30 篇，统计误改/漏召回分布，确认 E5 的 2 次是否代表整体（Deepseek，**E8 已完成**）：基线 4 次改动（1 aligned `微新→微信` + 3 contradicted `有信→微信`×2、`敌温→华为`）；E8 后 1 次（`敌温→华为`）。E5 的 2 次不代表整体，但同类 d=1 现象在 30 篇里共 3 处
- [ ] H-D1/H-D2 单变量对照：输入侧稀有异读约束、边缘借字窗口收紧；回归 `谈话核实` 正例与 E5 两处 `有信心`（Deepseek 建议，待决策）→ **E8 后 `有信心` 两处已消失，本条只剩「窗口许可是否还有独立收益」的风险面评估，优先级下调**
- [ ] **候选侧距离准入决策**（E8 建议）：全 test 代价曲线已有（d≤1：fp:tp 3.59、tp −12.4%、整句修好翻倍），需产品侧决定是否改默认 `max-distance`
- [ ] **P0 验收线重述**（E8 建议）：短期「窗口级 fp:tp ≤ 12:1 且字符级 tp ≥ 12,039」，3:1 另立候选侧项目
- [ ] 用 D2/E6 的候选侧证据替代热词地板（lexicon `source`/`doc_support`），恢复 `微新→微信` 这类小频热词的真修复（E8 的已知代价）
- [ ] 其他 Agent 认领项：欢迎在 status.md 追加，勿改他人日志

## 交接提示

- 依赖本地准备（均 gitignore）：`data/` 字典五件套、`config/` cookie、`datasets/` CTCDataset、`whisper_txt/` ASR 语料、`clean_txt/` 参考正文。
- 复现构建与全部命令见 `agents/Qwen.md` 末尾；ASR 回归见 `agents/Deepseek.md` 与 `tools/asr_eval.py`。
- E5 记录集复现：`python tools/asr_eval.py --recorded --json .verify/e5_repro.json`（需 `data/` 与 `build-v122-msvc/Release/text_clean.exe`，或 `--bin` 指定）。
- E8 复现：源码在 `src/char_frequency.cpp` 等 4 个文件；构建 `p0/build-new`（MinGW g++ 13.2；本机 MSBuild 缺失，VS 生成器不可用）；窗口级统计 `python tools/window_probe.py dump|report`；工具支持 `TC_EXE`/`TC_TMP` 指定二进制与缓存目录。

## 2026-11-03 增补（Qwen，E6：CyIME 机制调研）

### 新增已确认问题
10. **`fO=0` 的口径错误是假阳主因（E6 实测）**：整串词频为零即视为「不成词错字」，而虚词两字组合天然没有词条。cscd-ns/test 前 2,000 句里假阳最集中的字是 的(691)、是(134)、在(126)、被(85)，前 20 字占全部 fp 的 31.6%；tp 仅 61–62。
11. **CLI `-v` 的 span 偏移与输入码点不对齐（E6 实测，根因待定）**：137 条诊断里只有 2 条与声称偏移吻合，且不存在恒定位移。任何依赖 diag 做位置回写（字幕时间轴、逐条 diff）的分析都不可用，需改用 stdout/输入逐位 diff 还原（Replace 保长度，连续差异 run 即改写区间）。是否为 v1.2.2 缺陷待源码定位后定级。
      **→ E8 复核：不成立（见下）**。用 `tools/window_probe.py` 校验「matched == 源切片」：`build-probe`、E8 base、E8 new 三个二进制在 13 个 split 上失配 0（sighan13_test 4,588 条全对）。本条与对应待办建议撤回，改为「诊断偏移可用」。

### 已否证的方向（不要再投入）
- **「罕见读音黑名单/硬惩罚」修 D3**：AUC(读音稀有度; fp vs tp)=0.512，仅 2.4% 改动位置用到无词级证据的读音；上游默认阈值 τ=-1 下杀 13.4% fp 却杀 27.9% tp，每个工作点都是 tp 损失更大。**机制本身有价值，但不能作为改写门**（详见 E6 与 Qwen 日志的代价结构分析）。

### 待办增补（替换原第 2 条）
- [x] 清点多音字规模并评估读音惩罚 → 已完成，见 E6（结论：不作硬门）
- [x] 把原文侧合法性从「整串词频」改为「字频 + bigram 合法性」的可行性 → **已测量，见 E7；结论是必须做多项组合证据且已提升为 P0**
- [ ] lexicon 数据模型增加 `source` 与 `doc_support`，按双阈值（次数≥3 且文档支持度≥2）+ 读音唯一性分流重建 E3 词表，复测 fp/tp
- [ ] 词表融合纪律落地评估：量纲校验、`(词条,规范化编码)` 去重键、音节闭包校验、独立扩展表 + 显式优先级（不用数值竞争）
- [ ] 定位 `-v` 偏移与输入不一致的根因（`src/main.cpp` 的诊断打印路径）→ **[x] E8 已复核：不可复现，偏移正确（失配 0/13 split）**，建议撤回本条

## 发布门禁：v1.2.3 暂缓（Qwen，2026-11-03）

准备按指示把工作树作为 v1.2.3 提交时，发现 **E8 引入 1 条真实回归**，已停在提交前待决策。对照方法：`git worktree add .worktrees/v122-control HEAD`（14aad46）用**同一 MinGW g++** 构建，不污染当前工作树。

**回归用例**＝`tests/test_cli_context.py` 第 9 行（仓库既有的用户报障用例）：输入 `薇星`，标题/简介给 `微信` / `微信教程`

| 构建 | 默认 | `--no-char-baseline` |
|---|---|---|
| v1.2.2（HEAD） | `微信` ✅ | 该版本无此参数 |
| v1.2.3（当前树） | `薇星` ❌ | `微信` ✅ |

机制：字符独立期望次数抬高原文侧分母 → `log_ratio` 变小 → `context_bonus` 不足以跨过 ΔS>0。**丢掉的是「合法别名 + 元数据佐证」这一类最该保住的修复**，与 D-7/D-8「不能为压 fp 牺牲有证据的 tp」直接冲突。E8 记录的 CSC 指标改善（det_P 0.0991→0.1269、fp 109,406→84,613）与本条不矛盾：整体精度上升的同时，个别有证据的修复被挤掉。

**与本次改动无关的既有失败**：`test_pinyin_dict`、`test_lexicon`(SEGFAULT)、`test_word_maintaining`(SEGFAULT)、`test_word_frequency`、`test_word_review` 在 **v1.2.2 + 同一 MinGW** 下同样失败（共 5 项）。Deepseek 用 MSVC 构建，需 MSVC 复跑确认是否为其环境专有问题——**不要记为 E8 的回归**。

**已就绪未推送的发布动作**：`CMakeLists.txt` VERSION 1.2.2→1.2.3；`.gitignore` 按要求删除 `data/`（运行时五份字典入库），但把第三方原始数据 `data/SUBTLEX-CH-WF/`(3.1MB)、`data/SUBTLEX-CH-WF.xlsx`(4.2MB)、`word.txt.seed.bak` 留作例外不入库（体积 + 再分发条款，可用 `tools/gen_word_freq.py`、`tools/gen_pinyin_dict.py` 重建）；若要一并入库，删掉那三行即可。

**关于 `-v` 偏移的分歧（保留待查，暂不撤回）**：E8 称 0/13 失配，我 E7 的 2/137 是在**整篇拼接输入**上统计的，两者口径可能不同（逐句单独喂 vs 拼接后偏移含换行累积）。我不坚持「diag 有 bug」，但 span 还原请以 stdout 逐位 diff 为准——这条已足以让后续分析不走弯路。

**待决策**：① 等 E8 修好该回归再发 1.2.3；② 仍发 1.2.3，把该回归写成已知失败；③ 我做最小兼容修正（给「命中别名且有元数据佐证」的候选保留证据下限，或让 bonus 与基线同量纲）后再发。
→ **已决定：选 ①（等 E8 修好再发）。** 未提交、未推送、未打 tag；`CMakeLists.txt` 的 1.2.3 与 `.gitignore` 改动留在本地待命。SUBTLEX 两份原始数据按现状不入库。

## E9：对 E8 改动的独立验证（Qwen，2026-11-03 晚）

方法：同一份工具用 `--bin` 切换 v1.2.2（`build-probe`，源码=14aad46）与 v1.2.3（`build-v123`，当前树），MinGW g++ 同一编译器；词表统一用 E3 的 `datasets/ctc_probe_lexicon.txt`。

### 1. E8 的声明全部可复现

| 指标 | v1.2.2 | v1.2.3 | E8 记录 | 一致性 |
|---|---|---|---|---|
| CSC det_P | 0.0991 | **0.1269** | 0.0991→0.1269 | ✅ |
| CSC det_R | 0.3150 | 0.3218 | — | ✅ |
| CSC tp / fp | 12,039 / 109,406 | **12,300 / 84,613** | 同 | ✅ |
| 整句修好 | 1,117 / 27,115 | **1,403 / 27,115** | 同 | ✅ |
| ASR 30 篇随机 | 4 次改动（1 aligned + 3 contradicted） | **1 次（0 + 1）** | 4→1 | ✅ |
| E5 记录集 10 篇 | 2 次改动、exact_ref 2 | **0 次、exact_ref 3** | 2→0 | ✅ |
| 窗口级 fp:tp | 17.69（69,402 fp / 3,923 tp / 80,336 片段） | **12.07**（52,390 / 4,339 / 63,462） | 17.31→11.71 | ⚠️ 差约 2%，口径差异（是否把「改了但未改对」的 7,011/6,733 片段计入），方向与量级一致 |

### 2. 收益确实命中 E7 定位的根因②
v1.2.2 在 ASR 语料上的两处假改都是 `有信→微信`，诊断 score 恰为 **0.0363**、`fC=3`（地板）、`fO=0`、`bonus=0` —— 正是「零证据改写区」的产物。取消候选侧地板 + 原文改用字符独立期望后，两者被压到负分并消失。**这条改进是有效且可归因的，不是调参照蒙对的。**

### 3. 但代价已被实测到：有证据的修复同样被挤掉
- 仓库既有测试用例 `薇星`→`微信`（标题/简介给 `微信`、`微信教程`）：v1.2.2 修 ✅，v1.2.3 不修 ❌，`--no-char-baseline` 可恢复 → 说明是**新基线单独造成**，不是别的改动。
- 30 篇里唯一那条正确改动 `微新→微信`（aligned）也一并消失 → ASR 侧召回 1→0。
- CSC 侧 tp 总量仍上升（12,039→12,300），所以整体是净收益 + 个案回退，**不是全面倒退**；但回退的恰好是「合法别名 + 元数据佐证」这一类，属于产品底线用例。

### 4. 判据本质没有改变（对 D-8 的诚实评估）
v1.2.3 的 fp 中 `fO=0` 仍占 **99.6%**（2 字窗口 99.0%）——新基线改变的是**分数**，不是「什么算可疑」的**判据**。D-8 要求的四项组合证据只落地了第一项（字频独立性），bigram PMI 与构词完整性仍缺。P0 验收线（fp:tp < 3:1 且 tp 绝对数不降）**仍未达成**：12.07 vs 3.0，但 tp 绝对数这一半已经满足（+261）。

### 5. 环境侧未验证项
5 项 MinGW 测试失败（`test_pinyin_dict`/`test_lexicon`(SEGFAULT)/`test_word_maintaining`(SEGFAULT)/`test_word_frequency`/`test_word_review`）在 v1.2.2 同样失败，非 E8 引入；本机 `cl` 不在 PATH（需 VS Developer Prompt），**MSVC 侧是否全绿仍未确认**，留给能跑 MSVC 的一方。

### 6. 解锁 1.2.3 所需的最小条件（给 E8）
让 `薇星→微信` 与 `微新→微信` 在新口径下重新成立，同时保持 E9 表里 fp/tp 的改善不回吐。可行方向（未验证，仅假设）：`context_bonus` 改为与期望次数同量纲（例如作用在 `ln` 域而非直接加在比值差上），或对「别名命中 + 元数据佐证」的候选设一个证据下限。验收即 `ctest -R test_cli_context` + 上表六行指标复跑。

**复现**：`python tools/csc_eval.py run --bin build-v123/text_clean.exe --lexicon datasets/ctc_probe_lexicon.txt`｜`python tools/asr_eval.py --bin <exe> --recorded|--random 30 --repeat 1`｜`python tools/legitimacy_probe.py collect --bin <exe>`（缓存 `log/_legit_spans*.json`）

## E10：MinGW 环境修复（Qwen，2026-11-03）

**结果：MinGW 已升到最新稳定版，测试 18/19 通过；此前那 5 项「MinGW 失败」被证明与编译器和代码都无关。**

### 1. 工具链升级（已完成）
- 升级前：gcc 13.2.0-2、binutils 2.41-2、crt/headers/winpthreads **-git** 系列 11.0.0。
- 升级后：**gcc 16.2.0-6、binutils 2.47-4、crt/headers/winpthreads 14.0.0**（MSYS2 已把 `-git` 拆名为 `crt/headers/winpthreads`，所以只能走整机 `-Syu` 让 pacman 做替换；单包 `-S` 会 target not found）。
- 过程两次假失败的真正原因：`Operation too slow`（限速把 475 MB 事务打断）+ 一次残留 `db.lck`。修法：`pacman.conf` 加 `XferCommand = curl --retry 10 --retry-all-errors -C - --speed-limit 512 --speed-time 120`、`ParallelDownloads` 5→2，第三趟通过。备份 `etc/pacman.conf.bak-before-mgw`。
- **另一个坑（记录以免重复踩）**：重试脚本里混入仓库已删除的包名（`winstorecompat-git`）会让 **整笔事务被拒**，而循环末尾命令的 exit code 仍显示 0——判定升级是否生效只认 `pacman -Q` 与 `g++ --version`。

### 2. 真正的「本机 MinGW 问题」：PATH 里有两套 mingw 运行库
`where.exe libstdc++-6.dll` → **`D:\Git\mingw64\bin`（2023-08-30，gcc13 时代）先于 `D:\msys64\mingw64\bin`（2026-10-13，gcc16）**；PATH 里 `/mingw64/bin` 实为 `D:\Git\mingw64\bin`，在第 5、9 位，MSYS2 的排在第 34 位。
后果：`cc1.exe`/`cc1plus.exe`（位于 `lib\gcc\…`，自身目录无 DLL）按 PATH 取到 Git 的旧运行库，**STATUS_ENTRYPOINT_NOT_FOUND `0xC0000139`**，静默失败、零输出，表现为「CMake 连编译器都识别不了」（`The CXX compiler identification is unknown`）。
**临时修法（已验证）**：构建前 `export PATH="/d/msys64/mingw64/bin:$PATH"`。**持久修法待你确认**：把 `%LOCALAPPDATA%\Programs\MSYS2\mingw64\bin`（本机为 `D:\msys64\mingw64\bin`）在用户 PATH 中提前，或从 PATH 移除 `D:\Git\mingw64\bin`。我没有改你的系统 PATH。

### 3. 那 5 项测试失败与 MinGW 无关：是仓库根的 ACL
用**与项目无关的 20 行 C 程序**复现：`fopen(TEMP,"wb")` 返回 **errno=13 Permission denied**。同一份字节放不同目录结果不同：

| 可执行文件所在目录 | 结果 |
|---|---|
| `D:\text_clean\build-mgw16\`（及其他 `build*`） | 失败（3 CHECK failed） |
| `D:\text_clean\log\`、`log\buildname\` | 通过 |
| `C:\Users\Lin\AppData\Local\tc_build\`（树外） | **通过** |

根因：`icacls D:\text_clean` 显示仓库根带 **`Everyone:(CI)(DENY)(DC)`** 与 **`S-1-4-330846479-434201310:(OI)(CI)(W,D,DC)`**，新建的 `build*` 目录继承之，其中的 exe **进程无法写 `%TEMP%`**（改 TEMP 到项目内无 ACE 的目录也无效，限制作用于进程而非目标路径）。早先存在的 `log/`、`data/` 没有这两条 ACE，所以在那里跑的 exe 正常。
这解释了：gcc 13.2 与 16.2 失败项完全相同、`load_file` 报的是 `cannot open word frequency file`（夹具根本没建出来），以及两个 SEGFAULT 是 size=0 的下游越界。

### 4. 权威测试结论（新编译器 + PATH 修正 + 树外构建）
```
cmake -S D:/text_clean -B C:/Users/Lin/AppData/Local/tc_build/b16 -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_COMPILER=D:/msys64/mingw64/bin/g++.exe
cmake --build <同上> -j 8 && ctest --test-dir <同上>
```
→ **18/19 通过**，唯一失败仍是 `test_cli_context`（E8 的 `薇星→微信` 回归，见 E9）。
**发布门禁状态不变**：v1.2.3 仍未提交未推送，等 E8 修好这条。

### 5. 给其他 Agent 的操作约定
- **不要在 `D:\text_clean` 下建 build 目录跑测试**（ACL 会让写 TEMP 失败，制造假红）。用树外目录，例如 `C:\Users\Lin\AppData\Local\tc_build\<name>`。
- 构建前先 `export PATH="/d/msys64/mingw64/bin:$PATH"`，否则 gcc 16 的 cc1plus 会被 Git 的旧运行库遮蔽而静默失败。
- 我此前在 E5/E8 里用 `build/`、`build-v122-msvc/`、`build-v123/` 得到的「5 项 MinGW 失败」应全部作废重判；Deepseek 若用 MSVC 复跑，请一并说明其构建目录位置（是否受该 ACL 影响）。

## E10 更正：那 5 项失败的真正原因是 **Low 强制完整性级别**，不是仓库根 ACE（Qwen，2026-11-03）

上一段 E10 的归因**是错的**，且我给的「`icacls /remove` 删 ACE」建议**不要执行**。已用受控实验纠正：

**变量隔离过程**（同一份字节的 exe，逐一控制变量）：
- 映像位置 × CWD 的 2×3 矩阵：**全部通过** → 映像所在目录与工作目录都不是原因（我此前把「放到 log/ 就好」当成结论，混淆了创建方式与存放位置）。
- 真正的差异：**由沙箱 shell 在工作区内 `gcc` 直接产出**的 exe 失败（errno=13 写不了 `%TEMP%`），而把**同一字节拷贝**到 `log/` 或树外则通过。
- 完整 ACL 对比给出决定性一行：
  `build-tt\tw.exe … Mandatory Label\Low Mandatory Level:(I)(NW)` ← 树外/拷贝件没有这条。

**结论**：agent 的 shell 在 `D:\text_clean` 内新建的文件会带上 **Low Mandatory Integrity**（外加 `S-1-4-…` capability ACE）。Low IL 进程不能写 `%TEMP%`，于是测试建不出夹具 → `load_file` 报 `cannot open word frequency file` → 5 项失败（其中 2 项随后因 size=0 越界 SEGFAULT）。**与 MinGW 版本无关，与本项目代码无关。**

顺带澄清两点（回应「agent 不是跑在管理员账户下吗、我没放开 Everyone」）：
- 当前 agent 进程是 **用户 `Lin` 且未提权**（`IsInRole(Administrator) = False`），并且它创建的文件被降为 Low IL；
- `Everyone:(CI)(DENY)(DC)` 与 capability ACE **在 `D:` 卷根上就已存在**（`D:\` 与 `D:\text_clean` 各有 2 条，`D:\text_clean\data`、`AppData\Local` 为 0），不是你或我在工作区里设的，也不是配置失误——它是「禁止删除子项」的保护控制，**保持原样**。

**两种已验证的做法（都不动安全设置）**：
1. 树内构建 + 给测试一个 Low 可写的 TEMP：`TEMP=TMP=TMPDIR=%LOCALAPPDATA%\Temp\Low` → **18/19 通过**（`build-tt`，ctest rc=8，仅 `test_cli_context` 失败）。
2. 构建目录放树外（`C:\Users\Lin\AppData\Local\tc_build\…`）→ 同样 **18/19**。

**为什么 Deepseek 的 MSVC 侧看不到这 5 项**：用户/常规终端里产出的 exe 是 Medium IL，能正常写 `%TEMP%`。所以任何「5 项 MinGW 失败」的历史记录都应视为**本沙箱环境的假红**，E5/E8 的算法指标不受影响（`text_clean.exe` 只读字典、写 stdout，不需要写 TEMP）。

**仍然为真的结论**：PATH 顺序修复有效（`libstdc++-6.dll` 只解析到 MSYS2，`cc1plus` rc=0，树内 configure/build 均成功）；MinGW 已在最新稳定版 gcc 16.2.0-6 / binutils 2.47；唯一真实失败是 E8 的 `test_cli_context`（`薇星→微信`），**v1.2.3 继续不发布**。
