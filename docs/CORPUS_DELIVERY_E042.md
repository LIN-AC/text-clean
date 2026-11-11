# E042｜RAG 语料补充交付（Qwen）

2026-11-12，Qwen。按 [docs/RAG_CORPUS_REQUEST.md](../../docs/RAG_CORPUS_REQUEST.md) 与
[docs/RAG_CORPUS_TARGETS.tsv](../../docs/RAG_CORPUS_TARGETS.tsv) 交付，字段口径见
[docs/RAG_DATA_CONTRACT.md](../../docs/RAG_DATA_CONTRACT.md)。
**本轮只新增语料与新目录，未改生产代码、正式词库、人工真值、评分规则、默认参数，未覆盖 build/e036_corpus、build/e038_\*。**

## 一、一句话结论

规模够了，逐词验收没全过：**现代 3,000.7 万字 / 11 个来源组，历史 1,699.9 万字 / 11 个新书来源组，
合计 47,006,004 汉字、162,170 篇、7,188,455 段，泄漏复查 0 命中**。
但 `docs/RAG_CORPUS_TARGETS.tsv` 的 P1 历史 14 词只做到 **2/14**（要求 ≥12/14），P0 现代 6 词做到 **4/6**。
原因不是"再抓一点就够"，而是**其中 9 个词的目标词形在史料里根本不用**（详见第四节）。

> 修订记录：本批次先交 22,536 篇（无口语档），随后补进 AISHELL-1 朗读转写（+141,180 篇）并加了一道
> **建库期撞窗剔除**：AISHELL 有 2 篇与本项目旁白撞上同一个 12 字通用句式
> 「已经到了非解决不可的地步」，按需求文档"命中必须为 0"整篇剔除，逐条留痕见 `leak_dropped.tsv`。
> 这是巧合不是抄答案，但没有放宽验收线。

## 二、交付物

```
build/e042_corpus/
  corpus_supplement.sqlite   162,170 docs / 7,188,455 segs / 1,576MB
                             SHA256 f06939e39a7051a6…（全量见 manifest.json）
  coverage_report.tsv        40 个目标词逐词一行（自动化子串口径，与 E041 可比）
  coverage_report.detail.json 每词的来源组与最多 6 条公开上下文
  coverage_manual_review.tsv  人工抽查判定：自动数 vs 真用法 vs 不可覆盖原因
  coverage_samples_for_review.tsv 409 条待复核上下文（含词边界启发式标记）
  source_list.tsv            21 个来源组的 URL/许可/SHA/字数/占比
  hard_checks.json           硬性检查结果
  leak_dropped.tsv           建库期撞窗剔除的文档（2 篇，含出处 URL 与命中窗口）
  samples_naturalness.tsv    随机 40 条自然句抽查
  manifest.json              绑定上述文件与原始 dump 的 SHA256
  build_report.json          封顶值、每组可用/选用字数
  jsonl/ dump 与抓取的中间产物（一个文档一行，含 raw 原文）
  raw/ raw_ws/               原始 dump 与逐页 wikitext 缓存
```

规模与构成（汉字数＝`text_norm` 去掉规范化空格后的长度，含扩展区汉字；`norm_len` 另给含空格总长）：

| 域 | 文档 | 汉字数 | 规范化总长 | 来源组 | 最大单组占比 | 封顶值（汉字/组） |
|---|---:|---:|---:|---:|---:|---:|
| 现代 | 160,039 | 30,007,230 | 39,943,957 | 11 | 11.4% | 3,431,230 |
| 历史 | 2,131 | 16,998,774 | 20,764,513 | 11 | 21.6% | 3,664,277 |
| 合计 | 162,170 | 47,006,004 | 60,708,470 | 22 | — | — |

现代域文档数大是因为 AISHELL 转写按"一条录音＝一个文档"入库（141,180 篇，平均 14.4 字），
整文重复的 7,903 篇已并入同一 `cluster_id`，不会虚增独立文档数。

现代来源组：中文维基新闻/教科书/大学/导游/语录/维基百科（CC BY-SA 4.0，逐条留页面 URL＋修订时间戳＋wikitext SHA）＋
中国政府网政策文件库＋北京市政策文件库＋上海市信息公开文件（地方行政规范性文件，著作权法第五条不适用著作权）＋
**AISHELL-1 人工转写**（Apache-2.0，官方卡片另注明"free for academic use"；400 人照稿朗读、转写准确率 >95%，
2,038,408 汉字 / 141,180 条（另有 2 篇撞窗剔除，见 `leak_dropped.tsv`），register=`口语朗读（照稿）`；原始文件 SHA256 前缀 `b5f33b9e0b47`）＋
维基文库《朝花夕拾》（公有领域白话，仅 2 篇 5,777 字，聊胜于无）。

