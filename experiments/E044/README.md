# E044｜新架构复跑 + 完全真值双臂复跑（2026-11-12，Qwen）

触发原因：E043 把候选表定稿（全量启用、删片段行、`更赋` 替 `耕赋`），V1 基准更新为 **152/79/23/1951**。
`rag_clean.Cleaner` 会校验包内绑定的 `data/correction/candidates.tsv` 哈希，**旧包一律拒绝加载**，
所以本轮必须先重建包，再按 `experiments/E046/README.md`（Deepseek 的方法）原样复跑。
未修改 `src/`、`include/`、`data/`、`asr/`、评分参数与默认值；未改动 Deepseek 的脚本（用 import 覆盖常量的方式复用）。

## 1. 怎么测的

包（新目录，不覆盖 e038/e042）：

| 包 | 源库 | 文档 / 块 | 说明 |
|---|---|---:|---|
| `build/e044_base` | `build/e036_corpus/corpus_train.sqlite` | 80,198 / 607,006 | 与 E038 train_v2 同源，只换词库 |
| `build/e044_full` | `build/e044_corpus/corpus_merged_train.sqlite`（E036 训练侧 + E042 补充库） | 234,189 / 7,770,473 | 现代 3,083 万 + 历史 2,271 万汉字；模型训练句段 3,938,461 |
| `build/e044_openbook_{base,full}` | 由 Deepseek 的 `build_openbook_package.py` 生成，仅把证据换成七篇真值句子 | — | 测试产物，含真值，只留在 build/ |

臂与口径（全部七篇开卷、同参数 a=0 β=1 κ=10 ρ=1 α=.01 H=30 检索 50 段、不给标题简介、
评测用 E024 `align_lib` 的数字归一与唯一对齐）：

- `v1`：C++ 生产默认（`build/e035/text_clean.exe --no-index-cache`）。
- `rag`：新入口（RAG+N-gram+新公式，`--research`，有检索）。
- `rag_no_retrieval`：新入口去掉检索（只留字符 4-gram 与判决）。
- `openbook`（臂1）：证据库换成七篇真值句 + 照常检索 —— Deepseek 的原脚本，仅换包路径。
- `perfect`（臂2）：不检索，把每个窗口所在真值句直接构造成领域计数注入；**输入上下文仍是 ASR**，
  两次 pass 的窗口数必须一致，否则报错 —— 同为 Deepseek 原脚本。
- 归因脚本 `scripts/attribute_openbook.py` 与拆解脚本 `scripts/split_gain.py`：拿 Deepseek 旧表 trace 与本轮新表 trace 逐位点比 TP 集合，
  并按"当初写入的目标词是否被删/停用"归类。含真值的 trace 全部写 `build/`（.gitignore），不进仓库。

## 2. 结果：只换词库（`e044_base`）

| 臂 | 改对 | 误改 | 错到错 | 总距离 | Deepseek 旧表记录 | 变化 |
|---|---:|---:|---:|---:|---:|---|
| 零操作 | 0 | 0 | 0 | 2,024 | 2,024 | — |
| V1 默认 | **152** | **79** | **23** | **1,951** | 145/83/25/1962 | 复现新基准 ✓ |
| 新入口 + 检索 | 6 | 0 | 0 | 2,018 | 10/0/0/2,014 | **−4，且检索增益归零** |
| 新入口 无检索 | 6 | 0 | 0 | 2,018 | 6/0/0/2,018 | 不变 |
| 臂1 真值图书馆+检索 | 162 | 2 | 0 | 1,864 | 171/1/0/1,854 | −9 改对，+1 误改 |
| 臂2 完美证据不检索 | **214** | 1 | 0 | 1,811 | 212/0/0/1,812 | **+2 改对** |

三条要点：

1. **检索臂与无检索臂现在完全相等（6=6）**。E037/E038/E046 那唯一 4 字检索增益来自
   `魏清获取→卫青霍去`，而 `卫青霍去` 是园长本轮删掉的切分行。**删掉之后，检索在新架构里
   对这七篇的净贡献变成 0**——这是本轮最硬的结论之一。
2. **完美证据上限还略升了**（212→214）：定稿表让 `桑弘羊`、`祥符决口`、`均输平准`、`禁词` 等在更多位点
   成为可执行候选；代价是 `会要辑`、`卫青霍去`、`史之`、`匈漠`、`屋活` 等删除行带来 15 处消失，
   净 +2。消失/新增的逐位点归类见 `results/attribute_perfect.json`。
