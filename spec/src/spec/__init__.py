"""AutomationSpec models and block catalog. Source of truth for every automation."""

from spec.catalog import BLOCKS, BlockDef, get_block
from spec.models import CATEGORIES, FIELD_TYPES, AutomationSpec

__all__ = ["BLOCKS", "CATEGORIES", "FIELD_TYPES", "AutomationSpec", "BlockDef", "get_block"]
