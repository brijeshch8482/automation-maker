"""User auth: Supabase access tokens. Catalog routes need no login.

New Supabase projects sign access tokens with asymmetric keys (RS256 / ES256). We verify them with
the project's public keys from {SUPABASE_URL}/auth/v1/.well-known/jwks.json, cached in memory and
refetched when a token names a key we haven't seen (key rotation). Legacy projects that still sign
with a shared secret (HS256) work only when SUPABASE_JWT_SECRET is set.
"""

from __future__ import annotations

from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status

from api.config import Settings

DEV_PREFIX = "dev:"
ASYMMETRIC_ALGORITHMS = ["RS256", "ES256"]
JWKS_CACHE_SECONDS = 3600
REQUIRED_CLAIMS = ["sub", "exp", "aud"]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


def jwks_url(supabase_url: str) -> str:
    return f"{supabase_url}/auth/v1/.well-known/jwks.json"


class TokenVerifier:
    def __init__(self, settings: Settings, jwks_client: jwt.PyJWKClient | None = None) -> None:
        self.dev_auth = settings.dev_auth
        self.audience = settings.supabase_jwt_audience
        self.issuer = f"{settings.supabase_url}/auth/v1" if settings.supabase_url else None
        self.legacy_secret = settings.supabase_jwt_secret.get_secret_value()
        if jwks_client is None and settings.supabase_url:
            jwks_client = jwt.PyJWKClient(
                jwks_url(settings.supabase_url),
                cache_keys=True,
                cache_jwk_set=True,
                lifespan=JWKS_CACHE_SECONDS,
                timeout=10,
            )
        self.jwks = jwks_client

    def user_id(self, token: str) -> str:
        if self.dev_auth and token.startswith(DEV_PREFIX):
            user = token.removeprefix(DEV_PREFIX)
            if not user:
                raise _unauthorized("empty dev user")
            return user

        try:
            algorithm = jwt.get_unverified_header(token).get("alg")
        except jwt.PyJWTError as err:
            raise _unauthorized("invalid token") from err

        if algorithm in ASYMMETRIC_ALGORITHMS:
            claims = self._verify_asymmetric(token)
        elif algorithm == "HS256" and self.legacy_secret:
            claims = self._decode(token, self.legacy_secret, ["HS256"])
        elif self.jwks is None and not self.legacy_secret:
            raise _unauthorized("login is not configured")
        else:
            raise _unauthorized("unsupported token")
        return str(claims["sub"])

    def _verify_asymmetric(self, token: str) -> dict[str, Any]:
        if self.jwks is None:
            raise _unauthorized("login is not configured")
        try:
            key = self.jwks.get_signing_key_from_jwt(token).key
        except jwt.PyJWKClientConnectionError as err:
            # Supabase unreachable: not the user's fault, so don't send them to log in again.
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "can't check the login right now; try again"
            ) from err
        except jwt.PyJWTError as err:  # unknown key id, malformed token
            raise _unauthorized("invalid token") from err
        return self._decode(token, key, ASYMMETRIC_ALGORITHMS)

    def _decode(self, token: str, key: Any, algorithms: list[str]) -> dict[str, Any]:
        required = REQUIRED_CLAIMS + (["iss"] if self.issuer else [])
        try:
            return jwt.decode(
                token,
                key,
                algorithms=algorithms,
                audience=self.audience,
                issuer=self.issuer,
                options={"require": required},
                leeway=30,  # small clock skew between Supabase and Render
            )
        except jwt.PyJWTError as err:
            raise _unauthorized("invalid or expired token") from err


def current_user(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized("login required")
    verifier: TokenVerifier = request.app.state.auth
    return verifier.user_id(token)


CurrentUser = Annotated[str, Depends(current_user)]
