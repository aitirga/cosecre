"""AIM membership: who is a teacher, who is a student, who is neither."""

from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import register_admin

AIM = "/api/v1/aim"


def _create_user(client: TestClient, headers: dict[str, str], email: str) -> int:
    response = client.post(
        "/api/v1/users",
        headers=headers,
        json={"email": email, "password": "supersecure", "is_admin": False},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _sign_in(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "supersecure", "client": "pytest"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_a_hub_admin_is_a_teacher_without_being_granted_one(hub):
    """Otherwise the first install has nobody who can grant the first membership."""
    client, _ = hub
    headers = register_admin(client)

    body = client.get(f"{AIM}/me", headers=headers).json()

    assert body["role"] == "teacher"
    assert body["implicit"] is True
    assert body["is_hub_admin"] is True


def test_an_ordinary_user_has_no_aim_role_at_all(hub):
    """A null role is an answer, not an error — the client hides AIM entirely."""
    client, _ = hub
    admin = register_admin(client)
    _create_user(client, admin, "clerk@example.com")

    body = client.get(f"{AIM}/me", headers=_sign_in(client, "clerk@example.com")).json()

    assert body["role"] is None
    assert body["implicit"] is False


def test_an_explicit_row_beats_the_hub_admin_default(hub):
    client, _ = hub
    admin = register_admin(client)
    admin_id = client.get("/api/v1/users/me", headers=admin).json()["id"]

    client.put(f"{AIM}/members/{admin_id}", headers=admin, json={"role": "student"})

    body = client.get(f"{AIM}/me", headers=admin).json()
    assert body["role"] == "student"
    assert body["implicit"] is False


def test_a_granted_teacher_need_not_be_a_hub_admin(hub):
    client, _ = hub
    admin = register_admin(client)
    teacher_id = _create_user(client, admin, "maths@example.com")

    client.put(f"{AIM}/members/{teacher_id}", headers=admin, json={"role": "teacher"})
    headers = _sign_in(client, "maths@example.com")

    assert client.get(f"{AIM}/me", headers=headers).json()["role"] == "teacher"
    # And the roster screen works for them, even though `GET /users` would not.
    assert client.get(f"{AIM}/roster/candidates", headers=headers).status_code == 200


def test_a_student_cannot_reach_the_roster(hub):
    client, _ = hub
    admin = register_admin(client)
    student_id = _create_user(client, admin, "alumne@example.com")
    client.put(f"{AIM}/members/{student_id}", headers=admin, json={"role": "student"})

    headers = _sign_in(client, "alumne@example.com")

    assert client.get(f"{AIM}/members", headers=headers).status_code == 403
    assert client.get(f"{AIM}/roster/candidates", headers=headers).status_code == 403


def test_a_non_member_is_refused_in_catalan(hub):
    client, _ = hub
    admin = register_admin(client)
    _create_user(client, admin, "clerk@example.com")

    response = client.get(f"{AIM}/members", headers=_sign_in(client, "clerk@example.com"))

    assert response.status_code == 403
    assert "AIM" in response.json()["detail"]


def test_the_roster_lists_implicit_and_granted_members_together(hub):
    client, _ = hub
    admin = register_admin(client)
    student_id = _create_user(client, admin, "alumne@example.com")
    _create_user(client, admin, "clerk@example.com")
    client.put(f"{AIM}/members/{student_id}", headers=admin, json={"role": "student"})

    roster = client.get(f"{AIM}/members", headers=admin).json()

    by_email = {row["email"]: row for row in roster}
    assert by_email["admin@example.com"]["implicit"] is True
    assert by_email["alumne@example.com"]["role"] == "student"
    assert by_email["alumne@example.com"]["implicit"] is False
    # Someone with no row and no admin bit is not in AIM.
    assert "clerk@example.com" not in by_email


def test_candidates_exclude_people_who_already_have_a_row(hub):
    client, _ = hub
    admin = register_admin(client)
    student_id = _create_user(client, admin, "alumne@example.com")
    client.put(f"{AIM}/members/{student_id}", headers=admin, json={"role": "student"})

    emails = {row["email"] for row in client.get(f"{AIM}/roster/candidates", headers=admin).json()}

    assert "alumne@example.com" not in emails
    # The admin has no row of their own, so they are still a candidate.
    assert "admin@example.com" in emails


def test_the_last_granted_teacher_cannot_be_demoted_or_removed(hub):
    """The same guard `api/users.py` puts on the last administrator."""
    client, _ = hub
    admin = register_admin(client)
    teacher_id = _create_user(client, admin, "maths@example.com")
    client.put(f"{AIM}/members/{teacher_id}", headers=admin, json={"role": "teacher"})

    demote = client.put(f"{AIM}/members/{teacher_id}", headers=admin, json={"role": "student"})
    remove = client.delete(f"{AIM}/members/{teacher_id}", headers=admin)

    assert demote.status_code == 400
    assert remove.status_code == 400
    assert client.get(f"{AIM}/me", headers=_sign_in(client, "maths@example.com")).json()[
        "role"
    ] == "teacher"


def test_a_teacher_can_be_demoted_while_another_remains(hub):
    client, _ = hub
    admin = register_admin(client)
    first = _create_user(client, admin, "maths@example.com")
    second = _create_user(client, admin, "fisica@example.com")
    client.put(f"{AIM}/members/{first}", headers=admin, json={"role": "teacher"})
    client.put(f"{AIM}/members/{second}", headers=admin, json={"role": "teacher"})

    assert client.delete(f"{AIM}/members/{first}", headers=admin).status_code == 204
    assert client.get(f"{AIM}/me", headers=_sign_in(client, "maths@example.com")).json()[
        "role"
    ] is None


def test_an_unknown_role_is_rejected(hub):
    client, _ = hub
    admin = register_admin(client)
    user_id = _create_user(client, admin, "alumne@example.com")

    response = client.put(f"{AIM}/members/{user_id}", headers=admin, json={"role": "director"})

    assert response.status_code == 422


def test_the_hub_advertises_aim(hub):
    client, _ = hub

    meta = client.get("/api/v1/meta").json()

    assert meta["capabilities"]["aim"] is True
    assert "cosecre-aim" in meta["apps"]
