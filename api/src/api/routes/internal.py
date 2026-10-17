"""Callbacks from routines and from the Windows build workflow (docs/ROUTINES.md §4)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import ValidationError

from api.jobs import JobConflict, JobNotFound
from api.routes.deps import Jobs, Session
from api.schemas import BuildCallback, RoutineCallback
from api.security import verify_callback_token, verify_signature

router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)


@router.post("/routine-callback", status_code=status.HTTP_204_NO_CONTENT)
async def routine_callback(
    body: RoutineCallback, request: Request, jobs: Jobs, session: Session
) -> Response:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    secret = request.app.state.settings.callback_token_secret.get_secret_value()
    if scheme.lower() != "bearer" or not verify_callback_token(secret, body.job_id, token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad callback token")
    try:
        await jobs.on_routine_callback(session, body.model_dump())
    except JobNotFound as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found") from err
    except JobConflict as err:
        raise HTTPException(status.HTTP_409_CONFLICT, str(err)) from err
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/build-callback", status_code=status.HTTP_204_NO_CONTENT)
async def build_callback(request: Request, jobs: Jobs, session: Session) -> Response:
    # The signature covers the raw body, so verify before parsing it.
    raw = await request.body()
    secret = request.app.state.settings.build_callback_secret.get_secret_value()
    if not verify_signature(secret, raw, request.headers.get("X-Signature")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad signature")
    try:
        body = BuildCallback.model_validate_json(raw)
    except ValidationError as err:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, err.errors()) from err
    try:
        await jobs.on_build_callback(session, body.model_dump())
    except JobNotFound as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found") from err
    except JobConflict as err:
        raise HTTPException(status.HTTP_409_CONFLICT, str(err)) from err
    return Response(status_code=status.HTTP_204_NO_CONTENT)
