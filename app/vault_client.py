from __future__ import annotations

import logging
from pathlib import Path

import hvac
from hvac.exceptions import InvalidPath

from app.config import Settings

logger = logging.getLogger("vaultly.vault_client")


class VaultAuthError(RuntimeError):
    """Raised when Vaultly cannot authenticate to Vault."""


class SecretNotFoundError(KeyError):
    """Raised when a requested secret path does not exist."""


class VaultClient:
    """Thin wrapper around hvac that owns authentication and KV v2 access.

    Two auth methods are supported:
      * kubernetes (default) -- exchanges the pod's projected service account
        JWT for a Vault token via the Kubernetes auth method. No long-lived
        credential is ever stored by the app.
      * token -- a static Vault token supplied via VAULTLY_VAULT_TOKEN, for
        local development against `vault server -dev` only.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = hvac.Client(url=settings.vault_addr, namespace=settings.vault_namespace)

    def authenticate(self) -> None:
        method = self._settings.vault_auth_method
        if method == "kubernetes":
            self._authenticate_kubernetes()
        elif method == "token":
            self._authenticate_token()
        else:  # pragma: no cover - guarded by pydantic Literal
            raise VaultAuthError(f"Unsupported vault_auth_method: {method}")

        if not self._client.is_authenticated():
            raise VaultAuthError("Vault authentication did not produce a valid token")

    def _authenticate_kubernetes(self) -> None:
        token_path = Path(self._settings.vault_k8s_sa_token_path)
        if not self._settings.vault_k8s_role:
            raise VaultAuthError("vault_k8s_role must be set when vault_auth_method=kubernetes")
        if not token_path.exists():
            raise VaultAuthError(
                f"Service account token not found at {token_path}. "
                "Is this pod running with a projected service account?"
            )
        jwt = token_path.read_text().strip()
        self._client.auth.kubernetes.login(
            role=self._settings.vault_k8s_role,
            jwt=jwt,
            mount_point=self._settings.vault_k8s_mount_point,
        )
        logger.info(
            "Authenticated to Vault via Kubernetes auth method (role=%s)",
            self._settings.vault_k8s_role,
        )

    def _authenticate_token(self) -> None:
        if not self._settings.vault_token:
            raise VaultAuthError("vault_token must be set when vault_auth_method=token")
        logger.warning(
            "Authenticating to Vault with a static token. This is only acceptable for local "
            "development -- production deployments must use vault_auth_method=kubernetes."
        )
        self._client.token = self._settings.vault_token

    def is_authenticated(self) -> bool:
        try:
            return bool(self._client.is_authenticated())
        except Exception:  # noqa: BLE001 - readiness probe must not raise
            return False

    def read_secret(self, path: str) -> dict:
        try:
            response = self._client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=self._settings.vault_kv_mount,
                raise_on_deleted_version=True,
            )
        except InvalidPath as exc:
            raise SecretNotFoundError(path) from exc
        return response["data"]["data"]

    def write_secret(self, path: str, data: dict) -> None:
        self._client.secrets.kv.v2.create_or_update_secret(
            path=path,
            secret=data,
            mount_point=self._settings.vault_kv_mount,
        )
        logger.info("Wrote secret at path=%s (keys=%s)", path, sorted(data.keys()))

    def delete_secret(self, path: str) -> None:
        self._client.secrets.kv.v2.delete_metadata_and_all_versions(
            path=path,
            mount_point=self._settings.vault_kv_mount,
        )
        logger.info("Deleted all versions of secret at path=%s", path)
