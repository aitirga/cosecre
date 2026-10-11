"""Accounts are enabled by e-mail; their owner chooses the password on first sign-in."""

from __future__ import annotations

from conftest import register_admin

API = "/api/v1"


def _enable(client, admin, email="teacher@example.com", role="professor"):
    response = client.post(
        f"{API}/users", headers=admin, json={"email": email, "display_name": "Mestra", "role": role}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _choose(client, email="teacher@example.com", password="my-own-password"):
    return client.post(f"{API}/auth/activate", json={"email": email, "password": password})


def test_an_enabled_account_asks_for_a_password_on_first_sign_in(hub):
    client, _ = hub
    admin = register_admin(client)
    user = _enable(client, admin)

    assert user["status"] == "pending"
    assert user["role"] == "professor"

    login = client.post(f"{API}/auth/login", json={"email": "teacher@example.com", "password": ""})
    assert login.status_code == 409
    assert login.json()["code"] == "password_not_set"


def test_choosing_the_password_opens_the_account_once(hub):
    client, _ = hub
    admin = register_admin(client)
    _enable(client, admin)

    activated = _choose(client)
    assert activated.status_code == 200
    assert activated.json()["user"]["status"] == "active"

    # Once chosen, nobody else can choose it again.
    assert _choose(client, password="another-one").status_code == 400
    login = client.post(
        f"{API}/auth/login", json={"email": "teacher@example.com", "password": "my-own-password"}
    )
    assert login.status_code == 200


def test_only_enabled_addresses_can_choose_a_password(hub):
    client, _ = hub
    admin = register_admin(client)
    assert _choose(client, email="stranger@example.com").status_code == 400

    user = _enable(client, admin)
    client.patch(f"{API}/users/{user['id']}", headers=admin, json={"is_active": False})
    assert _choose(client).status_code == 400


def test_resetting_forgets_the_password_and_signs_it_out(hub):
    client, _ = hub
    admin = register_admin(client)
    _enable(client, admin)
    tokens = _choose(client).json()
    user_id = tokens["user"]["id"]

    reset = client.post(f"{API}/users/{user_id}/reset", headers=admin)
    assert reset.status_code == 200
    assert reset.json()["status"] == "pending"

    assert client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    old_password = client.post(
        f"{API}/auth/login", json={"email": "teacher@example.com", "password": "my-own-password"}
    )
    assert old_password.status_code == 409
    assert _choose(client, password="a-new-password").status_code == 200


def test_removing_a_never_used_account_deletes_it_and_a_used_one_is_disabled(hub):
    client, _ = hub
    admin = register_admin(client)
    pending = _enable(client, admin, email="pending@example.com")
    used = _enable(client, admin, email="used@example.com")
    _choose(client, email="used@example.com")

    assert client.delete(f"{API}/users/{pending['id']}", headers=admin).status_code == 200
    assert client.delete(f"{API}/users/{used['id']}", headers=admin).status_code == 200

    users = {u["email"]: u for u in client.get(f"{API}/users", headers=admin).json()}
    assert "pending@example.com" not in users
    assert users["used@example.com"]["status"] == "disabled"


def test_the_last_admin_cannot_be_demoted(hub):
    client, _ = hub
    admin = register_admin(client)
    me = client.get(f"{API}/auth/me", headers=admin).json()
    response = client.patch(f"{API}/users/{me['id']}", headers=admin, json={"role": "secretaria"})
    assert response.status_code == 400
