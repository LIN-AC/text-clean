# E021：词库职责与判决流程重构

2026-11-07，HEAD `14aad4667c09587cd47eb64ea33b670da6a61668`＋既有未提交工作树。
**结构改造已落地，最终22项测试全部通过；尚无独立真值上的纠错收益证明，未发布。公式保持原样。**

## 授权和范围

园长批准按Astra提案顺序重构，明确暂不修改公式，并允许无候选表基线。本轮只额外获得一次正式数据修改授权：将 `candidates.tsv` 第254行的 `祥符xiang2fu2` 分为 `祥符<TAB>xiang2fu2`。其余正式词库及全部人工真值未变，校验见manifest。`data/PROVENANCE.tsv`未修改，候选表当前SHA以本实验manifest为准。

新候选表已有人工真值配对，不能把回测当独立泛化证据。领域词频列也含真值，当前加载器完全不导入该计数。无候选基线只读AC锁表，其余词库均不读、不使用。

## 实际修改

1. 新增 `DictionaryBundle`：按表头逐列读取新TSV，保留来源、状态、读音和频率单位，出错时不留下半份词库。停用行不进候选池；同一目标的多个已启用别名合并。允许无别名的目标行。
2. 实际新表为362行启用、668行停用、336个目标，1个目标缺少可用的完整带调读音，不进入拼音检索。与上轮1034行快照不同，不使用过时计数。普通词典/扩展词典不自动成为候选或AC锁；它们提供切词参考。
3. AC只有保持原字的权限，覆盖所有重叠命中位置。候选与别名没有AC直接改写权，Mask也不能进入拼音或执行通道。兼容旧数据格式不兼容其越权行为。
4. 保留原文始终是0分的可选结果，替换仍须通过原公式与竞争门槛。移除了“普通词典收录就直接否决候选”的特殊判断。没有新增词典加分、没有调λ/μ，也没有全局改变拼音距离。
5. 窗口允许跨锁区，只能改变未锁定字符；提交替换前再查一次。数字字符保护，换行不跨越。5/6字目标可检索；没有启用停用单字配对，也未实现增删字。
6. 词级读音按完整读音变体核对，不允许把两个词级变体的局部拼成不存在的第三种读音。近音限制与原声调距离保留。旧格式的未标调兼容行为仍在旧数据入口；新表不把unknown制造成可匹配读音。
7. 自动BIN缓存含格式版本、完整索引来源身份及负载校验；输入变化或损坏重建，写入失败不影响内存索引正确性。有无缓存输出一致。新TSV模式默认缓存位置为`data/generated/pinyin_index.bin`，本轮测试缓存写入实验目录，未改正式词库目录。
8. bili2md适配器新增可选`extra_args`，原四个位置参数不变。按一视频调用，原字幕换行保留，同一视频共享上下文。

## 新频率如何处理

新表通用频率为Zipf对数值，旧公式使用次数。本轮可读取其证据，但**不把它转换或塞进旧公式**。`sources=none`保留缺失状态；领域列完全不使用。默认启用候选又未显式指定次数表时明确报错，避免悄悄换公式或伪装成正常纠错。

可用入口：

```powershell
# 检查新数据；不纠错
build/current/text_clean.exe --check-data
# 无候选基线；原文保留
build/current/text_clean.exe --no-candidates --input-file subtitle.txt
# 仅供结构回放：新候选/新读音配合显式旧次数表；不代表独立质量验证
build/current/text_clean.exe --word-freq data/old/word_freq.txt --char-freq data/old/dict.txt --input-file subtitle.txt
# 旧数据格式兼容；保护和判决行为按新规则
build/current/text_clean.exe --legacy-data --input-file subtitle.txt
```

`--no-index-cache`禁止缓存，`--index-cache <path>`指定缓存。新TSV不支持旧的交互追加词库方式，避免把旧行格式写坏新表。

## 基线及测试结果

重构前构建成功；测试最初8/19通过。临时目录修正后12/19通过，剩余7项主要为词库迁移后仍引用旧根路径，含因失败后继续索引空结果导致的崩溃。旧二进制保留在`build/baseline/`。不能把修复路径产生的通过数当算法收益。

重构中间版本22项测试，**20通过、2失败**（原始记录保留）：

- 新加载器、停用隔离、格式/单位拒绝、数字/重叠锁、跨锁修复、别名不过评分不修改、Mask无权限、保留原文、完整读音变体、5/6字目标、缓存失效和CLI基线等检查通过。
- `test_video_context` 有10个失败断言，来自5条含“微星”的正确句子在2种误导上下文下被改成“微信”。
- `test_cli_context`在“我买了微星主板”这一正确文本上失败。正确文本期望没有被改成错误输出，没有将失败标为预期通过。
- 旧单测中“AC直接替换/屏蔽”“词典就是锁”“目标词自动加入AC”的断言按已批准新职责改写，明确的保护由测试显式给出。词边界测试将切词信息移入词典夹具，未通过频率大小隐式提供词典。CLI旧上下文夹具显式指定旧数据及关闭字符基线，独立保留其词典撤锁后的误改失败；不能与未适配旧CLI默认配置混为一个实验。

