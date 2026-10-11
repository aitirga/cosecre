"""Who can reach what: the office's routes stay the office's."""

from __future__ import annotations

import re

from conftest import make_user, register_admin

API = "/api/v1"

#: Routes a Professor/a may call. Everything else must answer 403 — the test
#: walks the whole app, so a route added later without a role check fails here.
OPEN_TO_EVERYONE = (
    f"{API}/meta",
    f"{API}/auth/",
    f"{API}/users/me",
    # Every role's own corner; these check ownership themselves (see their tests).
    f"{API}/requests",
    f"{API}/notifications",
    f"{API}/submissions",
    # Reads none of the hub's data: it turns a question into the caller's own filters.
    f"{API}/ai-search",
)


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def test_a_professor_is_refused_everywhere_outside_their_corner(hub):
    client, _ = hub
    admin = register_admin(client)
    professor = make_user(client, admin, "professor")

    checked = 0
    # The OpenAPI document lists every route however the routers were included.
    for path, operations in client.app.openapi()["paths"].items():
        if not path.startswith(API) or path.startswith(OPEN_TO_EVERYONE):
            continue
        for method in operations:
            response = client.request(method.upper(), _concrete(path), headers=professor)
            assert response.status_code == 403, f"{method.upper()} {path} → {response.status_code}"
            checked += 1
    assert checked > 50


def test_secretaria_works_the_register_but_not_the_accounts(hub):
    client, _ = hub
    admin = register_admin(client)
    secretaria = make_user(client, admin, "secretaria")

    assert client.get(f"{API}/documents/records", headers=secretaria).status_code == 200
    assert client.get(f"{API}/statements/imports", headers=secretaria).status_code == 200
    assert client.get(f"{API}/users", headers=secretaria).status_code == 403
    assert (
        client.post(f"{API}/users", headers=secretaria, json={"email": "x@example.com"}).status_code
        == 403
    )


def test_the_role_travels_with_the_account(hub):
    client, _ = hub
    admin = register_admin(client)
    professor = make_user(client, admin, "professor")

    me = client.get(f"{API}/auth/me", headers=professor).json()
    assert me["role"] == "professor"
    assert me["is_admin"] is False
    assert me["status"] == "active"
    assert client.get(f"{API}/auth/me", headers=admin).json()["role"] == "admin"


def test_promoting_takes_effect_on_the_next_request(hub):
    client, _ = hub
    admin = register_admin(client)
    professor = make_user(client, admin, "professor")
    user_id = client.get(f"{API}/auth/me", headers=professor).json()["id"]
    assert client.get(f"{API}/documents/records", headers=professor).status_code == 403

    updated = client.patch(f"{API}/users/{user_id}", headers=admin, json={"role": "secretaria"})
    assert updated.status_code == 200
    assert updated.json()["role"] == "secretaria"
    assert client.get(f"{API}/documents/records", headers=professor).status_code == 200


def test_accounts_from_before_roles_keep_their_access(tmp_path):
    """A database written by an older hub: admins stay admins, members become Secretaria."""
    import sqlite3

    from conftest import build_client

    client, _ = build_client(tmp_path)
    with client:
        admin = register_admin(client)
        client.post(
            f"{API}/users",
            headers=admin,
            json={"email": "member@example.com", "password": "member-password"},
        )
        database = client.app.state.settings.database_url.removeprefix("sqlite:///")

    connection = sqlite3.connect(database)
    added = ("role", "password_set_at", "invite_token_hash", "invite_code_hash")
    for column in (*added, "invite_expires_at", "invite_attempts"):
        connection.execute(f"DROP INDEX IF EXISTS ix_users_{column}")
        connection.execute(f"ALTER TABLE users DROP COLUMN {column}")
    connection.commit()
    connection.close()

    client, _ = build_client(tmp_path)
    with client:
        token = client.post(
            f"{API}/auth/login", json={"email": "member@example.com", "password": "member-password"}
        ).json()["access_token"]
        member = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert member["role"] == "secretaria"
        assert member["status"] == "active"
        users = client.get(f"{API}/users", headers={"Authorization": f"Bearer {token}"})
        assert users.status_code == 403
        assert client.get(f"{API}/auth/me", headers=admin).json()["role"] == "admin"
