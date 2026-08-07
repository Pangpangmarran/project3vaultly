from app.db import CredentialRotator
from app.vault_client import VaultClient
from tests.conftest import requires_vault

pytestmark = requires_vault


def test_rotation_picks_up_change_without_restart(settings):
    vault_client = VaultClient(settings)
    vault_client.authenticate()
    vault_client.write_secret(settings.db_secret_path, {"username": "app_user", "password": "s3cret-v1"})

    rotator = CredentialRotator(vault_client, settings.db_secret_path, poll_interval_seconds=3600)

    assert rotator.refresh_once() is True
    assert rotator.state.version == 1
    assert rotator.state.username == "app_user"

    status = rotator.state.public_status()
    assert "password" not in status
    assert status["version"] == 1

    # Re-reading the same secret is not a rotation.
    assert rotator.refresh_once() is False
    assert rotator.state.version == 1

    # This is the requirement from project.md: change the secret in Vault,
    # and the running app picks up the new credential -- no restart, no
    # redeploy, just the next poll cycle.
    vault_client.write_secret(settings.db_secret_path, {"username": "app_user", "password": "s3cret-v2"})
    assert rotator.refresh_once() is True
    assert rotator.state.version == 2
    assert rotator.state.password == "s3cret-v2"


def test_rotation_handles_missing_secret_gracefully(settings):
    vault_client = VaultClient(settings)
    vault_client.authenticate()

    rotator = CredentialRotator(vault_client, settings.db_secret_path, poll_interval_seconds=3600)
    assert rotator.refresh_once() is False
    assert rotator.state.version == 0
