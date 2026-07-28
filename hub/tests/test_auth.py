from __future__ import annotations

import json
from pathlib import Path

from conftest import ADMIN_EMAIL, ADMIN_PASSWORD, build_client, register_admin


def test_register_login_and_me(hub):
    client, _ = hub

    register = client.post(
        "/api/v1/auth/register",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert register.status_code == 201
    assert register.json()["user"]["is_admin"] is True
    assert register.json()["expires_in"] > 0

    login = client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "client": "desktop"},
    )
    assert login.status_code == 200
    access_token = login.json()["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me.status_code == 200
    assert me.json()["email"] == ADMIN_EMAIL
    assert me.json()["last_login_at"] is not None


def test_login_rejects_a_wrong_password_without_revealing_the_account(hub):
    client, _ = hub
    register_admin(client)

    wrong_password = client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "not-the-password"}
    )
    unknown_email = client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": ADMIN_PASSWORD}
    )

    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert wrong_password.json()["detail"] == unknown_email.json()["detail"]


def test_registration_closes_after_the_first_account(hub):
    client, _ = hub
    register_admin(client)

    second = client.post(
        "/api/v1/auth/register",
        json={"email": "someone@example.com", "password": ADMIN_PASSWORD},
    )

    assert second.status_code == 403
    assert "closed" in second.json()["detail"].lower()


def test_open_registration_can_be_enabled(tmp_path: Path):
    client, _ = build_client(tmp_path, allow_open_registration=True)
    with client:
        register_admin(client)
        second = client.post(
            "/api/v1/auth/register",
            json={"email": "someone@example.com", "password": ADMIN_PASSWORD},
        )
        assert second.status_code == 201
        # Only the very first account is made an admin.
        assert second.json()["user"]["is_admin"] is False


def test_refresh_rotates_and_spends_the_old_token(hub):
    client, _ = hub
    tokens = client.post(
        "/api/v1/auth/register",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "client": "web"},
    ).json()

    refreshed = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] != tokens["refresh_token"]

    replayed = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert replayed.status_code == 401


def test_logout_revokes_only_that_session(hub):
    client, _ = hub
    first = client.post(
        "/api/v1/auth/register",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "client": "web"},
    ).json()
    second = client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "client": "desktop"},
    ).json()

    assert client.post(
        "/api/v1/auth/logout", json={"refresh_token": first["refresh_token"]}
    ).status_code == 200

    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}
        ).status_code
        == 200
    )


def test_sessions_are_listed_per_client(hub):
    client, _ = hub
    headers = register_admin(client)
    client.post(
        "/api/v1/auth/login",
        json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
            "client": "desktop",
            "client_label": "Aitor's Mac",
        },
    )

    sessions = client.get("/api/v1/auth/sessions", headers=headers)

    assert sessions.status_code == 200
    clients = {item["client"] for item in sessions.json()}
    assert clients == {"pytest", "desktop"}


def test_changing_a_password_signs_other_sessions_out(hub):
    client, _ = hub
    headers = register_admin(client)
    other = client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "client": "desktop"},
    ).json()

    changed = client.post(
        "/api/v1/auth/password",
        headers=headers,
        json={"current_password": ADMIN_PASSWORD, "new_password": "an-even-better-password"},
    )
    assert changed.status_code == 200

    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": other["refresh_token"]}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": ADMIN_EMAIL, "password": "an-even-better-password"},
        ).status_code
        == 200
    )


def test_requests_without_a_token_are_rejected(hub):
    client, _ = hub
    register_admin(client)

    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/documents/invoices").status_code == 401


def test_bootstrap_admin_comes_from_the_environment(tmp_path: Path):
    client, _ = build_client(
        tmp_path,
        bootstrap_admin_email="owner@example.com",
        bootstrap_admin_password="bootstrapped-password",
    )
    with client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": "bootstrapped-password"},
        )
        assert login.status_code == 200
        assert login.json()["user"]["is_admin"] is True


def test_legacy_seed_file_still_provisions_accounts(tmp_path: Path):
    seed_file = tmp_path / "seed_users.json"
    seed_file.write_text(
        json.dumps([{"email": "seeded@example.com", "password": "seeded", "is_admin": True}]),
        encoding="utf-8",
    )

    client, _ = build_client(tmp_path, seed_users_file=seed_file)
    with client:
        login = client.post(
            "/api/v1/auth/login", json={"email": "seeded@example.com", "password": "seeded"}
        )
        assert login.status_code == 200
        assert login.json()["user"]["is_admin"] is True


def test_a_broken_seed_file_does_not_stop_the_hub(tmp_path: Path):
    seed_file = tmp_path / "seed_users.json"
    seed_file.write_text("{ not json at all", encoding="utf-8")

    client, _ = build_client(tmp_path, seed_users_file=seed_file)
    with client:
        assert client.get("/healthz").status_code == 200