无候选基线：7份人工校对视频，排除原定3个discard后6710段、51865个原输入字符，旧版和新版输出都逐字节等于输入。改对0、误改0、原有错误全部漏改；不重新定义数字/编辑对齐指标，不把未改动的错误称为正确，不报告纠错召回提升。各文件SHA、cue计数、原样输出在`results/no_candidate_baseline.json`及逐视频文件。

## 性能与代价

同一机器、同一3,223,860字节输入，空输入启动5次取中位数、大文件3次取中位数；包含进程启动、加载和输出。

| 无候选配置 | 重构前 | 重构后 |
|---|---:|---:|
| 启动 | 271.0 ms | 15.8 ms |
| 大文件端到端速度 | 6.13 MB/s | 9.58 MB/s |

新版无候选路径不加载无用的大表，这是基线速度变化的原因，**不是启用纠错后的速度承诺**。初版误加载全部大表，启动约2.20秒，已修正；原始数据保留在`performance_initial.json`。

启用新候选和旧次数对照时，全量参考表读取仍约2.3–2.6秒；缓存没有显示稳定的端到端加速，加载大表占主导。一次Windows进程峰值工作集测量：无候选8,671,232字节，启用新候选349,405,184字节。不是持续运行内存或所有视频的上限。不要因此扩展成全量数据二进制化项目；先解决质量阻碍。

## 结论和未完成项

本轮完成了数据职责、权限、窗口及缓存结构的实现与检查。中间版本暴露“撤掉词典硬保护后，元数据加分推翻静态否决”的问题；随后修复判决准入：**原文被普通词典收录且静态评分≤0时，不允许仅靠标题/简介加分修改；静态评分>0时仍可修改。**原始分值仍按原公式计算，没有更改λ、μ、动态加分项，没有品牌特例或恢复无条件词典锁。

此条件属于已批准的原文参考证据与统一判决步骤；新增正反例证明它不是硬锁。最终 `tests_admission.txt` 为 **22/22通过**，原10个微星误改断言与CLI负例恢复通过；失败期间日志保留，正确文本期望没有改写。修复后重新跑无候选、缓存对齐和文件完整性校验。

因此不发布、不修改默认阈值。新通用/领域频率接入评分继续暂缓。没有新的独立真值，只有原样基线、结构测试及已见样本机械回放；未证明新版能降低总体误改或保留原召回。下一次重点是独立质量验证与新频率单位的评分接入；后者仍遵守园长“公式目前不动”的限制，不在本轮擅自实现。

## 复现

```powershell
$env:PATH='D:\msys64\mingw64\bin;'+$env:PATH
$env:PYTHONUTF8='1'
cmake -S . -B build/current -G 'MinGW Makefiles'
cmake --build build/current -j 4
New-Item -ItemType Directory -Force build/test-temp | Out-Null
$env:TEMP='D:\text_clean\build\test-temp'
$env:TMP=$env:TEMP
ctest --test-dir build/current --output-on-failure
python experiments/E021/scripts/validate.py
python experiments/E021/scripts/memory.py
```

最终`ctest`通过；`tests_first/second/third/final.txt`是过程记录，最终结论以`tests_admission.txt`为准。性能脚本需要本轮改动前保留的`build/baseline/text_clean.exe`；HEAD含旧工作树改动，不能用干净commit替代。本轮改前源文件SHA和git差异在`config/before.json`、`before.diff`；执行数据/二进制SHA、参数和授权变化在`results/manifest.json`。本实验未修改人工真值或正式评测指标。


## 修改文件清单

- 数据接口：`include/text_clean/dictionary_bundle.h`、`src/dictionary_bundle.cpp`（新增）。
- 运行流程：`include/text_clean/lexicon.h`、`include/text_clean/vocabulary.h`、`include/text_clean/text_cleaner.h`、`src/text_cleaner.cpp`、`src/main.cpp`。
- 缓存：`include/text_clean/pinyin_index.h`、`src/pinyin_index.cpp`。
- 构建与适配：`CMakeLists.txt`、`tools/bili2md_text_clean.py`。
- 新测试：`tests/test_dictionary_bundle.cpp`、`tests/test_decision_safety.cpp`、`tests/test_cli_bundle.py`。
- 契约及迁移测试调整：`tests/test_text_cleaner.cpp`、`tests/test_priority.cpp`、`tests/test_tone_correction.cpp`、`tests/test_cli_context.py`。
- 园长单独批准的一行数据修复：`data/correction/candidates.tsv`。
- 文档与记录：`README.md`追加开发状态、`agents/reports/Astra.md`追加本轮记录、新建当前`agents/status.md`和`agents/EXPERIMENTS.md`（历史未动）、`experiments/E021/`。

这些是本轮变动，git工作树里其他既有修改/删除不属于本轮，没有替园长恢复、提交或移动。
