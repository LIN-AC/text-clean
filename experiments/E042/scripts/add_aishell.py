#!/usr/bin/env python3
"""E042：把 AISHELL-1 转录转成契约文档 JSONL（一条录音转写＝一个文档）。

三件事必须做对：
  1) 原文件字段是**分词加空格**的（"而 对 楼市 成交"），拼回连续文本时不能留空格，
     否则规范化会把每个词界当成边界，句内搭配全断。
  2) 每条只有十来个字，注册为 register=口语朗读（照稿），不冒充会话口语；
     短句对"下一字转移"这类证据贡献弱，消费方可以按 register 自行排除。
  3) 逐条记录 utt_id、许可（Apache-2.0，官方卡片另写"free for academic use"）与原始行 SHA256。
"""
import argparse, hashlib, json, pathlib, sys, time

R = pathlib.Path(__file__).resolve().parents[3]
sys.stdout.reconfigure(encoding='utf-8')
SRC = R / 'build/e042_corpus/raw/aishell_transcript_v0.8.txt'
OUT = R / 'build/e042_corpus/jsonl/aishell1_transcript.jsonl'
URL = 'https://huggingface.co/datasets/AISHELL/AISHELL-1/resolve/main/data_aishell/transcript/aishell_transcript_v0.8.txt'
LICENSE = ('Apache-2.0（AISHELL-1 官方数据卡片 license: apache-2.0；卡片另注明 "The data is free for '
           'academic use"，北京希尔壳科技发布，人工转写准确率 >95%）')


def main(min_han=6):
    ap = argparse.ArgumentParser()
    ap.add_argument('--min-han', type=int, default=min_han)
    a = ap.parse_args()
    file_sha = hashlib.sha256(SRC.read_bytes()).hexdigest()
    n = kept = han = 0
    with OUT.open('w', encoding='utf-8', newline='\n') as w:
        for line in SRC.read_text('utf-8', errors='replace').splitlines():
            if not line.strip():
                continue
            n += 1
            uid, _, rest = line.partition(' ')
            parts = rest.split()
            text = ''.join(parts)                      # 分词空格必须去掉
            c = sum(1 for ch in text if '一' <= ch <= '鿿')
            if c < a.min_han:
                continue
            w.write(json.dumps(dict(domain='现代', register='口语朗读（照稿）', period='2015–2018',
                                    work='AISHELL-1 人工转写文本', title='utt ' + uid,
                                    url=URL + '#utt=' + uid, license=LICENSE, source_family='aishell1_transcript',
                                    fetched_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
                                    src_sha=hashlib.sha256(line.encode()).hexdigest(),
                                    source_file_sha=file_sha, chars=c, raw=text), ensure_ascii=False) + '\n')
            kept += 1
            han += c
    print('读入 %d 行，写出 %d 条 / %d 汉字 → %s' % (n, kept, han, OUT), flush=True)


if __name__ == '__main__':
    main()
