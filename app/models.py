from __future__ import annotations

from pydantic import BaseModel, RootModel


class SecretWriteRequest(RootModel[dict[str, str]]):
    """Arbitrary string key/value pairs to store at a secret path."""


class SecretResponse(BaseModel):
    path: str
    data: dict[str, str]


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str
    vault_authenticated: bool


class DBStatusResponse(BaseModel):
    username: str | None
    version: int
    rotated_at: str | None