历史新增 11 部书（全部公有领域，逐页留 URL＋修订时间戳＋SHA）：
資治通鑑 295 卷、宋史 457、清史稿 414、通典 201、元史 212、文獻通考 164、晉書 131、金史 135、
續資治通鑑長編 94、宋會要輯稿 18、鹽鐵論 10。按园长批准的"书名不同即独立来源组"计；
**这 11 组同属 zh.wikisource.org 一个网站**，按网站算是 1 组，请勿混用两种口径。

## 三、硬性检查（experiments/E042/scripts/check_supplement.py，独立复算，不调用建库函数）

| 项目 | 结果 |
|---|---|
| SQLite integrity_check | ok |
| 规范化独立复算不一致 / 长度不保持 | 0 / 0 |
| 位置映射（map 与 text_norm 等长且为恒等） | 0 处不符 |
| segs 能否由全文＋Unicode 偏移复原（抽 4,000 篇逐段） | 0 处不符 |
| 泄漏：七篇真值与原始 ASR 的 12 字窗口 **3,232 个**（其中 2,949 个不含空格可实际比对） | **0 命中**（建库期剔除 2 篇撞窗，见 `leak_dropped.tsv`） |
| 与 E036 老库的跨批完全重复 | 0 |
| 本批内整文相同 | 7,710 篇（AISHELL 短句跨说话人重复为主，已并入同一 cluster；其余为公文/条目转载） |
| 边界类别与 is_stop 冲突 | 0 |
| 许可缺失 / URL 不可追（首页代替具体出处） / src_sha 缺失 | 0 / 0 / 0 |
| 单来源最大占比 | 7.8%（限 30%） |

未使用的输入：`asr/`、`temp_txt/`、`clean_txt/`、`whisper-test/`、人工真值、本项目字幕——
只在**事后复查**里用作 12 字窗口比对，没有用来选句或造句。没有 LLM 生成句、没有模板句、没有词典释义或词表。

## 四、逐词验收结果与未达原因

自动口径（`coverage_report.tsv`，与 E041 的"文档含精确子串"一致）：OK 26 / BELOW_MIN 6 / MISSING 8。

| 组 | 要求 | 结果 |
|---|---|---|
| P0 现代 6 词 | 6/6 达标 | **4/6**：政务 488 篇/9 组、返乡 60/8、配齐 58/4、错时 27/6 达标；`段首` 8 篇且抽查仅 1 条真用法；`做到严而有度` 0 |
| P1 历史 14 词 | ≥12/14 | **2/14**：桑弘羊 42 篇/9 组、节流 10 篇/4 组（跨词假命中待复核）；其余 12 词未达 |
| P2-context 4 词 | 4/4 | **4/4**：田亩 81、政治 2,370、民变 25、青苗 32 |
| P2-low 5 词 | 5/5 | **5/5**：青黄 24、南伐 97、句丽 28、对峙 10、最称 10 |
| P3 11 词 | 不下降 | **11/11**：兼并 87、豪强 110、盐铁 181、八部 51、前代 348、后世 450、将有 277、明亡 49、江南 705、进士 709、仁政 52 |

**未达的 12 个 P1 词分成三类，都不是"再抓点史料"能解决的**（证据在 `coverage_manual_review.tsv`）：

1. **现代词被标成"历史域"（9 个）**：`富裕 0/204`、`前线 0/171`、`起价 0/22`、`账册 0/4`、`税基 0/4`、
   `衣冠南渡 0/4`、`纸币 4/54`、`跨地 1/86`、`清账 0/0`——左边是历史域命中，右边是现代域命中。
   史料用的是另一套词形：交子 34 / 会子 52 / 阵前 22 / 南渡 257 / 册籍 19 / 税源 / 抬价 / 对账 / 结清。
   历史视频的旁白说的是现代汉语，取证域应该允许现代语料，否则永远补不满。
2. **切分片段，不是自然词（2 个）**：`会要辑` 13 篇全部落在书名《宋会要辑稿》内部；
   `跨地` 现代命中几乎全是「跨地区/跨地域」的接缝；`鹿皮币` 的真实词形是「白鹿皮币」。
3. **同义改写而非精确子串（1 个）**：`祥符决口` 只有《清史稿》1 篇逐字真用法，
   但 祥符 383 篇、河决 357 篇、决口 83 篇都在，宋代史料写法是年号＋河决/坏堤。

`做到严而有度`、`清账` 已按文档要求标 **BLOCKED**，未造模板句；公文惯用语「宽严相济」有 7 篇可作替代语境参考。

**另一个必须提醒的事**：自动"文档含子串"口径会产生跨词假命中，例：`段首`←"在高**阶段首**先应该掌握"、
`节流`←"慢易以犯**节流**湎以忘本"、`起价`←"付得**起价**码"、`前线`←"当**前线**程"。
我加了词表启发式标记（`coverage_samples_for_review.tsv` 的 `aligned_heuristic`），但**启发式不能定案**：
"政务服务"里 政务/事务 是合法重叠会被误杀，"犯节／流湎"又判不出来。所以最终判定走人工抽查，
`节流`、`最称`、`将有` 这几个名义达标的词请 DeepSeek 在重建包内复核后再当证据。

