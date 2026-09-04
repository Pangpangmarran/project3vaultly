from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request

from app.config import Settings
from app.db import CredentialRotator
from app.models import (
    DBStatusResponse,
    HealthResponse,
    ReadyResponse,
    SecretResponse,
    SecretWriteRequest,
)
from app.security import require_api_token
from app.vault_client import SecretNotFoundError, VaultClient

logger = logging.getLogger("vaultly")


def get_vault_client(request: Request) -> VaultClient:
    return request.app.state.vault_client


def get_rotator(request: Request) -> CredentialRotator:
    return request.app.state.rotator


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(level=settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        vault_client = VaultClient(settings)
        vault_client.authenticate()

        rotator = CredentialRotator(
            vault_client=vault_client,
            secret_path=settings.db_secret_path,
            poll_interval_seconds=settings.rotation_poll_interval_seconds,
        )
        rotator.start()

        app.state.settings = settings
        app.state.vault_client = vault_client
        app.state.rotator = rotator
        try:
            yield
        finally:
            await rotator.stop()

    app = FastAPI(
        title="Vaultly",
        description="A minimal secrets API wrapper around HashiCorp Vault.",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/healthz", response_model=HealthResponse, tags=["ops"])
    def healthz() -> HealthResponse:
        """Liveness probe. Always returns ok if the process is up."""
        return HealthResponse(status="ok")

    @app.get("/readyz", response_model=ReadyResponse, tags=["ops"])
    def readyz(vault_client: VaultClient = Depends(get_vault_client)) -> ReadyResponse:
        """Readiness probe. Fails if Vaultly has lost its Vault session."""
        authenticated = vault_client.is_authenticated()
        if not authenticated:
            raise HTTPException(status_code=503, detail="Not authenticated to Vault")
        return ReadyResponse(status="ok", vault_authenticated=authenticated)

    @app.get(
        "/api/v1/secrets/{path:path}",
        response_model=SecretResponse,
        dependencies=[Depends(require_api_token)],
        tags=["secrets"],
    )
    def read_secret(path: str, vault_client: VaultClient = Depends(get_vault_client)) -> SecretResponse:
        try:
            data = vault_client.read_secret(path)
        except SecretNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"No secret at path '{path}'") from exc
        return SecretResponse(path=path, data=data)

    @app.put(
        "/api/v1/secrets/{path:path}",
        status_code=204,
        dependencies=[Depends(require_api_token)],
        tags=["secrets"],
    )
    def write_secret(
        path: str, body: SecretWriteRequest, vault_client: VaultClient = Depends(get_vault_client)
    ) -> None:
        vault_client.write_secret(path, body.root)

    @app.delete(
        "/api/v1/secrets/{path:path}",
        status_code=204,
        dependencies=[Depends(require_api_token)],
        tags=["secrets"],
    )
    def delete_secret(path: str, vault_client: VaultClient = Depends(get_vault_client)) -> None:
        vault_client.delete_secret(path)

    @app.get(
        "/api/v1/db/status",
        response_model=DBStatusResponse,
        dependencies=[Depends(require_api_token)],
        tags=["rotation-demo"],
    )
    def db_status(rotator: CredentialRotator = Depends(get_rotator)) -> DBStatusResponse:
        """Shows the currently active DB credential version/username.

        Demonstrates that changing the secret in Vault is picked up here
        without restarting the process -- the password itself is never
        returned by this endpoint.
        """
        return DBStatusResponse(**rotator.state.public_status())

    return app
