from decimal import Decimal

import pytest

from engine.errors import EngineError
from engine.fileutil import safe_filename, write_new_file
from engine.money import format_indian, format_number, round_money, to_decimal


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ("0", "0.00"),
        ("999", "999.00"),
        ("1000", "1,000.00"),
        ("118000", "1,18,000.00"),
        ("12345678.9", "1,23,45,678.90"),
        ("-2500.5", "-2,500.50"),
        ("0.005", "0.01"),
    ],
)
def test_format_indian(value, text):
    assert format_indian(Decimal(value)) == text


def test_numbers():
    assert to_decimal(" 1,200.50 ") == Decimal("1200.50")
    assert to_decimal("") is None and to_decimal(None) is None
    for bad in ("abc", "nan", "inf", True):
        with pytest.raises(ValueError):
            to_decimal(bad)
    assert round_money(Decimal("2.345")) == Decimal("2.35")
    assert format_number(Decimal("2.50")) == "2.5"
    assert format_number(Decimal("2")) == "2"


@pytest.mark.parametrize(
    ("name", "ext", "expected"),
    [
        ("INV-1.pdf", "pdf", "INV-1.pdf"),
        ("INV-1", "pdf", "INV-1.pdf"),
        ('a<b>:"c"/d\\e|f?g*.pdf', "pdf", "a-b---c--d-e-f-g-.pdf"),
        ("report.txt", "pdf", "report.txt.pdf"),
        ("CON.pdf", "pdf", "_CON.pdf"),
        ("trailing. . ", "pdf", "trailing.pdf"),
        ("", "pdf", "file.pdf"),
    ],
)
def test_safe_filename(name, ext, expected):
    assert safe_filename(name, ext) == expected


def test_write_new_file_never_overwrites(tmp_path):
    first = write_new_file(tmp_path / "out", "INV-1.pdf", b"one")
    second = write_new_file(tmp_path / "out", "INV-1.pdf", b"two")
    third = write_new_file(tmp_path / "out", "INV-1.pdf", b"three")
    assert [p.name for p in (first, second, third)] == [
        "INV-1.pdf",
        "INV-1 (2).pdf",
        "INV-1 (3).pdf",
    ]
    assert first.read_bytes() == b"one"  # the original is untouched


def test_write_new_file_gives_up_after_many(tmp_path, monkeypatch):
    import engine.fileutil as fu

    def always_exists(self, mode="r", *a, **k):
        raise FileExistsError

    monkeypatch.setattr(fu.Path, "open", always_exists)
    with pytest.raises(EngineError, match="too many files"):
        write_new_file(tmp_path, "x.pdf", b"")
