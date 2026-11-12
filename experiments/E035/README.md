# E035｜RAG＋字符 N-gram＋新判决入口：实现与开卷验收

2026-11-11，Astra。园长本轮批准引入新入口并反推交给Qwen的数据结构。**入口已经跑通；质量没有超过现行V1，RAG本轮没有测出额外收益，不切换默认。**

## 1. 实验身份与边界

- 基础Git：`72796cad1f5a7a2317b0bae79fbe335e79f7c153`，本轮源码改动尚未提交。实际执行源码SHA见`results/manifest.json`，不能仅凭基础commit复现实验。
- 正式词库、人工真值、园长备忘录和formula.md均未修改；脚本在运行前后核对所有正式TSV与七份真值的SHA。
- 输入：`asr/*.gt.jsonl`七篇，排除已有discard；沿用E024的E19唯一对齐与数字归一化实现，不给插删/歧义强造字符标签。6710有效cue、51865源字符、1921可归因替换错误。七份真值均参与过候选建库，**全部是开卷**，不是泛化测试。
- 资料：`build/e033_kb/kb.sqlite`，SHA256 `81fdefde59ec74a675e95f9c5cf31d4bd7c90bc824bb4f37716c64b4b05a76af`。新包只由公开资料和原有读音/候选/锁表派生，训练不读ASR真值。
- 候选表SHA `4b3485ca2a34d7a9cbcf577de9ed9fcbe160d127b2ae776529a6f9917515ad4f`。逐份数据、词库、源码、包清单哈希见manifest；包内清单另绑定四个运行文件及C++前端。
- 新前端SHA `c6ceee7463aad27a101ac34e9f49e40c147ac1a8bbd40eff5a8334766a5b7eb6`。参照`build/e025/text_clean.exe`与新构建默认V1对七篇逐字节相同。当前词库版本V1实测是145/83/25/1962；不能套用旧上下文表的145/82/25/1961。

## 2. 本轮实现

1. **C++只读候选出口**：`TextCleaner::evidence_candidates`及CLI `--candidate-export`，保留AC锁、数字保护、词窗和读音约束，导出字符偏移与目标。在旧词频评分之前退出，因此新判决不被旧评分预筛。V1旧入口行为不变。
2. **通用字符4-gram**：`tools/rag_clean.py`的Model。改良Kneser–Ney（按不同前驱统计低阶，并对罕见搭配降权）生成归一化概率；完整计数，共享字符表、句首/句末/未知字。`tools/prepare_rag_package.py`从完整句段训练，不从重叠检索块直接计数。
3. **资料检索**：SQLite倒排检索，无服务。全篇、标题/简介、局部上下文联合查询；遮住原窗口与目标词，同窗口所有竞争词共用证据。按文档簇封顶，同一转移在同簇出现多次只计一次。
4. **竞争与KEEP**：108967个普通读音词只参与竞争，允许修改的目标仍须通过C++出口。H保留P_mix前30及符合条件的AC热词；已算分尾部质量并入OTHER，不因截断虚增候选置信。成功窗口重叠则整组保留原文。
5. **可查原因**：日志记录候选、来源文档、G/D/S、KEEP/OTHER、未知字、缺读音、执行资格、最终保留原因。未校准包默认保持原文，只有显式`--research`允许工程初值产生改写。模型后验数值不称为真实正确率。

主要修改文件：`include/text_clean/text_cleaner.h`、`src/text_cleaner.cpp`、`src/main.cpp`、`CMakeLists.txt`、`tests/test_zipf_scoring.cpp`；新增`tools/rag_clean.py`、`tools/prepare_rag_package.py`、`tests/test_rag_clean.py`、本实验脚本及`docs/RAG_DATA_CONTRACT.md`。README新增入口说明。

## 3. 公式落地与验证

沿用formula.md第七节的方向，未改写原文档。给定同一检索集合E，h是最多3个前字，w是下一字：

```
n_E(h,w) = 含该转移的去重文档簇数
N_E(h)   = sum_w n_E(h,w)
P_mix(w|h,E) = [n_E(h,w) + kappa P_gen(w|h)] / [N_E(h) + kappa]
```

因为共同字符表上`sum_w P_gen=1`，所以分子之和恰为分母，P_mix归一；没有领域证据时恰好退回P_gen。N_E不是“含h的文档数”，一份文档可能提供多个后继，不能用后者作分母。

对原文O和等长目标C，把改动内部及其后最多3字的转移纳入；到真实句末则加EOS，未触及的前后项相消：

```
G = log P_gen(C上下文) - log P_gen(O上下文)
D = log P_mix(C上下文|E) - log P_mix(O上下文|E) - G
S_C = a_class + beta_class G + D
Z = 1 + sum_C exp(S_C) + rho
P(KEEP)=1/Z; P(C)=exp(S_C)/Z
```

所有竞争词共享E和Z；KEEP固定0分。OTHER含已评分尾部质量与未覆盖背景rho。实现用稳定的指数归一，避免溢出。当前初值a=0、β=1，因此S恰为混合概率的对数比；这里没有已估计的Whisper错误概率，也没有静态词频项。**这只是条件判决模型，尚未从有代表性的位置级标签估计a/β/rho，也没有证明0.99阈值对应1%误改风险。**

冻结参数：same/tone/near均`[a=0,beta=1]`，`kappa=10,rho=1,alpha=.01,top_h=30,retrieval_limit=50,calibrated=false`。新臂显式research；无检索臂只关闭检索，所有其余参数、候选选择、竞争、重叠处理相同。没有按七篇结果挑参数。标题/简介均不额外提供。

