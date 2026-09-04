from __future__ import annotations

import os
import uuid

import hvac
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

VAULT_ADDR = os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200")
VAULT_TOKEN = os.environ.get("VAULT_TOKEN", "vaultly-dev-root-token")
API_TOKEN = "test-bearer-token"


def _vault_reachable() -> bool:
    try:
        client = hvac.Client(url=VAULT_ADDR, token=VAULT_TOKEN)
        return bool(client.sys.is_initialized())
    except Exception:
        return False


requires_vault = pytest.mark.skipif(
    not _vault_reachable(),
    reason=(
        f"No Vault dev server reachable at {VAULT_ADDR}. Start one with: "
        "docker run --rm -d -p 8200:8200 -e VAULT_DEV_ROOT_TOKEN_ID=vaultly-dev-root-token "
        "hashicorp/vault server -dev"
    ),
)


@pytest.fixture
def settings() -> Settings:
    unique = uuid.uuid4().hex[:8]
    return Settings(
        vault_addr=VAULT_ADDR,
        vault_auth_method="token",
        vault_token=VAULT_TOKEN,
        vault_kv_mount="secret",
        api_bearer_token=API_TOKEN,
        db_secret_path=f"vaultly-tests/{unique}/database",
        rotation_poll_interval_seconds=3600,
    )


@pytest.fixture
def client(settings: Settings):
    app = create_app(settings)
    with TestClient(app) as test_client:
        test_client.headers.update({"Authorization": f"Bearer {API_TOKEN}"})
        yield test_client
