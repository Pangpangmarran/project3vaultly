from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings

_bearer_scheme = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def require_api_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    """Gate every /api/v1 route behind a shared bearer token.

    This is intentionally minimal: Vaultly is a demo secrets wrapper, not a
    multi-tenant broker. Real deployments should front it with proper
    per-client identity (mTLS, OIDC, K8s NetworkPolicy) rather than relying
    on this alone -- see README "Security model".
    """
    if credentials is None or not secrets.compare_digest(credentials.credentials, settings.api_bearer_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
