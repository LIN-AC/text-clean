import collections
import json
import pathlib
import platform
import subprocess
import sys

ROOT=pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'experiments/E024/scripts'))
from rag_clean import sha
from align_lib import align


def main():
    out=ROOT/'experiments/E053/results'
    d=json.loads((out/'seven.json').read_text('utf8'))
    verification=json.loads((out/'verification.json').read_text('utf8'))
    supplement=json.loads((out/'supplement.json').read_text('utf8'))
    assert len(d['results'])==7
    totals={}
    for arm in ('ngram','rag','rag_proposals'):
        counts=collections.Counter();values=collections.Counter()
        for per_video in d['results'].values():
            row=per_video[arm];counts.update(row['counts'])
            values.update({k:row[k] for k in ['distance','remaining_original_errors','seconds',
                'candidate_reachable_errors','candidate_count','rag_only_candidates','nonzero_D']})
        totals[arm]=dict(counts=dict(counts),**dict(values))
    ctc={}
    for arm in ('ngram','rag'):
        counts=collections.Counter();distance=remaining=0
        for row in supplement['results'].values():
            counts.update(row[arm]['score']['counts']);distance+=row[arm]['score']['distance']
            remaining+=row[arm]['score']['remaining_original_errors']
        ctc[arm]=dict(counts=dict(counts),distance=distance,remaining=remaining)
    data_unchanged=all(sha(ROOT/name)==digest for name,digest in d['data'].items())
    def source_preserved(name,digest):
        if sha(ROOT/name)==digest:return True
        return name.replace('\\','/')=='tools/proposal_clean.py' and sha(ROOT/'experiments/E053/frozen/proposal_clean_measured.py')==digest
    source_unchanged=all(source_preserved(name,digest) for name,digest in d['source'].items())
    assert data_unchanged and source_unchanged
    correct_chars=error_chars=0
    for name in d['data']:
        for line in (ROOT/name).read_text('utf8').splitlines():
            if not line.strip():continue
            row=json.loads(line)
            if row.get('discard'):continue
            labels,_=align(row['text'],row['gt'])
            correct_chars+=sum(row['text'][i]==v for i,v in labels.items())
            error_chars+=sum(row['text'][i]!=v for i,v in labels.items())
    code_files=['CMakeLists.txt','include/text_clean/retrieval.h','src/retrieval.cpp','src/retrieval_main.cpp',
                'tools/proposal_clean.py','tools/native_retrieval.py','tests/test_proposal_clean.py']
    report=dict(commit=d['commit'],branch=d['branch'],totals=totals,ctc=ctc,
        truth_unchanged=data_unchanged,measured_source_preserved=source_unchanged,
        aligned_correct_characters=correct_chars,aligned_substitution_errors=error_chars,
        python=platform.python_version(),code_sha256={f:sha(ROOT/f) for f in code_files},
        script_sha256={str(f.relative_to(ROOT)):sha(f) for f in (ROOT/'experiments/E053/scripts').glob('*.py')})
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    labels={'ngram':'N-gram 提议，D=0','rag_proposals':'N-gram＋RAG 提议，D=0','rag':'N-gram＋RAG 提议，G＋D 判决'}
    lines=[]
    for arm in ('ngram','rag_proposals','rag'):
        r=totals[arm];c=r['counts']
        lines.append(f"| {labels[arm]} | {c['TP']} | {c['FP']} | {c['wrong']} | {r['remaining_original_errors']} | {r['distance']} | {r['candidate_reachable_errors']} |")
    quality='\n'.join(lines)
    times='\n'.join(f"- {labels[arm]}：七篇 clean() 累计 {totals[arm]['seconds']:.2f} 秒。" for arm in ('ngram','rag','rag_proposals'))
    ctc_lines='\n'.join(f"| {labels[arm]} | {r['counts']['TP']} | {r['counts']['FP']} | {r['counts']['wrong']} | {r['remaining']} | {r['distance']} |" for arm,r in ctc.items())
    text=f'''# E053｜V2 候选提议与原生 C++ 检索：第一阶段验收

日期：2026-11-13 开始，2026-11-14 验收。Agent：Astra。基础 Git `{d['commit']}`，分支 `{d['branch']}`；改动未提交，已有他人未提交修改原样保留。源码和脚本 SHA256 见 `results/summary.json`，输入与包指纹见 `results/seven.json`，二进制指纹见 `results/verification.json`。

## 1. 做了什么

- 新的研究入口不读答案候选表、普通词频或 competitors.json。N-gram 前缀索引有界遍历提出 2–4 字串；RAG 从真实连续原文补充同读音字串。原文路径保留，AC 锁保留，未知字/读音不取得替换资格。本阶段允许同音异调，暂不扩近音。
- 检索迁至 C++/SQLite：只读既有 v2 数据库，短上下文查询＋原文/候选配对查询，分支交错，段去重，保留来源、位置和真实边界，最多 300 段/8192 字。相比过去广泛 OR 查询，避免只找话题、删掉所有候选后再盼它自己出现。
- 复用既定 `S=a+βG+D`、双向 G/D、KEEP 与背景质量，a=0、β=1、κ=10、ρ=1、α=.01、top_h=30 原值不变；beam=8，最多四对查询种子是提议/检索预算。检索分数不直接加入 S；p 不参与。
- 兼容重叠写法合并，冲突的连通组保留原文。默认不改写，只有 `--research` 才执行。没有切换 V1 默认。

本阶段仅检索在 C++，语言模型、候选遍历、文档封顶计数和判决仍在 Python；不是完整原生运行时迁移。

七篇跑完后的验收选择：研究入口默认 RAG 只补候选（`evidence_scoring=False`），仅显式 `--research --domain-evidence` 启用 D；不调整公式和权重。实测代码按原字节保存在 `frozen/proposal_clean_measured.py`，最终代码只增加该默认/CLI 开关与输出元数据，三臂脚本均显式指定开关，因此表内对照含义不变。最后补跑机制测试。

## 2. 工程验收

- 修改前基线 CTest 25/25（13.23 秒）；修改后 26/26（15.62 秒），新增 12 个机制用例合为一项 CTest。含旧查询一致性、文档封顶、截断不造句界、双边查询、非法请求、只读数据库、无答案表提议、读音硬筛、跨段禁止拼接、重叠冲突、AC 与默认 KEEP。
- 28 组实际语料查询，C++ legacy 模式与 Python 的段 id、正文、来源、偏移、边界、文档集合及计数完全一致。
- 七篇旧 V1 与本次构建 V1 输出逐字节相同，仍 {verification['counts']['TP']}/{verification['counts']['FP']}/{verification['counts']['wrong']}，距离 {verification['distance']}。不等于采用了工作树中其他 Agent 的未合并改动。
- 真值与本轮使用的读音、AC、候选表测试前后指纹一致；实测源码指纹与 frozen 快照一致。最终默认开关/元数据改动单列，不冒称源码完全未动；未修改正式词库或人工真值。
- 初次测试遇到 Windows 临时目录 ACL 失败；换项目内全新临时目录后完整重跑通过，未把环境错误改成跳过断言。

## 3. 七篇完整选择对照（全部开卷）

沿用 E044/E024 数字归一与唯一归因；同七篇，过滤原 discard，不新增标签。原有可归因替换错误 1921 字，零操作距离 2024。候选覆盖仅统计完整窗口均可唯一归因、真实目标确实进入池的原错字；是诊断，不替换正式评分指标。

| 方案 | 改对字 | 改坏原正确字 | 错到错字 | 剩余原替换错字 | 总距离↓ | 候选可达原错字 |
|---|---:|---:|---:|---:|---:|---:|
| 零操作 | 0 | 0 | 0 | 1921 | 2024 | — |
| V1（本轮重跑） | 152 | 79 | 23 | 1769 | 1951 | — |
| E044 固定答案表＋N-gram（历史对照，非本轮重跑） | 94 | 1 | 0 | 1827 | 1931 | — |
{quality}

补充描述性比例，不改变上述验收口径：可唯一归因的原正确字符 {correct_chars} 个、原替换错误 {error_chars} 个。V1 的替换错误召回率为 {152/error_chars:.2%}、原正确字符被误改比例为 {79/correct_chars:.3%}；N-gram 为 {totals['ngram']['counts']['TP']/error_chars:.2%}/{totals['ngram']['counts']['FP']/correct_chars:.3%}；RAG 只补候选为 {totals['rag_proposals']['counts']['TP']/error_chars:.2%}/{totals['rag_proposals']['counts']['FP']/correct_chars:.3%}；加 D 为 {totals['rag']['counts']['TP']/error_chars:.2%}/{totals['rag']['counts']['FP']/correct_chars:.3%}。这些比例不涵盖插删及歧义位置，也不能用大量正确字符稀释误改的实际代价。

逐视频结果见 `results/seven.json`。`rag_proposals` 重放本轮原生检索结果，每个请求均核对相等，并重新完整生成、评分、竞争、重叠选择；不是删除最终输出模拟消融。它与 `rag` 的检索资料及候选池相同，只关闭 D，以分开候选贡献与判决证据贡献。旧 V1/固定答案表与开放提议器的可达范围不同，不能只比精度忽略召回。

全量 trace 与检索重放文件在 `build/e053/`，包含原文片段但未混入语料/词库。`pilot.json` 是同配置首篇预跑，不另算独立验证。

## 4. 异域及旧问题

CTC 三份文本错字资料各取前 30 句，共 90 句，完整处理；没有选中错误位置再喂给程序。按同一字符指标计分，没有调参数。这是异域小样本，不是独立 ASR 泛化验收，也未证明与公开训练语料完全无重合。

| 方案 | 改对 | 误改 | 错到错 | 剩余原错 | 总距离 |
|---|---:|---:|---:|---:|---:|
{ctc_lines}

构造的已知正确负例中，“略微深一点”“谈话核实”“谈话人员”保留；“微星电脑”被改成“微型电脑”（1 字）。默认未启用 research 时原文全部保留。

实际 `datasets/whisper_txt/BV1ghec66Eau.txt` 中已确认的“这个颜色要略微深一点”本轮保留。全文另有 {supplement['real_asr']['total_changed_chars_unlabeled']} 个字发生变化，其他区域没有本轮认可的完整真值，**不分类成改对/误改**。

## 5. 性能与代价

{times}
- 新入口初次加载 {d['load_seconds']:.2f} 秒，包括文件校验、366 MB JSON 模型与索引；这不是 V1 的启动时间。
- 28 组相同查询：Python {verification['python_seconds']:.3f} 秒，C++ {verification['cpp_seconds']:.3f} 秒。查询次序固定、缓存与运行库不同，只证明迁移没有明显恶化，不能宣称可靠的提速百分比；计数验证使用小字表，不能代表完整模型推理。
- 部分七篇运行与补充实验重叠，实测可用内存曾降至约 0.4 GiB。补充实验结束后余下串行完成，以上墙钟受并行和内存压力影响，**不作为纯吞吐验收**。`rag_proposals` 含重放文件读取，不能与在线 RAG 耗时直接相减声称检索成本。

## 6. 结论与未解决项

工程迁移通过，质量没有据此通过。检索终于能补候选、影响领域证据，但“有证据”不代表“证据能区分对错”；保留研究入口，不能替代生产默认。已有正确低频词/品牌仍会被常见写法挤掉。

另查实 N-gram 提议可以组合出整体未在模型中出现的串，例如“给点小奖→奇点效奖”。N-gram 臂中，未整体见过的候选涉及 54 改对、52 误改、14 错到错；首读音不同、依赖至少一个非首读音的改动涉及 14 改对、22 误改、4 错到错。详见 `results/candidate_audit.json`。因此不能假定一刀切删除这些候选没有召回代价；该归因不能直接推算删除后的结果，改变资格后必须重跑完整选择。

本轮没有全量关闭 AC 保护的对照，也没有新检索器的完整错领域对照；只完成 AC 机制用例和开保护的七篇实测。质量发布验收未通过，不能用工程验收替代这些尚未完成的检查。

后续优先在候选可靠性层验证“整串有据”和读音歧义处理，再研究校准；不因 D 已非零就扩大权重，不恢复旧答案表来掩盖开放提议的风险，不根据这七篇调门槛宣称泛化。完整 C++ LM/提议/判决迁移尚未做，资料不足、漏候选、未知读音及插删错误仍存在。

## 7. 复现

```powershell
cmake -S . -B build/astra_v2 -G "MinGW Makefiles" -DTC_BUILD_RETRIEVAL=ON -DPython3_EXECUTABLE=C:/Users/Lin/AppData/Local/Python/pythoncore-3.14-64/python.exe
cmake --build build/astra_v2 -j 4
# Windows 若临时目录权限冲突，使用一个新建的项目内 TEMP/TMP 目录。
ctest --test-dir build/astra_v2 --output-on-failure
python experiments/E053/scripts/verify.py
python experiments/E053/scripts/run.py --tag seven --implementation experiments/E053/frozen/proposal_clean_measured.py
python experiments/E053/scripts/supplement.py
python experiments/E053/scripts/audit_candidates.py
python experiments/E053/scripts/summarize.py
```

大模型实验按上面顺序串行，不同时启动两个模型。无需下载资料或改真值；包为 `build/e044_full`。SHA 与参数已经写入结果。入口与 C++ 协议见 `docs/V2_PROPOSAL_RETRIEVAL.md`。

## 8. 本轮修改文件

- C++：`include/text_clean/retrieval.h`、`src/retrieval.cpp`、`src/retrieval_main.cpp`；可选目标接入 `CMakeLists.txt`。
- Python：`tools/native_retrieval.py`、`tools/proposal_clean.py`；正式测试 `tests/test_proposal_clean.py`。
- 文档：`docs/V2_PROPOSAL_RETRIEVAL.md`、README 追加、Architecture 本人追加节、本人日志与公共实验/状态追加。
- 实验：`experiments/E053/scripts/`、`results/` 与本报告。未提交/推送，未改其他 Agent 日志；此前已有的源码修改不冒认为本轮成果。
'''
    (ROOT/'experiments/E053/README.md').write_text(text,encoding='utf8')
    print(json.dumps(totals,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
