from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from api.routes.deps import CatalogDep, StorageDep
from api.schemas import AutomationSummary, DownloadOut

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


@router.get("/automations/{automation_id}/download")
async def download_automation(
    automation_id: str, catalog: CatalogDep, storage: StorageDep
) -> DownloadOut:
    """Short-lived links to the latest published build (no login: ready-made apps are free)."""
    if catalog.get(automation_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "automation not found")
    entry = (await storage.catalog_manifest()).get(automation_id) if storage else None
    if not entry:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "downloads are not available yet")
    app = storage.link(entry["zip"], filename=entry["zip"].rsplit("/", 1)[-1])
    guide = storage.link(entry["guide"], filename="Guide.pdf", inline=True)
    return DownloadOut(
        version=entry["version"],
        filename=entry["zip"].rsplit("/", 1)[-1],
        size_bytes=entry.get("zip_bytes"),
        url=app.url,
        guide_url=guide.url,
        expires_in=app.expires_in,
        built_at=entry.get("built_at"),
    )
