#!/usr/bin/env python3
"""Run the ASR corpus regression against clean_txt reference bodies.

Each whisper_txt file is split into 标题/简介/正文. Title and description are
passed as context; the body goes through stdin. Reference bodies come from
clean_txt/<same name>.

Recorded baseline: agents/EXPERIMENTS.md E5, commit 14aad46.

Usage:
  python tools/asr_eval.py --recorded
  python tools/asr_eval.py --random 10 --seed 20261103
  python tools/asr_eval.py --files BV1ghec66Eau.txt,BV1yQfWYaEVo.txt
  python tools/asr_eval.py --recorded --set "--mu 1.0" --json .verify/e5.json
"""

import argparse
import difflib
import json
import os
import pathlib
import random
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent

RECORDED = [
    "BV1ghec66Eau.txt",
    "BV1yQfWYaEVo.txt",
    "BV1joFezGEqj.txt",
    "BV1fhhP6xEMp.txt",
    "BV1kMxM6FECM.txt",
    "BV1vESwBQEKg.txt",
    "BV1cLFSz4ECr.txt",
    "BV1ikxE62EVP.txt",
    "BV1EBxT6DEhk.txt",
    "BV174421f7Th.txt",
]

MARKER = re.compile(r"^=====\s*(标题|简介|正文)\s*=====\s*$")
VERBOSE = re.compile(
    r'^\s+\[(exact|pinyin|fuzzy)\] status=(\w+) (\d+)\.\.(\d+) '
    r'"(.*?)" -> "(.*?)" entry=(\d+) distance=(\d+) score=([-0-9.eE+]+) '
    r"logR=([-0-9.eE+]+) fC=(\d+) fO=(\d+) action=(\w+)"
    r"(?: context_bonus=([-0-9.eE+]+))?"
)

BIN_CANDIDATES = [
    "build-v122-msvc/Release/text_clean.exe",
    "build-v122-gcc/text_clean.exe",
    "build/Release/text_clean.exe",
    "build/text_clean.exe",
]


def find_binary(explicit):
    if explicit:
        path = pathlib.Path(explicit)
        if not path.is_absolute():
            path = ROOT / path
        if not path.exists():
            sys.exit(f"error: cleaner binary not found: {path}")
        return path
    for rel in BIN_CANDIDATES:
        path = ROOT / rel
        if path.exists():
            return path
    sys.exit(
        "error: no cleaner binary found; pass --bin "
        "(tried: " + ", ".join(BIN_CANDIDATES) + ")"
    )


def split_sections(text):
    sections = {}
    current = None
    buf = []
    for line in text.splitlines(keepends=True):
        match = MARKER.match(line.strip())
        if match:
            if current is not None:
                sections[current] = "".join(buf)
            current = match.group(1)
            buf = []
        else:
            buf.append(line)
    if current is not None:
        sections[current] = "".join(buf)
    return sections


def load_document(path):
    sections = split_sections(path.read_text(encoding="utf-8"))
    return (
        sections.get("标题", "").strip("\n"),
        sections.get("简介", "").strip("\n"),
        sections.get("正文", "").strip("\n"),
    )


def parse_matches(stderr):
    matches = []
    for line in stderr.splitlines():
        match = VERBOSE.match(line)
        if not match:
            continue
        g = match.groups()
        matches.append(
            {
                "kind": g[0],
                "status": g[1],
                "begin": int(g[2]),
                "end": int(g[3]),
                "matched": g[4],
                "replacement": g[5],
                "entry": int(g[6]),
                "distance": int(g[7]),
                "score": float(g[8]),
                "logR": float(g[9]),
                "fC": int(g[10]),
                "fO": int(g[11]),
                "action": g[12],
                "bonus": float(g[13]) if g[13] else 0.0,
            }
        )
    return matches