## 五、已知限制

1. **口语档只补上"照稿朗读"，自发言谈与社媒仍缺**：
   - 已入库：AISHELL-1 转写（Apache-2.0，203.8 万字，14.4 字/条短句，只能算朗读体）。
   - 未入库：Common Voice 25 zh-TW（CC0，匿名可下，但单文件 131–444MB 且含音频列，未获园长点头前没拉）；
   - **WenetSpeech 拿不到**：OpenDataLab 页面明写"本站暂不提供直接下载，如需下载请至数据集官网"，
     官网要求填 Google 表单→查收邮件→按说明下载（音频包加密，需 解压码）。许可 CC BY 4.0 且仅限非商用，
     音频版权归原视频方。所以这不是我能绕的，也不是"下载下来就能用"。
   - 有一条**灰色捷径**：非 gated 的第三方仓库 `yuekai/wenetspeech_paraformer_fixed_transcript`
     有个 928.5MB 的 `text.fix`，匿名可下（实测 206），但**该仓库未声明许可**。按"拿不准许可的先报"，没入库。
2. **维基百科只解析到 11,859 篇 / 1,403 万字**：全量 dump 3.45GB，按 sha256(标题) 每 40 篇取 1 篇抽样，
   为冻结输入提前停止解析（dump 的 SHA256 已登记，重跑可续）。
3. **`朝花夕拾` 只有 2 篇 5,777 字**：维基文库上鲁迅《呐喊》《彷徨》《野草》《背影》等没有分卷子页，
   抓取只回主页面，正文为空 → 该组实际不起作用，已在 source_list 里保留真实数字没有隐藏。
4. **文档簇只在本批内部去重**，与 E036 老库只做了"整文 SHA 相同"的跨批检查（结果 0）；
   近重复跨批未做（清史稿/明史、資治通鑑/史記集解 这类共享底子的书，重建包时可能仍留两份近似文本）。
5. **规模按封顶抽样**：现代每组上限 385 万字，历史 366 万字，因此"可用而未用"的汉字有 1,761 万
   （build_report.json 的 family_avail_chars − family_used_chars）。抽样规则是 sha256(标题|URL) 升序累加，与目标词无关。

## 六、复现

```powershell
$env:PYTHONUTF8='1'
$env:https_proxy='http://127.0.0.1:7897'   # 直连 Wikimedia 只有 ~14KB/s，走代理实测 ~1.9MB/s

python experiments/E042/scripts/fetch_gov.py index              # 政务清单 19,045 篇
python experiments/E042/scripts/fetch_gov.py fetch --target 2400
python experiments/E042/scripts/fetch_beijing.py --target 700
python experiments/E042/scripts/fetch_shanghai.py --target 700
python experiments/E042/scripts/fetch_ws.py probe               # 维基文库书目可用性
python experiments/E042/scripts/fetch_ws.py fetch --work 資治通鑑   # 11 部书逐个跑
python experiments/E042/scripts/fetch_ws.py clean --work 資治通鑑
python experiments/E042/scripts/parse_batch.py                  # Wikimedia dump → jsonl
python experiments/E042/scripts/build_supplement.py --budget-modern 30000000 --budget-history 17000000
python experiments/E042/scripts/check_supplement.py
python experiments/E042/scripts/coverage.py --with-old --db build/e042_corpus/corpus_supplement.sqlite `
  --out build/e042_corpus/coverage_report.tsv
python experiments/E042/scripts/spot_check.py --per-word 12
python experiments/E042/scripts/emit_delivery.py
```

基础 Git `72796cad1f5a7a2317b0bae79fbe335e79f7c153`；本轮脚本尚未提交，复现需带上新目录
`experiments/E042/`。输入 dump 与逐页缓存的 SHA 见 `dump_manifest.json`、`raw_ws/`。

## 七、交给 DeepSeek 的点

1. 用 `corpus_supplement.sqlite` + `build/e036_corpus/corpus_train.sqlite` 重建新包（新目录，别覆盖 e038 包），
   在 E041 同一批 116 位点上重跑：目标词召回、目标 vs 错误候选文档差分。
2. **先分开两件事**：本轮补的是"现代公共事务书面语 + 11 部新史料"。E041 统计里 69 个"同领域查无"中，
   落在上面第 1、2、3 类原因的那些，**不会因为补语料而消失**，需要改取证域或改词形匹配。
3. 历史侧注意留出边界：老库《漢書》《史記集解》《後漢書補逸》《明史紀事本末》《漢書顏師古註》整部在留出侧，
   训练包统计里它们永远是 0；本轮新增的 11 部书全部在训练侧，未与留出集相交。
4. `节流`、`最称`、`将有`、`段首` 这类跨词假命中，重建包后请再抽查一次，别直接当"证据已覆盖"。
