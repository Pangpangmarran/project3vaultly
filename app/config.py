from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Vaultly runtime configuration.

    Every field is sourced from the environment (or a local `.env` file for
    dev). Nothing here is a hardcoded secret: `vault_token` only makes sense
    in the `token` auth method, which is itself gated to non-production use.
    """

    model_config = SettingsConfigDict(env_prefix="VAULTLY_", env_file=".env", extra="ignore")

    # --- Vault connection ---
    vault_addr: str = "http://127.0.0.1:8200"
    vault_namespace: str | None = None
    vault_kv_mount: str = "secret"

    # --- Vault authentication ---
    # "kubernetes" logs in with the pod's projected service account JWT via
    # Vault's Kubernetes auth method. "token" is a static-token fallback for
    # local development ONLY and is never appropriate in a deployed cluster
    # (see project.md requirement: "no static tokens").
    vault_auth_method: Literal["kubernetes", "token"] = "kubernetes"
    vault_token: str | None = None
    vault_k8s_role: str | None = None
    vault_k8s_mount_point: str = "kubernetes"
    vault_k8s_sa_token_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/token"

    # --- Vaultly's own API auth ---
    # A single shared bearer token, intentionally minimal. Production
    # deployments are expected to front this with proper IAM/mTLS/RBAC —
    # see README "Security model & what this app deliberately does not do".
    api_bearer_token: str = Field(..., description="Bearer token required on every /api/v1 request")

    # --- Rotation demo (database credentials) ---
    db_secret_path: str = "vaultly/database"
    rotation_poll_interval_seconds: float = 30.0

    log_level: str = "INFO"
