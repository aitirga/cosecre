from __future__ import annotations

from conftest import ADMIN_PASSWORD, register_admin


def test_admin_creates_an_account_that_can_sign_in(hub):
    client, _ = hub
    headers = register_admin(client)

    created = client.post(
        "/api/v1/users",
        headers=headers,
        json={"email": "staff@example.com", "password": "staff-password", "display_name": "Staff"},
    )
    assert created.status_code == 201
    assert created.json()["is_admin"] is False

    login = client.post(
        "/api/v1/auth/login", json={"email": "staff@example.com", "password": "staff-password"}
    )
    assert login.status_code == 200
    assert login.json()["user"]["display_name"] == "Staff"


def test_non_admins_cannot_manage_accounts(hub):
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

    assert client.get("/api/v1/users", headers=staff_headers).status_code == 403
    assert (
        client.post(
            "/api/v1/users",
            headers=staff_headers,
            json={"email": "another@example.com", "password": "another-password"},
        ).status_code
        == 403
    )


def test_disabling_an_account_takes_effect_immediately(hub):
    client, _ = hub
    admin_headers = register_admin(client)
    staff = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={"email": "staff@example.com", "password": "staff-password"},
    ).json()
    staff_token = client.post(
        "/api/v1/auth/login", json={"email": "staff@example.com", "password": "staff-password"}
    ).json()["access_token"]
    staff_headers = {"Authorization": f"Bearer {staff_token}"}
    assert client.get("/api/v1/auth/me", headers=staff_headers).status_code == 200

    disabled = client.delete(f"/api/v1/users/{staff['id']}", headers=admin_headers)
    assert disabled.status_code == 200

    # The access token is still cryptographically valid — the check has to happen
    # per request, not only at sign-in.
    assert client.get("/api/v1/auth/me", headers=staff_headers).status_code == 403
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "staff@example.com", "password": "staff-password"},
        ).status_code
        == 403
    )


def test_the_last_admin_cannot_be_demoted(hub):
    client, _ = hub
    headers = register_admin(client)
    admins = [user for user in client.get("/api/v1/users", headers=headers).json() if user["is_admin"]]
    assert len(admins) == 1

    response = client.patch(
        f"/api/v1/users/{admins[0]['id']}", headers=headers, json={"is_admin": False}
    )

    assert response.status_code == 400
    assert "last administrator" in response.json()["detail"]


def test_an_admin_cannot_disable_themselves(hub):
    client, _ = hub
    headers = register_admin(client)
    me = client.get("/api/v1/auth/me", headers=headers).json()

    assert client.delete(f"/api/v1/users/{me['id']}", headers=headers).status_code == 400
    assert (
        client.patch(
            f"/api/v1/users/{me['id']}", headers=headers, json={"is_active": False}
        ).status_code
        == 400
    )


def test_an_admin_reset_password_replaces_the_old_one(hub):
    client, _ = hub
    admin_headers = register_admin(client)
    staff = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={"email": "staff@example.com", "password": "staff-password"},
    ).json()

    reset = client.patch(
        f"/api/v1/users/{staff['id']}", headers=admin_headers, json={"password": ADMIN_PASSWORD}
    )
    assert reset.status_code == 200

    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "staff@example.com", "password": "staff-password"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "staff@example.com", "password": ADMIN_PASSWORD},
        ).status_code
        == 200
    )
