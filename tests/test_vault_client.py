import pytest

from app.config import Settings
from app.vault_client import VaultAuthError, VaultClient


def test_token_auth_requires_token_to_be_set():
    settings = Settings(api_bearer_token="x", vault_auth_method="token", vault_token=None)
    client = VaultClient(settings)
    with pytest.raises(VaultAuthError, match="vault_token"):
        client.authenticate()


def test_kubernetes_auth_requires_role_to_be_set():
    settings = Settings(api_bearer_token="x", vault_auth_method="kubernetes", vault_k8s_role=None)
    client = VaultClient(settings)
    with pytest.raises(VaultAuthError, match="vault_k8s_role"):
        client.authenticate()


def test_kubernetes_auth_requires_service_account_token_file(tmp_path):
    missing = tmp_path / "does-not-exist"
    settings = Settings(
        api_bearer_token="x",
        vault_auth_method="kubernetes",
        vault_k8s_role="vaultly-app",
        vault_k8s_sa_token_path=str(missing),
    )
    client = VaultClient(settings)
    with pytest.raises(VaultAuthError, match="Service account token not found"):
        client.authenticate()
