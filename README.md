# text_clean

保守的中文 ASR 同音／近音纠错器，C++17，无服务依赖。保留四阶段流程：AC 精确动作 → 锁定保护 → 拼音倒排及声调距离候选评分 → 非重叠替换。候选仍由 `data/lexicon.txt` 定义；静态词频不会自动成为纠错目标。

```powershell
cmake -S . -B build-release -DCMAKE_BUILD_TYPE=Release
cmake --build build-release --config Release
ctest --test-dir build-release -C Release --output-on-failure
```

旧 CLI 和 `TextCleaner::clean(text)` 保持可用。CLI 另加载独立合法词汇集合 `data/dict.txt`（可用 `--vocabulary` 指定一词一行或 jieba 格式），部署时需要携带；缺失时明确报错，避免悄悄失去保护。默认数据为 `data/word_freq.txt`、`data/pinyin_dict.txt`、`data/lexicon.txt`、`data/word.txt`；可用既有参数指定文件。AC 中明确配置的别名替换及掩码仍是权威动作，不受动态评分限制。

## bili2md 调用

UTF-8 字幕通过 stdin 或 `--input-file` 输入；标题／简介只用于上下文，不混入输出：

```powershell
text_clean --title "微信使用教程" --description "介绍微信功能" --input-file subtitles.txt
```

长简介使用 `--description-file intro.txt`，标题可用 `--title-file title.txt`；文件参数优先于同名文本参数。元数据文件以 UTF-8 编码；读取失败返回 2。stdout 仅清洗结果（沿用旧 CLI 的末尾换行），诊断走 stderr，`-v` 显示静态频率、距离和 `context_bonus`。

Python 可直接引入本工程 `tools/bili2md_text_clean.py`：

```python
from bili2md_text_clean import clean_subtitles
cleaned = clean_subtitles(executable, title, description, raw_asr)
```

适配器用参数数组调用，无 shell；长元数据经临时文件传递，调用结束释放；失败抛出 `subprocess.CalledProcessError`。可执行文件依照原有规则查找 data。正式部署应将 data 放在可执行文件旁；Python 模块需加入 bili2md 的导入路径。本仓库未包含 bili2md 的上游工程，因此交付的是已验证的调用接口与适配器。

C++ 集成链接 `tc_pipeline`；加载字典、动作词表和静态词频后构造 `TextCleaner`，保留 `PinyinDict` 的生命周期长于 cleaner：

```cpp
// 构造 cleaner 时以最后一个参数传入 Vocabulary：
// Vocabulary vocabulary; vocabulary.load_file("data/dict.txt", &error);
// TextCleaner cleaner(std::move(lexicon), pinyin, config, ac_words,
//                     std::move(frequency), std::move(vocabulary));
auto context = cleaner.prepare_context(title, description, raw_asr);
for (const auto& cue : cues) {
    auto result = cleaner.clean(cue, context);
    // result.matches 的 begin/end 是该 cue 原文的 Unicode 码点偏移。
}
// 视频结束销毁 context；cleaner 和静态字典可跨视频复用。
```

`clean(text, context)` 不修改共享状态；同一个 cleaner 可使用不同的只读上下文。上下文不保存原始标题／字幕，不写入词库。

## 评分与安全边界

静态分数仍为 `log((1+fC)/(1+fO)) - lambda*distance - mu`。标题与简介中对规范候选的精确出现数合并为 m，ASR 中精确出现数为 a。仅对静态词频为零的原窗口附加：

`bonus = log(1 + min(m,2)/2) + log(1 + min(a,3)/12)`，且 m=0 时 bonus=0。

因此元数据最多将先验比值放大 2 倍，ASR 最多再放大 1.25 倍。ASR 单独重复不能提升目标，静态已知原词不接受动态加分。只统计动作词表中有拼音的 Replace 规范词；不从错误字幕发明新词，不提升 Mask/Keep 动作。空上下文等价于旧调用。

合法词汇集合只做完整候选跨度的 membership 保护：命中就跳过拼音改写，不改变分词、不抬高词频、不增加纠错目标。AC 明确动作仍优先；旧 C++ 构造函数可用，但调用者必须传入 Vocabulary 才有额外低频词保护。

候选索引新增按音节长度的倒排桶，在截断候选前过滤长度和首音节。输入侧保留全部多音字读音；候选侧必须遵守动作词表声明的词级拼音，只保留对应基音的声调读音，并将同一约束用于索引、距离及近音检查。例如“微信”的 `wei xin` 不允许扩展成 `wei shen`。词表填 `-` 时仍由字符首读音推导，多音词应显式填写正确词级拼音。保留旧 find_candidates API。流水线先检索候选，再按需解析声调／查词频；基音锚点前置过滤也使用全部读音。

等长候选现在使用逐音节替换距离（同基音同调0、不同调1、不同基音2），并保留逐位置拼音字母编辑距离≤1的近音硬限制。原有 Levenshtein 函数仍供其他调用方使用。

窗口由起点与有限长度唯一生成，边界由同一个左右对称许可函数检查：普通词界／未知区可用，至多跨4个 token；切入已知词只能借一个边缘字，另一侧为未知区时允许留下单字，否则剩余片段须能成词或与紧邻上下文重新成词。两端同时切入已知词继续禁止；边缘候选仍要求基音全部相同、只改一字、距离≤1。

所有通过评分的候选参与重叠连通组比较。最高分对次高分的优势必须大于已有修改阈值 mu，否则整组保留原文。不会因为更早开始就优先修改；完全同分的不同候选也不会由词表编号决定结果。

字符 N-gram 目前只有 `tools/ngram_veto.py` 离线实验，不加载到 C++ 流水线。它只评价已有的等长候选是否应被否决，不产生新候选或写回文本；支持不足时放弃判断。详见 `PRIORITY_IMPLEMENTATION.md`。

## 回归

`tests/test_video_context.cpp` 覆盖动态加分、ASR 污染、反向干扰、上下文隔离、白名单和局部边界；`tests/test_cli_context.py` 覆盖 Python 适配器、中文路径和失败返回（CMake 找到 Python 时注册）。现有 12 组测试保留，新增优先级回归和离线 N-gram 测试。

```powershell
python tools/refactor_benchmark.py .verify/refactor/baseline.exe log/refactor_baseline.json
python tools/refactor_benchmark.py build-gcc/text_clean.exe log/refactor_after.json
python tools/refactor_benchmark.py build-gcc/text_clean.exe log/refactor_context.json --context
```

本机基线可执行文件保存在 `.verify/refactor/baseline.exe`（不提交）；基线是本次开始时的工作区构建，不是 Git HEAD。基准脚本复用现有 `v2error_report.py` 的 27 条注入样例，固定两篇 ASR，保留语料／词典 SHA256、输出改写明细和计时样本。详见 `REFACTOR_REPORT.md`。
