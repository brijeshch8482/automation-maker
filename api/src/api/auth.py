"""User auth: Supabase access tokens (HS256 JWT). Catalog routes need no login."""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status

from api.config import Settings

DEV_PREFIX = "dev:"


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


def user_id_from_token(token: str, settings: Settings) -> str:
    if settings.dev_auth and token.startswith(DEV_PREFIX):
        user = token.removeprefix(DEV_PREFIX)
        if not user:
            raise _unauthorized("empty dev user")
        return user

    secret = settings.supabase_jwt_secret.get_secret_value()
    if not secret:
        raise _unauthorized("login is not configured")
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=settings.supabase_jwt_audience,
            options={"require": ["sub", "exp"]},
        )
    except jwt.PyJWTError as err:
        raise _unauthorized("invalid or expired token") from err
    return str(claims["sub"])


def current_user(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized("login required")
    return user_id_from_token(token, request.app.state.settings)


CurrentUser = Annotated[str, Depends(current_user)]
