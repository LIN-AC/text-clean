import pathlib
import subprocess
import sys
import tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
from bili2md_text_clean import clean_subtitles
exe = str(pathlib.Path(sys.argv[1]).resolve())
tempfile.tempdir = str(pathlib.Path(sys.argv[2]).resolve())
assert clean_subtitles(exe, "微信", "微信教程", "薇星") == "微信\n"
assert clean_subtitles(exe, "微信", "微信教程", "我买了微星主板") == "我买了微星主板\n"
assert clean_subtitles(exe, "华为华为", "华为", "谈话核实、花了很多心血") == "谈话核实、花了很多心血\n"
with tempfile.TemporaryDirectory() as directory:
    path = pathlib.Path(directory) / "中文标题.txt"
    path.write_text("微信", encoding="utf-8")
    p = subprocess.run([exe, "--title-file", str(path), "--description", "微信", "薇星"], capture_output=True, check=True)
    assert p.stdout.decode().strip() == "微信"
    p = subprocess.run([exe, "--description-file", str(path) + ".missing"], input=b"", capture_output=True)
    assert p.returncode == 2 and p.stdout == b""
print("CLI metadata / adapter / missing file / Unicode path: PASS")

# User-reported ASR sentence must survive misleading topic metadata too.
assert clean_subtitles(exe, "微信", "微信教程", "这个颜色要略微深一点") == "这个颜色要略微深一点\n"
# Optional local real-corpus regression: corpus is intentionally not committed.
corpus = pathlib.Path(__file__).resolve().parents[1] / "whisper_txt" / "BV1ghec66Eau.txt"
if corpus.exists():
    original = corpus.read_bytes().decode("utf-8")
    assert "这个颜色要略微深一点" in original
    result = subprocess.run([exe], input=original.encode("utf-8"), capture_output=True, check=True)
    expected = original if original.endswith("\n") else original + "\n"
    assert result.stdout.decode("utf-8") == expected
