# P0–P3 优化交付记录

2026-11-02；基于上一轮实际工作区继续修改，未覆盖既有未提交工作。基线可执行文件保留于 `.verify/priority/baseline.exe`。本轮初始 CTest 14/14，完成后 **16/16**。四段式处理架构保留，无线上 N-gram、服务或大模型依赖。

## 按优先级完成内容

| 优先级 | 实现 | 验证 |
|---|---|---|
| P0 合法词保护 | 新增 Vocabulary，独立加载合法词集合；完整原候选跨度命中后禁止拼音改写。与静态词频、分词和 AC 动作分离 | 微星主板/显卡等不再受微信元数据误导；人名、术语的针对性高频候选攻击也保持原文 |
| P0 负例 | 18 条品牌、人名、术语与边界正确句，分别空、无关、误导、重复元数据；增加4组确实会被高频同音候选改写的保护测试 | 72 个句子与上下文组合，旧版10个误改，新版0个 |
| P1 延迟计算 | 先按多读音首音节锚点过滤和检索候选，非空才解析声调、查询统计频率 | 旧测试保持通过，整进程大文本性能实测提升 |
| P1 候选索引 | 新增长度分桶、逐位置多音读音候选接口，在截断前应用长度及首音节限制；保留原查询API | 100个错长度候选不会挤掉 limit=1 的正确候选；首读音不同、第二读音相同的“行芒→航芒”可召回；重建与零上限验证 |
| P2 窗口 | `(begin,length)` 唯一生成，统一左右对称的局部边界许可函数；不再累加多类窗口后 sort/unique | 两侧借字、双侧已知词切入禁止、支付保证金与谈话句回归 |
| P2 距离 | 流水线改用等长逐音节替换成本，保留基音近似硬限制；原 Levenshtein API 保留 | 甲乙/乙甲的编辑距离2与对应距离4明确区分；截断返回验证；既有声调/近音测试通过 |
| P2 冲突 | 保留所有通过评分的候选，按重叠连通组比较；最高分须比次高分多出既有 mu，否则整组保留原文 | 同分同跨度不受词表顺序影响；相近重叠候选放弃；更强的较晚候选可胜出 |
| P3 N-gram | 新增离线字符 trigram/bigram 边界否决实验；支持不足不判断，拒绝等长范围外输入及完整评测句泄露 | 人工构造独立句子中否决1个误候选、保留1个正候选；新闻训练语料对这两项无覆盖，均放弃判断 |

P3 **没有接入线上决策**。人工小样只验证机制，不能当作领域模型有效性的统计证据；现有新闻语料不足以支持上线。工具只输出评分与 veto，不生成候选、不改写文本。

## 同批数据对比

| 指标 | 本轮基线 | 新版 |
|---|---:|---:|
| 新增正确句×上下文负例 | 10/72 误改 | 0/72 误改 |
| 两篇正确文本（18,917码点） | 0处误改 | 0处误改 |
| 两篇固定真实 ASR | 0处改写 | 0处改写 |
| 既有可覆盖目标召回，无上下文 | 17/24（70.83%） | 17/24（70.83%） |
| 同批目标召回，合成上下文 | 18/24（75%） | 17/24（70.83%） |
| 全部27个目标，无上下文 | 17/27 | 17/27 |
| 测试组 | 14/14 | 16/16 |

合成上下文下少改的一例是“微言”：它在完整合法词库中存在，现在保守保护。注入样例可以把它指定为错误，但不能据此取消真实合法词保护。旧样例仍沿用原有统计口径，其中 Mask 执行也算目标命中；因此这不是严格的纯纠错召回率。两篇 ASR 没有完整人工金标，未声称真实 ASR 召回提升。

## 性能与代价

同一 MinGW GCC Release、同一 2,227,480 字节文本，独立进程5次中位数；空输入启动15次中位数。包含字典载入和标准输入输出开销。此次所有改动的整体对比，不能把提升全部归因于某一项优化。

| 指标 | 基线 | 新版无上下文 | 新版有上下文 |
|---|---:|---:|---:|
| 吞吐 MB/s | 2.310 | 3.018 | 2.904 |
| 大文本 ms | 964.4 | 738.1 | 767.0 |
| 整进程启动 ms | 76.9 | 210.9 | 203.9 |

无上下文吞吐增加约 30.7%，但启动显著变慢：CLI 现在需要加载完整合法词汇集合，优先保证词汇保护。应用应跨字幕复用一个 cleaner，按视频释放上下文；逐句启动 CLI 不合适。本轮未测峰值 RSS，不能宣称内存优化；完整词集合会占用额外内存。

