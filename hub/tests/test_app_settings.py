from __future__ import annotations

from conftest import register_admin

SETTINGS_URL = "/api/v1/apps/cosecre-print/settings"


def test_an_app_can_store_and_read_back_its_settings(hub):
    client, _ = hub
    headers = register_admin(client)

    written = client.put(
        SETTINGS_URL,
        headers=headers,
        json={"defaultPrinter": "HP-4200", "concurrency": 4, "duplex": True},
    )
    assert written.status_code == 200
    assert written.json()["settings"]["concurrency"] == 4

    read = client.get(SETTINGS_URL, headers=headers)
    assert read.status_code == 200
    assert read.json() == {
        "app_slug": "cosecre-print",
        "settings": {"defaultPrinter": "HP-4200", "concurrency": 4, "duplex": True},
    }


def test_a_bundle_write_removes_keys_it_omits(hub):
    client, _ = hub
    headers = register_admin(client)
    client.put(SETTINGS_URL, headers=headers, json={"keep": 1, "drop": 2})

    client.put(SETTINGS_URL, headers=headers, json={"keep": 3})

    assert client.get(SETTINGS_URL, headers=headers).json()["settings"] == {"keep": 3}


def test_individual_keys_can_be_written_and_deleted(hub):
    client, _ = hub
    headers = register_admin(client)

    written = client.put(
        f"{SETTINGS_URL}/theme", headers=headers, json={"value": {"mode": "light"}}
    )
    assert written.status_code == 200
    assert written.json()["value"] == {"mode": "light"}

    assert client.get(f"{SETTINGS_URL}/theme", headers=headers).status_code == 200
    assert client.delete(f"{SETTINGS_URL}/theme", headers=headers).status_code == 200
    assert client.get(f"{SETTINGS_URL}/theme", headers=headers).status_code == 404


def test_settings_are_namespaced_per_app(hub):
    client, _ = hub
    headers = register_admin(client)

    client.put(SETTINGS_URL, headers=headers, json={"shared": "print"})
    client.put("/api/v1/apps/cosecre-desktop/settings", headers=headers, json={"shared": "desktop"})

    assert client.get(SETTINGS_URL, headers=headers).json()["settings"] == {"shared": "print"}
    assert client.get("/api/v1/apps/cosecre-desktop/settings", headers=headers).json()[
        "settings"
    ] == {"shared": "desktop"}


def test_registered_apps_are_discoverable(hub):
    client, _ = hub
    headers = register_admin(client)
    client.put(SETTINGS_URL, headers=headers, json={"anything": True})

    apps = client.get("/api/v1/apps", headers=headers).json()

    # The documents module is always present; anything with stored settings joins it.
    assert "cosecre-docs" in apps
    assert "cosecre-print" in apps
    assert apps == sorted(apps)


def test_writes_require_an_admin_but_reads_do_not(hub):
    client, _ = hub
    admin_headers = register_admin(client)
    client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={"email": "staff@example.com", "password": "staff-password"},
    )
    staff_token = client.post(
        "/api/v1/auth/login", json={"email": "staff@example.com", "password": "staff-password"}
    ).json()["access_token"]
    staff_headers = {"Authorization": f"Bearer {staff_token}"}
    client.put(SETTINGS_URL, headers=admin_headers, json={"readable": True})

    assert client.get(SETTINGS_URL, headers=staff_headers).status_code == 200
    assert client.put(SETTINGS_URL, headers=staff_headers, json={"nope": 1}).status_code == 403


def test_slugs_and_keys_are_validated(hub):
    client, _ = hub
    headers = register_admin(client)

    assert client.get("/api/v1/apps/Not_A_Slug/settings", headers=headers).status_code == 422
    assert (
        client.put(SETTINGS_URL, headers=headers, json={"has spaces": 1}).status_code == 422
    )
