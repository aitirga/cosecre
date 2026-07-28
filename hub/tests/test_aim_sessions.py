"""Running an exercise for a class."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import FakeProvider, build_client, register_admin

from test_aim_exercises import REFINED

AIM = "/api/v1/aim"


def _add_user(client: TestClient, admin: dict[str, str], email: str, role: str) -> dict[str, str]:
    created = client.post(
        "/api/v1/users",
        headers=admin,
        json={"email": email, "password": "supersecure", "display_name": email.split("@")[0]},
    ).json()
    client.put(f"{AIM}/members/{created['id']}", headers=admin, json={"role": role})
    token = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "supersecure", "client": "pytest"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def classroom(tmp_path):
    """A teacher with a publishable exercise, and two students."""
    provider = FakeProvider(structured_payload=REFINED)
    client, _ = build_client(tmp_path, provider=provider)
    with client:
        admin = register_admin(client)
        exercise_id = client.post(
            f"{AIM}/exercises", headers=admin, json={"title": "Paràboles"}
        ).json()["id"]
        client.post(f"{AIM}/exercises/{exercise_id}/refine", headers=admin, json={"raw_blocks": {}})
        yield (
            client,
            admin,
            exercise_id,
            _add_user(client, admin, "anna@example.com", "student"),
            _add_user(client, admin, "bru@example.com", "student"),
        )


def _new_session(client: TestClient, admin: dict[str, str], exercise_id: int) -> dict:
    response = client.post(f"{AIM}/sessions", headers=admin, json={"exercise_id": exercise_id})
    assert response.status_code == 201, response.text
    return response.json()


def test_a_session_starts_waiting_with_a_readable_join_code(classroom):
    client, admin, exercise_id, _, _ = classroom

    body = _new_session(client, admin, exercise_id)

    assert body["status"] == "waiting"
    assert len(body["join_code"]) == 6
    # No vowels and no look-alikes — this gets read off a projector.
    assert not set(body["join_code"]) & set("AEIOU01ILO")


def test_an_unrefined_exercise_cannot_be_run(classroom):
    client, admin, _, _, _ = classroom
    raw_id = client.post(f"{AIM}/exercises", headers=admin, json={"title": "Cru"}).json()["id"]

    response = client.post(f"{AIM}/sessions", headers=admin, json={"exercise_id": raw_id})

    assert response.status_code == 409


def test_a_student_waits_until_the_teacher_starts(classroom):
    client, admin, exercise_id, anna, _ = classroom
    _new_session(client, admin, exercise_id)

    waiting = client.get(f"{AIM}/student/current", headers=anna).json()

    assert waiting["state"] == "waiting"
    # The statement is withheld until it actually starts.
    assert waiting["exercise"] is None


def test_starting_reveals_the_statement_but_never_the_ladder(classroom):
    """The difficulty ladder is the tutor's script; it is not the student's."""
    client, admin, exercise_id, anna, _ = classroom
    created = _new_session(client, admin, exercise_id)
    client.get(f"{AIM}/student/current", headers=anna)

    client.post(f"{AIM}/sessions/{created['id']}/start", headers=admin)
    live = client.get(f"{AIM}/student/current", headers=anna).json()

    assert live["state"] == "live"
    assert live["exercise"]["statement_md"] == REFINED["statement_md"]
    assert "difficulty_ladder" not in live["exercise"]
    assert "anticipated_issues" not in live["exercise"]


def test_the_first_look_attaches_the_student_without_a_code(classroom):
    client, admin, exercise_id, anna, _ = classroom
    created = _new_session(client, admin, exercise_id)

    first = client.get(f"{AIM}/student/current", headers=anna).json()
    second = client.get(f"{AIM}/student/current", headers=anna).json()

    assert first["participant_id"] == second["participant_id"]
    monitor = client.get(f"{AIM}/sessions/{created['id']}/monitor", headers=admin).json()
    assert len(monitor["participants"]) == 1


def test_a_join_code_also_works_and_is_idempotent(classroom):
    client, admin, exercise_id, anna, _ = classroom
    created = _new_session(client, admin, exercise_id)

    first = client.post(f"{AIM}/sessions/join", headers=anna, json={"code": created["join_code"]})
    second = client.post(f"{AIM}/sessions/join", headers=anna, json={"code": created["join_code"]})

    assert first.status_code == 200
    assert first.json()["participant_id"] == second.json()["participant_id"]


def test_a_lowercase_join_code_is_accepted(classroom):
    client, admin, exercise_id, anna, _ = classroom
    created = _new_session(client, admin, exercise_id)

    response = client.post(
        f"{AIM}/sessions/join", headers=anna, json={"code": created["join_code"].lower()}
    )

    assert response.status_code == 200


def test_an_unknown_join_code_is_refused(classroom):
    client, _, _, anna, _ = classroom

    assert client.post(f"{AIM}/sessions/join", headers=anna, json={"code": "ZZZZZZ"}).status_code == 404


def test_the_monitor_shows_every_student_and_their_budget(classroom):
    client, admin, exercise_id, anna, bru = classroom
    created = _new_session(client, admin, exercise_id)
    client.get(f"{AIM}/student/current", headers=anna)
    client.get(f"{AIM}/student/current", headers=bru)

    monitor = client.get(f"{AIM}/sessions/{created['id']}/monitor", headers=admin).json()

    names = {row["display_name"] for row in monitor["participants"]}
    assert names == {"anna", "bru"}
    assert all(row["effective_budget"] == 60_000 for row in monitor["participants"])
    assert all(row["stuck"] is False for row in monitor["participants"])


def test_a_teacher_can_lower_one_student_s_budget(classroom):
    client, admin, exercise_id, anna, _ = classroom
    created = _new_session(client, admin, exercise_id)
    participant_id = client.get(f"{AIM}/student/current", headers=anna).json()["participant_id"]

    client.patch(
        f"{AIM}/sessions/{created['id']}/participants/{participant_id}",
        headers=admin,
        json={"token_budget_override": 500},
    )

    assert client.get(f"{AIM}/student/current", headers=anna).json()["effective_budget"] == 500


def test_a_student_cannot_reach_the_monitor(classroom):
    client, admin, exercise_id, anna, _ = classroom
    created = _new_session(client, admin, exercise_id)

    assert client.get(f"{AIM}/sessions/{created['id']}/monitor", headers=anna).status_code == 403


def test_a_teacher_cannot_monitor_another_teacher_s_session(classroom):
    client, admin, exercise_id, _, _ = classroom
    created = _new_session(client, admin, exercise_id)
    other = _add_user(client, admin, "altre@example.com", "teacher")

    assert client.get(f"{AIM}/sessions/{created['id']}/monitor", headers=other).status_code == 403


def test_ending_a_session_tells_the_student_so(classroom):
    client, admin, exercise_id, anna, _ = classroom
    created = _new_session(client, admin, exercise_id)
    client.post(f"{AIM}/sessions/{created['id']}/start", headers=admin)
    client.get(f"{AIM}/student/current", headers=anna)

    client.post(f"{AIM}/sessions/{created['id']}/end", headers=admin)

    state = client.get(f"{AIM}/student/current", headers=anna).json()
    assert state["state"] == "ended"


def test_a_student_with_no_session_anywhere_is_idle(classroom):
    client, _, _, anna, _ = classroom

    assert client.get(f"{AIM}/student/current", headers=anna).json()["state"] == "idle"


def test_an_exercise_that_has_been_run_cannot_be_deleted(classroom):
    """The transcript belongs to the student too, so the exercise is kept."""
    client, admin, exercise_id, _, _ = classroom
    _new_session(client, admin, exercise_id)

    response = client.delete(f"{AIM}/exercises/{exercise_id}", headers=admin)

    assert response.status_code == 409


def test_a_session_pins_the_version_it_started_with(classroom):
    """Editing mid-class must not change the problem under a student."""
    client, admin, exercise_id, anna, _ = classroom
    created = _new_session(client, admin, exercise_id)
    client.post(f"{AIM}/sessions/{created['id']}/start", headers=admin)

    client.put(
        f"{AIM}/exercises/{exercise_id}/draft",
        headers=admin,
        json={"raw_blocks": {"statement": "un problema completament diferent"}},
    )

    live = client.get(f"{AIM}/student/current", headers=anna).json()
    assert live["exercise"]["statement_md"] == REFINED["statement_md"]