工程验证：**CTest 25/25通过，12.05秒**。其中Python套件10项，覆盖归一化、UNK/EOS、完整句差分等价、文档封顶和正确分母、共享竞争/KEEP、数值稳定、完整读音变体及未校准保护/显式研究入口。C++补查无词频也可导出候选与AC锁保护。日志在`build/e035/tests_final.txt`。

## 4. 七篇完整流程对照

| 方案 | 改对字 | 误改原正确字 | 错到错字 | 剩余原替换错误字 | 归一化总编辑距离↓ |
|---|---:|---:|---:|---:|---:|
| 不纠错 | 0 | 0 | 0 | 1921 | 2024 |
| 当前V1 | 145 | 83 | 25 | 1776 | 1962 |
| 新公式＋N-gram＋RAG（工程初值） | 8 | 0 | 0 | 1913 | 2016 |
| 新公式＋N-gram，无检索 | 8 | 0 | 0 | 1913 | 2016 |

新入口仅3次编辑、8字改对，全部在历史视频BV1uUak6pEdK；其余六篇0次改写。改对字只保留V1的5.52%，总错误比V1多54，比不纠错少8。**0误改主要伴随大量弃权，不能说已经解决误改问题。**无检索与检索臂逐视频计数一致；额外脚本`verify_ablation.py`核对输出全文，而非仅看总数（结果见`ablation_equality.json`）。

逐视频计数和耗时见`results/results.json`，汇总`summary.json`。完整候选和证据跟踪`*.trace.json`包含原始ASR片段，作为本地私有实验产物保存，不应随公共仓库发布。

## 5. 数据反推与成本

派生包：89069个去重文档、116430个完整汉字句段；移除1121份完全重复文档。通用模型训练112941个现代句段、909846汉字；字符表3483项（包含UNK/EOS）。实际折扣无退回阶；抽查32历史条件及边界的最大概率质量误差`2.44e-15`，不是对全部历史条件逐个穷举。

- 启用目标340个，全部有完整读音，但只有304个所有字在通用字符表内，36个缺字；不能用“读音齐了”代替“可评分”。
- 1176个候选窗口中，26个原文含未知字，147个至少一个目标含未知字，290个H中没有可执行目标，28个H为空；这些分类相互重叠，不可相加当漏改数。参见`diagnostics.json`、`coverage.json`。
- 所有窗口均检索到了资料，但开关检索结果不变，说明“检索非空”不是有效证据指标。尚未区分检索不相关、具体转移缺失、通用模型不足及未校准阈值各占多少，不能全归罪于词库。
- 新包四个文件约226MB：资料库196526080字节、模型20829622字节、竞争词8788303字节、参数362字节。
- 七篇累计：RAG新入口144.02秒，无检索22.55秒，V1 18.89秒；新包一次加载另需2.42秒。这里V1每视频包含加载，Python新入口复用模型但仍每视频启动C++，不是等加载条件的纯核心吞吐对比。检索路径明显慢，未达到原项目高吞吐目标。

交给Qwen的准确结构、字段、验收与顺序见`docs/RAG_DATA_CONTRACT.md`。优先补资料身份/真实句界/去重簇，再补来源可查的现代通用表达与完整读音竞争词；不能只按这36个目标补答案。保持来源分组留出，检验新包对原文与目标两侧都公平。资料采样和留出不使用ASR真值。

## 6. 复现

在项目根；首次建立构建及样品包（输出包必须是新目录，不覆盖已冻结包）：

```powershell
$env:PATH='D:\msys64\mingw64\bin;'+$env:PATH
$env:PYTHONUTF8='1'
$env:TEMP='D:\text_clean\build\test-temp'
$env:TMP=$env:TEMP
New-Item -ItemType Directory -Force $env:TEMP | Out-Null
cmake -S . -B build/e035 -G 'MinGW Makefiles'
cmake --build build/e035 -j4
ctest --test-dir build/e035 --output-on-failure
python tools/prepare_rag_package.py --source-db build/e033_kb/kb.sqlite --output build/e035_package --frontend build/e035/text_clean.exe
python experiments/E035/scripts/evaluate.py
python experiments/E035/scripts/diagnose.py
python experiments/E035/scripts/verify_ablation.py
```

本机已有冻结包时跳过构建包一行；异机重编译二进制哈希不同，应在隔离副本构建新包和重跑，不改旧manifest绕过校验。E025参照二进制、E033原始库及私有真值须具备；缺失时不能声称复现。源码、测试等新增文件的补充快照见`results/artifact_manifest.json`。

## 7. 未解决与下一步

现有前端仍保留距离≤2、边缘窗规则和候选上限64，不能将到不了出口的错误归于新评分；竞争词扩充也不会自动赋予替换资格。旧加载器仍读频率文件，暂不能删除。

后续唯一优先实验：在来源留出且原文可回查的新资料包上，**固定这轮候选和初值**，重跑有/无检索对照并逐项记录正确目标可评分率、支持转移的文档来源、TP/FP/错到错、漏改与耗时。先确认资料带来独立判别力，再讨论校准和性能重构。若检索仍无增益或误改增加，停止扩大检索体量，定位证据质量；不能用这七篇开卷调到最好后称泛化。

未执行：默认替换、Whisper p门槛、全局删除拼音约束、自动启用普通词、把未校对文本作负例、真值修订、Git提交或推送。
