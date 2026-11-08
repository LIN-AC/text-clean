# CSC 真值基准（CTCDataset 接入）

补上 `ALGORITHM_DEFECTS.md` §4.8 指出的缺口：本仓此前**没有任何带真值的纠错评测数据**——30 份 `whisper_txt` 无真值，3 份全对文本只能测误替换、测不了召回，全部结论建立在 4 个改写样本上。

## 1. 数据来源与筛选

上游 <https://github.com/zejunwang1/CTCDataset>（**仅限学术研究用途**，故 `datasets/` 已加入 .gitignore，不入库）。仓库全量 171 MB，只按需拉取拼音型拼写纠错子集 18 MB / 20 个文件：

| 取用 | 用途 |
|---|---|
| `sighan/sighan1{3,4,5}_{train,test}` | 真实读者举报的同音错字，同音占比最高 |
| `MCSCSet/{test,valid}` | 众包错字，量最大 |
| `cscd-ns/{test,dev}` | 母语者语料，news 域，视觉型错字极少 |
| `lemon/*` 七个域 | 真实用户输入错字 |
| `ECSpell/ec_{law,med,odw}` | 领域文本，作 train 侧词表来源 |

拉取方式：`curl` raw.githubusercontent.com 单文件（整仓 `git clone` 会拖进 171 MB 语法类数据，已放弃）。

统一 schema：`source`（错）/ `target`（对）/ `label`，等长句对。

## 2. 错字类型分布（`python tools/csc_eval.py stats`）

用 `data/pinyin_dict.txt` 的**全部**字读音给每个差异点分类：同调同母 = homophone、同母异调 = tone、母音编辑距离 ≤1 = near、其余 = visual。

| 指标 | 数值 |
|---|---|
| 句对总数 | 88,520（其中 41,328 句完全正确） |
| 金标准错字总数 | 71,790 |
| homophone / tone / near / visual | 39,216 / 16,247 / 6,972 / 8,877 |
| **拼音型占比** | **87.0%** |
| 全句差异均为拼音型的句对（asr_fit） | 39,028 |

87% 与 ASR 同音错的形态吻合，说明这批数据适合本仓；`sighan13_test` 同音占 76%、`cscd-ns` 视觉型仅 27/2,527。

## 3. held-out 设计

- `build-lex`：**只用 train 划分**（sighan13/14/15_train + MCSCSet/valid + ECSpell 三份）造词表——取每个错字位置周围 `word_freq.txt` 中存在的最长正确片段作规范词、错片段作别名，得 `datasets/ctc_probe_lexicon.txt`：**6,553 条规范词 / 14,320 别名**（2字 5,241、3字 1,018、4字 294）。
- `run`：只在 test 划分上打分，指标用 CSC 常规的字级 detection / correction 双套 P/R/F0.5，句级修复数为辅。句间以换行拼接，`\n` 为非汉字边界 → 逐句互不干扰，且不带标题/简介（即「空上下文等价旧行为」那条不变量）。

## 4. 基线数字

`python tools/csc_eval.py run [--lexicon datasets/ctc_probe_lexicon.txt]`

| 配置 | det_P | det_R | det_F0.5 | cor_P | cor_R | tp / fp / fn | 整句修好 |
|---|---|---|---|---|---|---|---|
| 出厂 lexicon（10 条） | 0.0890 | **0.0004** | 0.0003 | 0.0366 | 0.0002 | 17 / 174 / 38,200 | 4 / 27,115 |
| train 派生 6,553 条 | 0.0991 | **0.3150** | 0.0761 | 0.0407 | 0.0335 | 12,039 / **109,406** / 26,178 | 1,117 / 27,115 |

- 出厂配置：召回 0.0004，且 191 次改动里 174 次是错的——行为完全由词表规模决定，算法本身没有被触发。
- 放开词表后：召回升到 0.315，但**每 1 次正确检测伴随 9 次错误改写**（det_P 0.099）；27,115 句含金标准错的句子里整句修好仅 1,117 句，同时引入十万处错字。
- 关键拆分：train 派生词表已覆盖 **65.7%** 的金标准错字位置（另有 10.9% 落在 `word_freq` 有词但词表未学的片段上），而 det_R 仍只有 0.315、det_P 0.099 → **瓶颈在判决机制，不是覆盖度**。这把 `ALGORITHM_DEFECTS.md` 里原先只能靠 4 个样本推测的结论变成了可复现的量。

阈值扫描（`--only cscd-ns/test --limit 2000`，900 句含金标准错）：

| 参数 | det_P | det_R | fp | cor_F0.5 |
|---|---|---|---|---|
| μ=0.7（默认） | 0.0306 | 0.1830 | 5,678 | 0.0040 |
| μ=1.8 | 0.0313 | 0.1360 | 4,112 | 0.0044 |
| λ=1.2 μ=1.8 | 0.0326 | 0.1391 | 4,030 | 0.0050 |
| max-distance=1 | 0.0380 | 0.1186 | 2,940 | 0.0060 |
| max-distance=1 μ=1.8 | 0.0383 | 0.1084 | 2,660 | 0.0061 |

→ 精确率被钉死在 3–4%，任何 (λ, μ, 距离上限) 组合都只是**等比例砍掉召回与假阳**，fp 始终是 tp 的 25 倍。这实证否定了「调参可救」的路径，指向 `ALGORITHM_DEFECTS.md` 的 D4（`log_ratio` 无上界 + `fO=0` 即成候选）与 D3（多音字罕见读音）必须改证据模型本身。

## 5. 复现

```
# 一次性：按需拉取（见 §1 文件清单）
python tools/csc_eval.py stats
python tools/csc_eval.py build-lex
python tools/csc_eval.py run
python tools/csc_eval.py run --lexicon datasets/ctc_probe_lexicon.txt
python tools/csc_eval.py run --lexicon datasets/ctc_probe_lexicon.txt --only cscd-ns/test --limit 2000 --set "--max-distance 1 --mu 1.8"
```

`tools/csc_eval.py` 是唯一新增依赖（stdlib），二进制取 `build-probe/text_clean.exe`，回退 `build/Debug/text_clean.exe`。

## 6. 下一步能做什么

1. 任何算法改动现在都有 44k+ 句、2.2 万金标准错字可测，且 train/test 隔离；改进优先级（D2 别名权威化、D3 读音上下文化、D4 分数改造、D5 区间 DP）都能给出可证伪的数字。
2. 这批数据可反向造 ASR 型干扰：把 `target` 按拼音随机替换成同音字，即得「已知错误注入位置」的纯召回测试集，比现有一致的 web 错字更可控。
3. 上一轮的 token 概率 `p` 门控实验同样需要这批真值才能评估收益（`p` 与金标准错字的相关性可直接量化）。
