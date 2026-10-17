from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from api.routes.deps import CatalogDep
from api.schemas import AutomationSummary

router = APIRouter(tags=["catalog"])


@router.get("/automations")
async def list_automations(catalog: CatalogDep) -> list[AutomationSummary]:
    return [AutomationSummary.of(spec) for spec in catalog.list()]


@router.get("/automations/{automation_id}")
async def get_automation(automation_id: str, catalog: CatalogDep) -> dict[str, Any]:
    spec = catalog.get(automation_id)
    if spec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "automation not found")
    return spec


@router.post("/automations/{automation_id}/download")
async def download_automation(automation_id: str, catalog: CatalogDep) -> None:
    if catalog.get(automation_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "automation not found")
    # Prebuilt EXEs come with the catalog build workflow and R2 storage (Phase 2).
    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "downloads are not available yet")
