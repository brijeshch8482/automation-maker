import json

import pytest

from tests.conftest import AUTOMATIONS_DIR
from tools.validate_spec import validate_spec

SPEC_FILES = sorted(AUTOMATIONS_DIR.glob("*/spec.json"))


def test_catalog_is_not_empty():
    assert SPEC_FILES


@pytest.mark.parametrize("path", SPEC_FILES, ids=lambda p: p.parent.name)
def test_catalog_spec_is_valid(path):
    spec, issues = validate_spec(json.loads(path.read_text(encoding="utf-8")))
    assert issues == []
    assert spec.id == path.parent.name
    assert spec.sample_data, "every catalog automation needs sample_data"
