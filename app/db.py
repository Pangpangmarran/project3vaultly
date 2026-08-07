from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from app.vault_client import SecretNotFoundError, VaultClient

logger = logging.getLogger("vaultly.db")


@dataclass
class DBCredentialState:
    """Live-updatable view of the app's own database credential.

    This is the rotation demo: a background poller re-reads
    `db_secret_path` from Vault on an interval and swaps this state in
    place. Nothing that holds a reference to `DBCredentialState` needs to
    restart when the password changes in Vault -- it just sees the new
    value on the next read.
    """

    username: str | None = None
    password: str | None = None
    version: int = 0
    rotated_at: datetime | None = None

    def apply(self, username: str, password: str) -> bool:
        """Update state if the credential actually changed. Returns True on rotation."""
        if username == self.username and password == self.password:
            return False
        self.username = username
        self.password = password
        self.version += 1
        self.rotated_at = datetime.now(UTC)
        return True

    def public_status(self) -> dict:
        """Status view safe to expose over the API -- never includes the password."""
        return {
            "username": self.username,
            "version": self.version,
            "rotated_at": self.rotated_at.isoformat() if self.rotated_at else None,
        }


class CredentialRotator:
    """Polls Vault for DB credential changes and applies them to shared state."""

    def __init__(self, vault_client: VaultClient, secret_path: str, poll_interval_seconds: float):
        self._vault_client = vault_client
        self._secret_path = secret_path
        self._poll_interval_seconds = poll_interval_seconds
        self.state = DBCredentialState()
        self._task: asyncio.Task | None = None

    def refresh_once(self) -> bool:
        try:
            secret = self._vault_client.read_secret(self._secret_path)
        except SecretNotFoundError:
            logger.warning("DB credential secret not found at path=%s", self._secret_path)
            return False

        rotated = self.state.apply(username=secret.get("username"), password=secret.get("password"))
        if rotated:
            logger.info(
                "Database credential rotated without restart (version=%d, username=%s)",
                self.state.version,
                self.state.username,
            )
        return rotated

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._poll_interval_seconds)
            try:
                await asyncio.to_thread(self.refresh_once)
            except Exception:  # noqa: BLE001 - keep polling even if one cycle fails
                logger.exception("DB credential refresh cycle failed")

    def start(self) -> None:
        self.refresh_once()
        self._task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
