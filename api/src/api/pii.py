"""Server-side PII guard. Mirrors web/src/lib/pii.ts; both run tests/fixtures/pii_cases.json.

Descriptions should hold only the FORMAT of a task. Anything that looks like real personal or
business data is masked before it is stored or sent to a routine.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

LABELS = {
    "email": "email address",
    "gstin": "GSTIN",
    "pan": "PAN",
    "ifsc": "IFSC code",
    "card": "card number",
    "aadhaar": "Aadhaar number",
    "phone": "phone number",
    "bank_account": "bank account number",
}


@dataclass(frozen=True)
class PiiMatch:
    kind: str
    start: int
    end: int
    text: str


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def verhoeff_valid(digits: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


# ASCII-only \d, \w and \b, matching JavaScript regex semantics.
_A = re.ASCII

# Order matters: earlier detectors win where matches overlap. Same order and patterns as pii.ts.
_DETECTORS: list[tuple[str, re.Pattern[str], Callable[[str], bool] | None]] = [
    (
        "email",
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}", _A),
        None,
    ),
    ("gstin", re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b", _A | re.I), None),
    ("pan", re.compile(r"\b[A-Z]{3}[ABCFGHJLPT][A-Z]\d{4}[A-Z]\b", _A | re.I), None),
    ("ifsc", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", _A | re.I), None),
    (
        "card",
        re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])", _A),
        lambda t: luhn_valid(_digits(t)),
    ),
    (
        "aadhaar",
        re.compile(r"(?<!\d)[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?!\d)", _A),
        lambda t: verhoeff_valid(_digits(t)),
    ),
    (
        "phone",
        re.compile(
            r"(?<![\w+])(?:(?:\+91|0091|91)[ -]?|0)?[6-9]\d{4}[ -]?\d{5}(?!\d)"
            r"|\+\d{1,3}[ -]?\d(?:[ -]?\d){6,12}(?!\d)",
            _A,
        ),
        None,
    ),
    ("bank_account", re.compile(r"(?<!\d)\d{9,18}(?!\d)", _A), None),
]


def find_pii(text: str) -> list[PiiMatch]:
    found: list[PiiMatch] = []
    for kind, pattern, accept in _DETECTORS:
        for m in pattern.finditer(text):
            start, end = m.span()
            if any(start < f.end and f.start < end for f in found):
                continue
            if accept and not accept(m.group()):
                continue
            found.append(PiiMatch(kind, start, end, m.group()))
    return sorted(found, key=lambda m: m.start)


def mask_pii(text: str, matches: list[PiiMatch] | None = None) -> str:
    matches = find_pii(text) if matches is None else matches
    out, last = [], 0
    for m in sorted(matches, key=lambda m: m.start):
        out.append(text[last : m.start])
        out.append(f"[{LABELS[m.kind]}]")
        last = m.end
    out.append(text[last:])
    return "".join(out)
