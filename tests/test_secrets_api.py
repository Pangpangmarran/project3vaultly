from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import requires_vault

pytestmark = requires_vault


def test_write_then_read_secret(client: TestClient):
    path = "app-config/widget"
    write = client.put(f"/api/v1/secrets/{path}", json={"api_key": "abc123"})
    assert write.status_code == 204

    read = client.get(f"/api/v1/secrets/{path}")
    assert read.status_code == 200
    assert read.json() == {"path": path, "data": {"api_key": "abc123"}}


def test_read_missing_secret_returns_404(client: TestClient):
    response = client.get("/api/v1/secrets/does/not/exist")
    assert response.status_code == 404


def test_delete_secret(client: TestClient):
    path = "app-config/to-delete"
    client.put(f"/api/v1/secrets/{path}", json={"k": "v"})

    delete = client.delete(f"/api/v1/secrets/{path}")
    assert delete.status_code == 204

    read = client.get(f"/api/v1/secrets/{path}")
    assert read.status_code == 404


def test_missing_bearer_token_is_rejected(settings):
    app = create_app(settings)
    with TestClient(app) as anon_client:
        response = anon_client.get("/api/v1/secrets/whatever")
    assert response.status_code == 401


def test_wrong_bearer_token_is_rejected(settings):
    app = create_app(settings)
    with TestClient(app) as anon_client:
        anon_client.headers.update({"Authorization": "Bearer wrong-token"})
        response = anon_client.get("/api/v1/secrets/whatever")
    assert response.status_code == 401