## 接口与兼容性

- CLI 新增 `--vocabulary <path>`，默认 `data/dict.txt`；支持一词一行或 jieba 的词/频次/词性格式，只读取词。仅收录至少两个汉字的词，不把频次加入评分。
- 部署必须同时携带合法词汇文件；找不到时返回2，避免无声降级。旧部署若只复制原来的四份数据，需要补充该文件或显式提供路径。
- C++ `TextCleaner` 构造函数新增最后一个可选 `Vocabulary` 参数。旧代码仍可编译，但需传入词汇集合才能获得额外低频词保护。
- 已明确配置的 AC 替换／Mask 动作仍优先于拼音层的合法词保护。若主动把“威信”等合法词配置为强制别名替换，调用方应承担该精确规则的含义；本轮没有改写既有 AC 策略。
- 原有 `PinyinInvertedIndex::find_candidates`、`PinyinDict::toned_distance` 保持可用；流水线改用新接口。
- 重叠分差复用 `modification_threshold`，没有新增调参项。连通冲突组中即使存在多个可兼容子组合，本版也只选一个显著占优者或放弃整组，避免为召回引入全局搜索。

## 修改文件

- `include/text_clean/vocabulary.h`、`src/vocabulary.cpp`：新增独立词汇集合。
- `include/text_clean/pinyin_index.h`、`src/pinyin_index.cpp`：长度桶、位置与多读音检索。
- `include/text_clean/pinyin_dict.h`、`src/pinyin_dict.cpp`：新增对应距离。
- `include/text_clean/text_cleaner.h`、`src/text_cleaner.cpp`：保护、检索顺序、统一窗口及保守冲突选择。
- `src/main.cpp`：合法词汇文件接口。
- `tests/test_video_context.cpp`、`tests/test_cli_context.py`：修正歧义正例，增加上下文误导负例。
- `tests/test_priority.cpp`：新增词汇、索引、多音字、距离、边界与冲突针对性回归。
- `tools/ngram_veto.py`、`tests/test_ngram_veto.py`：新增离线模型与机制测试。
- `tools/refactor_benchmark.py`：记录合法词汇文件SHA256。
- `CMakeLists.txt`、`README.md`、本报告：构建与使用文档。

## 复现与证据

```powershell
cmake --build build-gcc -j 4
ctest --test-dir build-gcc --output-on-failure
python tools/refactor_benchmark.py .verify/priority/baseline.exe log/priority_baseline.json
python tools/refactor_benchmark.py build-gcc/text_clean.exe log/priority_after.json
python tools/refactor_benchmark.py build-gcc/text_clean.exe log/priority_context.json --context
python tools/ngram_veto.py --train independent_train.txt --cases candidates.jsonl --output report.json
```

N-gram cases 为 JSONL，每行包含 `text, begin, end, replacement, valid`；begin/end 是码点位置，valid 是人工标注候选是否正确的布尔值。默认实验固定回退/支持规则，仅统计跨候选边界的局部2/3-gram，至少两个有支持的局部项且负分超过阈值才否决。完整训练/评测句相同会报错，但近重复仍需人工排查。

原始数据：`log/priority_baseline.json`、`priority_baseline_context.json`、`priority_after.json`、`priority_context.json`、`priority_negatives.json`、`priority_ngram_synthetic.json`、`priority_ngram_news.json`。合成N-gram输入位于 `.verify/priority/ngram_train.txt`、`ngram_cases.jsonl`。这些本地实验文件按原有 gitignore 保留，不修改原始语料。

## 保留问题

- 合法词集合并非人工逐词审定，低频噪声可能阻碍召回；目前保护完整原窗口，不锁定所有包含该窗口的长词。
- 静态同音合法词之间的真实错误会更容易漏改，这是本轮明确选择。
- 多音字全部读音降低检索漏召回，也可能扩大候选集合；仍依赖近音限制、词汇保护和分差放弃。
- 新边界许可是对称局部启发式，不是语义证明。负例有限，零误改仅适用于此次样本。
- 默认完整词汇集合的启动及内存成本仍待后续压缩／持久加载优化。
- N-gram 缺乏独立领域语料，尚未上线；未新增或替换静态词库。
- 仅验证本机 GCC Release，未扩展到 MSVC/Linux 或峰值内存验收。