def run_file(binary, corpus, ref_dir, name, repeat, cleaner_args):
    title, desc, body = load_document(corpus / name)
    ref_path = ref_dir / name
    ref_body = load_document(ref_path)[2] if ref_path.exists() else ""
    if not ref_body:
        print(f"warning: reference body missing for {name}", file=sys.stderr)

    # A private scratch directory with ordinary permissions. tempfile.mkdtemp
    # (and TemporaryDirectory) creates 0o700, which some sandboxes then cannot
    # write into; removals are best effort so a leftover never aborts a run.
    td = pathlib.Path(tempfile.gettempdir()) / f"tc_asr_{os.getpid()}_{time.time_ns()}"
    td.mkdir(parents=True, exist_ok=True)
    try:
        title_path = td / "title.txt"
        desc_path = td / "desc.txt"
        title_path.write_text(title, encoding="utf-8")
        desc_path.write_text(desc, encoding="utf-8")
        times = []
        out = err = b""
        for _ in range(repeat):
            start = time.perf_counter()
            proc = subprocess.run(
                [
                    str(binary),
                    "--title-file",
                    str(title_path),
                    "--description-file",
                    str(desc_path),
                    "-v",
                    *cleaner_args,
                ],
                input=(body + "\n").encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(ROOT),
            )
            times.append((time.perf_counter() - start) * 1000.0)
            out, err = proc.stdout, proc.stderr
            if proc.returncode != 0:
                print(
                    f"warning: {name} exited with {proc.returncode}",
                    file=sys.stderr,
                )
    finally:
        shutil.rmtree(td, ignore_errors=True)

    output = out.decode("utf-8", "replace").rstrip("\n")
    body_norm = body.rstrip("\n")
    ref_norm = ref_body.rstrip("\n")
    matches = parse_matches(err.decode("utf-8", "replace"))
    changes = [m for m in matches if m["matched"] != m["replacement"]]

    kinds = {}
    for match in matches:
        kinds[match["kind"]] = kinds.get(match["kind"], 0) + 1

    similarity = (
        difflib.SequenceMatcher(None, output, ref_norm).ratio() if ref_norm else 0.0
    )
    ref_same_len = len(ref_norm) == len(body_norm)
    classes = {"aligned": 0, "contradicted": 0, "uncertain": 0}
    change_records = []
    for match in changes:
        begin, end = match["begin"], match["end"]
        ref_seg = (
            ref_norm[begin:end]
            if ref_same_len and end <= len(ref_norm)
            else None
        )
        if ref_seg == match["replacement"]:
            verdict = "aligned"
        elif ref_seg == match["matched"]:
            verdict = "contradicted"
        else:
            verdict = "uncertain"
        classes[verdict] += 1
        change_records.append(
            {
                "file": name,
                "kind": match["kind"],
                "begin": begin,
                "end": end,
                "matched": match["matched"],
                "replacement": match["replacement"],
                "distance": match["distance"],
                "score": match["score"],
                "fC": match["fC"],
                "fO": match["fO"],
                "bonus": match["bonus"],
                "ref_seg": ref_seg,
                "cls": verdict,
            }
        )

    return {
        "file": name,
        "body_chars": len(body_norm),
        "ref_chars": len(ref_norm),
        "matches": len(matches),
        "ac_locked": sum(1 for m in matches if m["status"] == "ac_locked"),
        "kinds": kinds,
        "changes": len(changes),
        "changed": output != body_norm,
        "sim": similarity,
        "exact_ref": output == ref_norm,
        "ref_same_len": ref_same_len,
        "avg_ms": sum(times) / len(times),
        "times": times,
        "classes": classes,
        "change_records": change_records,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin", help="path to text_clean executable")
    parser.add_argument("--corpus", default="whisper_txt", help="ASR corpus dir")
    parser.add_argument("--ref-dir", default="clean_txt", help="reference dir")
    parser.add_argument(
        "--files", help="comma-separated file names (relative to --corpus)"
    )
    parser.add_argument("--recorded", action="store_true", help="run the E5 file set")
    parser.add_argument(
        "--random", type=int, help="randomly sample N files instead of --files"
    )
    parser.add_argument("--seed", type=int, default=20261103)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument(
        "--set", dest="cleaner_args", default="", help="extra cleaner CLI args"
    )
    parser.add_argument("--json", help="write full results to this JSON file")
    args = parser.parse_args()

    corpus = ROOT / args.corpus
    ref_dir = ROOT / args.ref_dir
    if not corpus.is_dir():
        sys.exit(f"error: corpus directory not found: {corpus}")

    all_names = sorted(p.name for p in corpus.glob("*.txt"))
    if args.files:
        names = [name.strip() for name in args.files.split(",") if name.strip()]
    elif args.recorded:
        names = list(RECORDED)
    elif args.random:
        names = random.Random(args.seed).sample(all_names, min(args.random, len(all_names)))
    else:
        parser.error("choose one of --files, --recorded, --random N")

    missing = [name for name in names if not (corpus / name).exists()]
    if missing:
        sys.exit("error: corpus files missing: " + ", ".join(missing))

    binary = find_binary(args.bin)
    cleaner_args = shlex.split(args.cleaner_args)

    rows = []
    for name in names:
        rows.append(
            run_file(binary, corpus, ref_dir, name, max(1, args.repeat), cleaner_args)
        )

    print("FILE\tchars\tmatches\tAC\tchanges\tchanged\tsim\texact_ref\tavg_ms")
    for row in rows:
        print(
            f"{row['file']}\t{row['body_chars']}\t{row['matches']}\t"
            f"{row['ac_locked']}\t{row['changes']}\t{row['changed']}\t"
            f"{row['sim']:.6f}\t{row['exact_ref']}\t{row['avg_ms']:.1f}"
        )

    classes = {
        key: sum(row["classes"][key] for row in rows)
        for key in ("aligned", "contradicted", "uncertain")
    }
    print(
        "\nTOTAL files {files} changed_files {changed} changes {changes} "
        "exact_ref_files {exact} avg_sim {sim:.6f} avg_ms {ms:.2f} "
        "total_chars {chars}".format(
            files=len(rows),
            changed=sum(1 for row in rows if row["changed"]),
            changes=sum(row["changes"] for row in rows),
            exact=sum(1 for row in rows if row["exact_ref"]),
            sim=sum(row["sim"] for row in rows) / len(rows),
            ms=sum(row["avg_ms"] for row in rows) / len(rows),
            chars=sum(row["body_chars"] for row in rows),
        )
    )
    print("CHANGE_CLASS", classes)
    print("\nCHANGES")
    for row in rows:
        for change in row["change_records"]:
            print(change)

    if args.json:
        out_path = pathlib.Path(args.json)
        if not out_path.is_absolute():
            out_path = ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "commit": subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                text=True,
            ).stdout.strip(),
            "binary": str(binary),
            "files": names,
            "repeat": args.repeat,
            "cleaner_args": cleaner_args,
            "rows": rows,
            "change_class": classes,
        }
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nwrote {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
