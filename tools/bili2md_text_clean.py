"""Small subprocess adapter. No shell, service, or persistent video state."""
from pathlib import Path
import subprocess
import tempfile


def clean_subtitles(executable: str, title: str, description: str, raw_asr: str) -> str:
    """Return UTF-8 subtitles; raise CalledProcessError on CLI failure.

    The CLI adds a final newline, as in its legacy interface. For exact byte
    preservation / per-cue processing, use the C++ VideoContext API instead.
    """
    executable = str(Path(executable).resolve())
    with tempfile.TemporaryDirectory(prefix="text_clean_") as directory:
        title_file = Path(directory) / "title.txt"
        description_file = Path(directory) / "description.txt"
        title_file.write_text(title, encoding="utf-8")
        description_file.write_text(description, encoding="utf-8")
        result = subprocess.run(
            [executable, "--title-file", str(title_file),
             "--description-file", str(description_file)],
            input=raw_asr.encode("utf-8"), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=True,
        )
    return result.stdout.decode("utf-8")
