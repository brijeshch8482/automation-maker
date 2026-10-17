from pathlib import Path

from engine.testing import load_custom_step, run_custom_step
from engine.values import Document

SPEC = Path(__file__).parent / "spec.json"


def test_counts_words_lines_and_characters():
    numbers = load_custom_step(SPEC).count("one two\nthree\n")
    assert numbers == {"words": 3, "lines": 2, "characters": 14}


def test_run_on_sample_data(tmp_path):
    report = run_custom_step(SPEC, tmp_path)
    assert isinstance(report, Document)
    assert report.extension == "txt"
    assert report.data.decode("utf-8").splitlines() == [
        "Words: 23",
        "Lines: 4",
        "Characters: 118",
    ]
