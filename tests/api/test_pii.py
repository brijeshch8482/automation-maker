import json

import pytest

from api.pii import find_pii, luhn_valid, mask_pii, verhoeff_valid
from tests.conftest import REPO_ROOT

CASES = json.loads((REPO_ROOT / "tests/fixtures/pii_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES["detect"], ids=lambda c: c["text"][:40])
def test_find_pii(case):
    assert [[m.kind, m.text] for m in find_pii(case["text"])] == case["expect"]


@pytest.mark.parametrize("case", CASES["mask"], ids=lambda c: c["text"][:40])
def test_mask_pii(case):
    assert mask_pii(case["text"]) == case["masked"]


def test_checksums():
    assert verhoeff_valid("234123412346")
    assert not verhoeff_valid("234123412345")
    assert luhn_valid("4111111111111111")
    assert not luhn_valid("4111111111111112")


def test_non_ascii_digits_are_not_matched():
    # Devanagari digits: JavaScript's \d doesn't match them, so neither may Python's.
    assert find_pii("९८७६५४३२१०") == []
