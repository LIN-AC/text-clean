#!/usr/bin/env python3
"""人工输入热词阶段：用 text_clean --review 逐篇处理 whisper_txt，把挑选出的
专有名词/固定用词作为热词喂回交互输入，由程序追加到 data/word.txt。

热词只收准确的专有名词（品牌、产品名、型号）与领域固定用词；
不收句子片段、口语梗、形容词。英文/数字词（5090、Apple 类）不会被程序的分词
报为未收录词，只能在这里人工输入。

Usage: python tools/submit_hotwords.py [--dry-run]
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXE = ROOT / "build-gcc" / "text_clean.exe"
CORPUS_DIR = ROOT / "whisper_txt"
WORD_FILE = ROOT / "data" / "word.txt"
CLEAN_DIR = ROOT / "clean_txt"

# 按文件（BV 号）整理的人工热词，全部与语料中的写法核对过。
HOTWORDS: dict[str, list[str]] = {
    "BV162AEzyEiF": [
        "小米", "Xiaomi", "Xiaomi Book", "XiaomiBook", "Redmi", "轻薄本",
        "性能释放",
    ],
    "BV174421f7Th": [
        "英特尔", "Intel", "CPU", "缩缸", "默频", "定压超频",
    ],
    "BV1CJxv6qEqw": [
        "Intel", "Core Ultra", "273PQE", "CPU",
    ],
    "BV1cLFSz4ECr": [
        "NVIDIA", "RTX", "RTX5060", "游戏本", "笔记本电脑",
    ],
    "BV1d4pZ6JEZy": [
        "双十一", "固态硬盘", "SSD",
    ],
    "BV1DaGy6GEQK": [
        "618", "国补", "内存", "闪存", "笔记本电脑",
    ],
    "BV1dHiyBkE1t": [
        "CPU", "Intel", "AMD",
    ],
    "BV1EBxT6DEhk": [
        "REDMI", "Redmi", "REDMI Book", "Wildcat Lake", "处理器", "模具",
    ],
    "BV1f4Hk6gEDP": [
        "都市：天际线2", "天际线", "帧率", "双通道", "内存", "锐龙", "酷睿",
        "Core Ultra", "X3D", "PBO", "ROG", "14900K", "14700K", "9950X3D",
        "9800X3D", "7800X3D", "285K",
    ],
    "BV1fhhP6xEMp": [
        "小米", "玄戒", "玄戒O3",
    ],
    "BV1gfJ46jEsF": [
        "英伟达", "NVIDIA", "RTX Spark",
    ],
    "BV1ghec66Eau": [
        "iPhone",
    ],
    "BV1i7XpBREMy": [
        "三星", "S26 Ultra", "S24 Ultra", "防窥屏",
    ],
    "BV1ikxE62EVP": [
        "NVIDIA", "RTX Spark", "SoC", "Windows", "ARM",
    ],
    "BV1JocweiEQf": [
        "5090", "显卡",
    ],
    "BV1joFezGEqj": [
        "极客湾", "AMD", "TR 9995WX", "9995WX", "水冷", "散热器", "超频",
        "CNC", "顶盖", "水冷头",
    ],
    "BV1Ke3C6FEuc": [
        "CPU", "Intel", "AMD", "笔记本电脑",
    ],
    "BV1kMxM6FECM": [
        "苹果", "A20 Pro", "高通", "骁龙", "联发科", "天玑", "天玑9600",
        "玄戒O3", "麒麟", "谷歌", "Tensor G6", "能效",
    ],
    "BV1LR336sEFX": [
        "极客湾", "电池锁容", "AI Agent",
    ],
    "BV1Nu4m1K79M": [
        "龙芯", "3A6000", "CPU", "液氮", "超频", "开源", "软件生态",
    ],
    "BV1Nz1FBdEiy": [
        "OPPO", "Find X9 Pro", "vivo", "X300 Pro",
    ],
    "BV1oZeA6fERD": [
        "iPhone", "A20 Pro", "A15", "苹果", "安卓", "游戏手机", "散热",
    ],
    "BV1rDa36SErm": [
        "笔记本电脑",
    ],
    "BV1vESwBQEKg": [
        "显示器",
    ],
    "BV1WSHK6SEfL": [
        "中央处理器", "CPU", "GPU", "主板", "台式机", "电源", "显卡",
        "散热器", "晶体管", "DRAM", "固态硬盘", "硬盘驱动器", "HDD",
        "Branch Education",
    ],
    "BV1X6AreqEwm": [
        "RTX5070Ti", "RTX", "5080", "4080S", "能效",
    ],
    "BV1yQfWYaEVo": [
        "RTX5090", "5090D", "RTX", "50系显卡", "DLSS", "DLSS4", "帧稳定性",
        "多帧生成", "帧生成", "特供版",
    ],
    "BV1yXsf6MEru": [
        "Intel", "Wildcat Lake", "轻薄本", "18A", "架构", "单核",
    ],
    "BV1zcYLzCE2H": [
        "三星",
    ],
    "BV1zPxw6BE1S": [
        "影之刃零", "显卡",
    ],
}


def review_file(path: pathlib.Path, words: list[str], dry_run: bool) -> str:
    stdin_data = "\n".join(words) + "\n\n" if words else "\n"  # 空行结束本批输入
    args = [str(EXE), "--review", "--word-file", str(WORD_FILE),
            "--lexicon", str(ROOT / "data" / "lexicon.txt"),
            "--pinyin-dict", str(ROOT / "data" / "pinyin_dict.txt"),
            "--input-file", str(path)]
    if dry_run:
        proc = subprocess.run(args, input="\n", capture_output=True, text=True,
                              encoding="utf-8", errors="replace", cwd=ROOT)
        return proc.stderr
    CLEAN_DIR.mkdir(exist_ok=True)
    with open(CLEAN_DIR / path.name, "wb") as fh:
        proc = subprocess.run(args, input=stdin_data.encode("utf-8"),
                              stdout=fh, stderr=subprocess.PIPE, check=True,
                              cwd=ROOT)
    return proc.stderr.decode("utf-8", "replace")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    dry_run = "--dry-run" in sys.argv

    def entries(lines):
        return [l.strip() for l in lines if l.strip() and not l.startswith("#")]

    before = WORD_FILE.read_text(encoding="utf-8").splitlines()
    for path in sorted(CORPUS_DIR.glob("*.txt")):
        words = HOTWORDS.get(path.stem, [])
        stderr = review_file(path, words, dry_run)
        lines = [l for l in stderr.splitlines()
                 if l.startswith("已新增") or l.startswith("标题/简介词表已覆盖")
                 or l.startswith("未新增") or l.startswith("没有新增")]
        print(f"{path.stem}  提交 {len(words)} 个热词  | " + " ; ".join(lines))
    after = WORD_FILE.read_text(encoding="utf-8").splitlines()
    old_set = set(entries(before))
    added = [w for w in entries(after) if w not in old_set]
    print(f"\nword.txt 有效词条 {len(old_set)} -> {len(set(entries(after)))}，本次新增 {len(added)} 个：")
    for i in range(0, len(added), 6):
        print("  " + "  ".join(added[i:i + 6]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
