from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from api.downloads import TOKEN_TTL_S, bundle_link, worker_link
from api.routes.deps import CatalogDep, StorageDep
from api.schemas import AppDownloadOut, AutomationSummary, DownloadOut

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
    automation_id: str, request: Request, catalog: CatalogDep, storage: StorageDep
) -> DownloadOut:
    """Short-lived links to the latest published build (no login: ready-made apps are free)."""
    if catalog.get(automation_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "automation not found")
    entry = (await storage.catalog_manifest()).get(automation_id) if storage else None
    if not entry:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "downloads are not available yet")
    settings = request.app.state.settings
    secret = settings.download_token_secret.get_secret_value()
    pack = entry.get("pack")
    if pack and settings.download_worker_url and secret:
        # Runner + layers + signed pack, merged by the Worker (Phase 2b).
        guide = storage.link(f"{pack['prefix']}/Guide.pdf", filename="Guide.pdf", inline=True)
        return DownloadOut(
            version=entry["version"],
            filename=f"{pack['exe']}.zip",
            size_bytes=pack.get("size_bytes"),
            url=worker_link(settings.download_worker_url, secret, pack),
            guide_url=guide.url,
            expires_in=TOKEN_TTL_S,
            built_at=entry.get("built_at"),
        )
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


@router.get("/automations/{automation_id}/bundle")
async def bundle_automation(
    automation_id: str, request: Request, catalog: CatalogDep, storage: StorageDep
) -> DownloadOut:
    """Add to MakeMyEXE: the signed pack as a .mmx bundle for the installed app, streamed by
    the Worker (no login: ready-made apps are free; licenses come in phase 2e)."""
    if catalog.get(automation_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "automation not found")
    entry = (await storage.catalog_manifest()).get(automation_id) if storage else None
    pack = (entry or {}).get("pack")
    settings = request.app.state.settings
    secret = settings.download_token_secret.get_secret_value()
    worker = settings.download_worker_url
    if not (entry and pack and pack.get("bundle_bytes") and worker and secret):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "bundles are not available yet")
    guide = storage.link(f"{pack['prefix']}/Guide.pdf", filename="Guide.pdf", inline=True)
    return DownloadOut(
        version=entry["version"],
        filename=f"{pack['exe']}.mmx",
        size_bytes=pack["bundle_bytes"],
        url=bundle_link(worker, secret, pack),
        guide_url=guide.url,
        expires_in=TOKEN_TTL_S,
        built_at=entry.get("built_at"),
    )


@router.get("/app/latest")
async def latest_app(storage: StorageDep) -> AppDownloadOut:
    """ "Download MakeMyEXE": the latest released installer (app/latest.json in R2)."""
    latest = await storage.app_latest() if storage else None
    if latest is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "the app is not released yet")
    filename = latest["key"].rsplit("/", 1)[-1]
    link = storage.link(latest["key"], filename=filename)
    return AppDownloadOut(
        version=str(latest.get("version", "")),
        filename=filename,
        size_bytes=latest.get("size_bytes"),
        sha256=latest.get("sha256"),
        url=link.url,
        expires_in=link.expires_in,
    )