3. **臂1 反而降了 9 字**：完美证据能过、真值图书馆过不了，说明**从"取回真值句子"到"判决放行"这一步
   仍受候选表词形和窗口长度牵制**（`仍启用` 消失 14 处里多数是目标词正确但被同窗别的候选压过）。

## 3. 结果：再换语料（`e044_full`，E036 训练侧 + E042 补充库 = 5,350 万汉字）

| 臂 | 改对 | 误改 | 错到错 | 总距离 | 只换词库时 | 增量 | 用时 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 新入口 + 检索 | **94** | 1 | 0 | **1,931** | 6 | **+88** | 2,014s |
| 新入口 无检索 | **94** | 1 | 0 | **1,931** | 6 | +88 | 61s |
| 臂1 真值图书馆+检索 | 278 | 1 | 0 | 1,747 | 162 | +116 | 91s |
| 臂2 完美证据不检索 | **319** | 2 | 0 | 1,707 | 214 | +105 | 83s |
| （对照）V1 默认 | 152 | 79 | 23 | 1,951 | — | — | 19s |

**① 补语料有效，但起作用的是通用 4-gram 底座，不是检索。**
有检索与无检索在**七篇上输出逐字相同、编辑集合 7/7 全等**；合并包里 D≠0 的窗口只有 **13/1,174（1.1%）**，
D≠0 的候选条目 223 条，却没有改变任何一个判决。所以 +88 全部来自"现代语料从 82 万字涨到 3,083 万字"
带来的语言模型改善，检索证据通路对这七篇的贡献仍然是 **精确 0**。

**② 与 V1 变成互补关系。** 新入口 94 个改对位点与 V1 的 152 个：交集 **48**，新入口独占 **46**，V1 独占 **104**
（E039 时是 10 与 145 交集 0）。若只做位点并集，上限可到 198 字，但两边误改口径差很多（1 vs 79），
合并策略必须另做对照实验，本轮没测。

**③ 上限仍然很高。** 完美证据 319、真值图书馆 278，而正常入口只有 94 ——
"证据取回来"和"证据够强"之间的差距就是检索机制本身，与 E040/E041 的结论一致。

逐视频（改对字）：

| 视频 | V1 | 新入口(full) | 真值图书馆 | 完美证据 |
|---|---:|---:|---:|---:|
| BV163xB6zEwF | 1 | 0 | 4 | 4 |
| BV18mxx64Es3 | 7 | 2 | 11 | 14 |
| BV19T4P6MEWp | 0 | 0 | 2 | 6 |
| BV1LBxq6AEVn | 4 | 2 | 2 | 2 |
| BV1sxxX64E4E | 7 | 0 | 12 | 21 |
| BV1uUak6pEdK（历史） | 133 | 90 | 247 | 272 |
| BV1XgxE6BEqn | 0 | 0 | 0 | 0 |

注意：现代四篇新入口几乎为 0（90 个改对全在历史那篇），说明补充库里的现代语料对
现代视频的错词仍未对上——与 E042 交付里"P0 现代词已覆盖、但现代视频的位点少且依赖词形"一致。

## 4. 复现

```powershell
$env:PYTHONUTF8='1'; $env:TEMP='D:\text_clean\build\test-temp2'; $env:TMP=$env:TEMP
python experiments/E044/scripts/merge_corpus.py
python tools/prepare_rag_package.py --source-db build/e036_corpus/corpus_train.sqlite --output build/e044_base --frontend build/e035/text_clean.exe
python tools/prepare_rag_package.py --source-db build/e044_corpus/corpus_merged_train.sqlite --output build/e044_full --frontend build/e035/text_clean.exe
python experiments/E044/scripts/run_arms.py --package build/e044_base --tag base --openbook-dir build/e044_openbook_base --arms v1,rag,rag_no_retrieval,openbook,perfect
python experiments/E044/scripts/run_arms.py --package build/e044_full --tag full --openbook-dir build/e044_openbook_full --arms rag,rag_no_retrieval,perfect,openbook
python experiments/E044/scripts/attribute_openbook.py
```

## 5. 边界

七篇全开卷，臂1/臂2 更是"把答案当证据"的上界测试，**任何数字都不是泛化成绩**；
`perfect`/`openbook` 产物含真值，只留本地；E042 补充库与合并库均在 `build/`，未进仓库；
`v1` 与 `rag` 用的是同一份定稿词库，可直接横比。
