"""Accounts are enabled by e-mail and opened by their owner with a link or a code."""

from __future__ import annotations

from datetime import timedelta

from conftest import register_admin

from cosecre_hub.models import User
from cosecre_hub.security import utcnow

API = "/api/v1"


def _invite(client, admin, email="teacher@example.com", role="professor"):
    response = client.post(
        f"{API}/users", headers=admin, json={"email": email, "display_name": "Mestra", "role": role}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_an_invited_account_waits_for_its_owner(hub):
    client, _ = hub
    admin = register_admin(client)
    issued = _invite(client, admin)

    assert issued["user"]["status"] == "pending"
    assert issued["user"]["role"] == "professor"
    assert len(issued["code"]) == 6 and issued["code"].isdigit()
    assert issued["token"]

    login = client.post(f"{API}/auth/login", json={"email": "teacher@example.com", "password": ""})
    assert login.status_code == 403
    assert "activat" in login.json()["detail"]


def test_the_link_shows_who_it_is_for_and_opens_the_account(hub):
    client, _ = hub
    admin = register_admin(client)
    issued = _invite(client, admin)

    preview = client.get(f"{API}/auth/invite/{issued['token']}")
    assert preview.status_code == 200
    assert preview.json() == {"email": "teacher@example.com", "display_name": "Mestra", "role": "professor"}

    activated = client.post(
        f"{API}/auth/activate", json={"token": issued["token"], "password": "my-own-password"}
    )
    assert activated.status_code == 200
    assert activated.json()["user"]["status"] == "active"

    # Spent: the link no longer works, the chosen password does.
    assert client.get(f"{API}/auth/invite/{issued['token']}").status_code == 404
    again = client.post(f"{API}/auth/activate", json={"token": issued["token"], "password": "another-one"})
    assert again.status_code == 400
    login = client.post(
        f"{API}/auth/login", json={"email": "teacher@example.com", "password": "my-own-password"}
    )
    assert login.status_code == 200


def test_the_code_opens_it_too_but_only_a_few_guesses(hub):
    client, _ = hub
    admin = register_admin(client)
    issued = _invite(client, admin)
    wrong = "000000" if issued["code"] != "000000" else "111111"

    for _ in range(5):
        response = client.post(
            f"{API}/auth/activate",
            json={"email": "teacher@example.com", "code": wrong, "password": "my-own-password"},
        )
        assert response.status_code == 400

    # Five misses spend the invitation, even for the right code.
    right = client.post(
        f"{API}/auth/activate",
        json={"email": "teacher@example.com", "code": issued["code"], "password": "my-own-password"},
    )
    assert right.status_code == 400
    users = client.get(f"{API}/users", headers=admin).json()
    assert next(u for u in users if u["email"] == "teacher@example.com")["status"] == "expired"


def test_the_right_code_opens_the_account(hub):
    client, _ = hub
    admin = register_admin(client)
    issued = _invite(client, admin)
    response = client.post(
        f"{API}/auth/activate",
        json={"email": "teacher@example.com", "code": issued["code"], "password": "my-own-password"},
    )
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "professor"


def test_an_invitation_runs_out(hub):
    client, _ = hub
    admin = register_admin(client)
    issued = _invite(client, admin)

    session = client.app.state.session_factory()
    user = session.query(User).filter(User.email == "teacher@example.com").one()
    user.invite_expires_at = utcnow() - timedelta(minutes=1)
    session.commit()
    session.close()

    response = client.post(
        f"{API}/auth/activate", json={"token": issued["token"], "password": "my-own-password"}
    )
    assert response.status_code == 400


def test_reinviting_resets_the_account_and_signs_it_out(hub):
    client, _ = hub
    admin = register_admin(client)
    issued = _invite(client, admin)
    tokens = client.post(
        f"{API}/auth/activate", json={"token": issued["token"], "password": "my-own-password"}
    ).json()
    user_id = tokens["user"]["id"]

    reissued = client.post(f"{API}/users/{user_id}/invite", headers=admin)
    assert reissued.status_code == 200
    assert reissued.json()["user"]["status"] == "pending"

    assert client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    old_password = client.post(
        f"{API}/auth/login", json={"email": "teacher@example.com", "password": "my-own-password"}
    )
    assert old_password.status_code == 403
    reopened = client.post(
        f"{API}/auth/activate", json={"token": reissued.json()["token"], "password": "a-new-password"}
    )
    assert reopened.status_code == 200


def test_removing_a_never_used_invite_deletes_it_and_a_used_account_is_disabled(hub):
    client, _ = hub
    admin = register_admin(client)
    pending = _invite(client, admin, email="pending@example.com")
    used = _invite(client, admin, email="used@example.com")
    client.post(f"{API}/auth/activate", json={"token": used["token"], "password": "my-own-password"})

    assert client.delete(f"{API}/users/{pending['user']['id']}", headers=admin).status_code == 200
    assert client.delete(f"{API}/users/{used['user']['id']}", headers=admin).status_code == 200

    users = {u["email"]: u for u in client.get(f"{API}/users", headers=admin).json()}
    assert "pending@example.com" not in users
    assert users["used@example.com"]["status"] == "disabled"


def test_the_last_admin_cannot_be_demoted(hub):
    client, _ = hub
    admin = register_admin(client)
    me = client.get(f"{API}/auth/me", headers=admin).json()
    response = client.patch(f"{API}/users/{me['id']}", headers=admin, json={"role": "secretaria"})
    assert response.status_code == 400
