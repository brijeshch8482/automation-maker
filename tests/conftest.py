import copy
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AUTOMATIONS_DIR = REPO_ROOT / "automations"
INVOICE_SPEC = AUTOMATIONS_DIR / "invoice-generator" / "spec.json"


@pytest.fixture
def invoice_spec() -> dict:
    """A fresh, mutable copy of the invoice-generator spec."""
    return copy.deepcopy(json.loads(INVOICE_SPEC.read_text(encoding="utf-8")))
