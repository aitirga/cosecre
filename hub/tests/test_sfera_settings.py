import pytest
from conftest import register_admin

URL = "/api/v1/apps/cosecre-sfera/settings"


def test_sfera_shared_configuration_and_admin_permissions(hub):
    client, _ = hub
    admin = register_admin(client)
    data = {"access_url": "https://portal.example.org/", "centre": "Centre de prova"}
    assert client.put(URL, headers=admin, json=data).json()["settings"] == data
    client.post("/api/v1/users", headers=admin, json={"email": "staff@example.org", "password": "staff-password"})
    token = client.post("/api/v1/auth/login", json={"email": "staff@example.org", "password": "staff-password"}).json()["access_token"]
    staff = {"Authorization": f"Bearer {token}"}
    assert client.get(URL, headers=staff).json()["settings"] == data
    assert client.put(URL, headers=staff, json=data).status_code == 403
    assert client.get(URL).status_code == 401
    assert client.put(URL, headers=admin, json={"access_url": "", "centre": ""}).status_code == 200


@pytest.mark.parametrize("value", ["file:///tmp/portal", "javascript:alert(1)", "http://portal.example.org", "https://user:password@portal.example.org", "https://portal.example.org/?token=secret", "https://portal.example.org/?code=secret", "https://portal.example.org:invalid", "https://portal invalid.example.org/", 123])
def test_sfera_rejects_unsafe_urls_on_both_write_endpoints(hub, value):
    client, _ = hub
    admin = register_admin(client)
    assert client.put(URL, headers=admin, json={"access_url": value}).status_code == 422
    assert client.put(URL + "/access_url", headers=admin, json={"value": value}).status_code == 422


def test_sfera_rejects_secrets_and_keeps_previous_settings(hub):
    client, _ = hub
    admin = register_admin(client)
    good = {"access_url": "http://127.0.0.1:8765", "centre": "Prova"}
    assert client.put(URL, headers=admin, json=good).status_code == 200
    assert client.put(URL, headers=admin, json={"password": "never-store"}).status_code == 422
    assert client.put(URL + "/password", headers=admin, json={"value": "never-store"}).status_code == 422
    assert client.get(URL + "/password", headers=admin).status_code == 422
    assert client.get(URL, headers=admin).json()["settings"] == good
