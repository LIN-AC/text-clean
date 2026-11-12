# E042｜RAG 语料补充交付（Qwen）

本目录是 Qwen 本轮语料采集/建库脚本与来源记录；语料本体在 `build/e042_corpus/`，说明见该目录的 `README.md`、`manifest.json`、`coverage_report.tsv`。

Deepseek 同日曾把“完全开卷：真值图书馆与完美证据”也编为 E042，造成编号冲突；该实验已整体移到 [E046](../E046/README.md)，旧 E042 开卷结果只保留历史编号，不再在本目录维护。Qwen 的 E042 语料脚本、E044 复跑脚本引用的 `build/e042_corpus/` 都不受影响。

编号说明：
- 语料交付：`build/e042_corpus/`（Qwen，本目录脚本）
- Deepseek 完全开卷：`experiments/E046/`
- Deepseek 语料覆盖审计：`experiments/E047/`
- Qwen 候选表复核：`experiments/E043/`
