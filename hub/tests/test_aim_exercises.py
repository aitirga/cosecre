"""Authoring an exercise, refining it with the model, and sharing it."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import FakeProvider, build_client, register_admin

AIM = "/api/v1/aim"

REFINED = {
    "title": "Àrea sota una paràbola",
    "statement_md": "Calcula l'àrea entre $y = x^2$ i l'eix d'abscisses per a $x \\in [0, 2]$.",
    "difficulty_ladder": [
        {"step": 1, "label": "Dibuixa", "prompt": "Com és la corba?", "escalation": "Marca els límits."},
        {"step": 2, "label": "Planteja", "prompt": "Quina integral?", "escalation": "Recorda la primitiva."},
    ],
    "anticipated_issues": [
        {"issue": "Confon àrea amb pendent", "signal": "Parla de derivar", "hint": "Què acumula una integral?"}
    ],
    "suggested_topics": ["integrals", "no-existeix"],
    "suggested_level": "2n batxillerat",
    "plot_requests": ["La paràbola amb l'àrea ombrejada"],
}


@pytest.fixture
def teaching(tmp_path):
    """A hub with one teacher and a provider primed to return a real exercise."""
    provider = FakeProvider(structured_payload=REFINED)
    client, _ = build_client(tmp_path, provider=provider)
    with client:
        yield client, provider, register_admin(client)


def _new_exercise(client: TestClient, headers: dict[str, str], title: str = "Esborrany") -> int:
    response = client.post(f"{AIM}/exercises", headers=headers, json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_a_new_exercise_starts_as_an_unrefined_draft(teaching):
    client, _, headers = teaching

    body = client.post(f"{AIM}/exercises", headers=headers, json={"title": "Esborrany"}).json()

    assert body["status"] == "draft"
    assert body["refined"] is False
    assert body["current"]["version"] == 1


def test_the_draft_autosaves_and_takes_its_title_from_the_blocks(teaching):
    client, _, headers = teaching
    exercise_id = _new_exercise(client, headers)

    client.put(
        f"{AIM}/exercises/{exercise_id}/draft",
        headers=headers,
        json={"raw_blocks": {"title": "Paràboles", "statement": "Àrea sota la corba"}},
    )

    body = client.get(f"{AIM}/exercises/{exercise_id}", headers=headers).json()
    assert body["title"] == "Paràboles"
    assert body["current"]["raw_blocks"]["statement"] == "Àrea sota la corba"


def test_refining_asks_the_model_for_the_agreed_schema_and_stores_the_result(teaching):
    client, provider, headers = teaching
    exercise_id = _new_exercise(client, headers)

    response = client.post(
        f"{AIM}/exercises/{exercise_id}/refine",
        headers=headers,
        json={"raw_blocks": {"title": "Paràboles", "statement": "Àrea sota la corba"}},
    )

    assert response.status_code == 200, response.text
    assert provider.structures[0].schema_name == "refined_exercise"
    # The teacher's own words reach the model, under labelled headings.
    assert "Àrea sota la corba" in provider.structures[0].messages[0].content
    refined = response.json()["version"]["refined"]
    assert len(refined["difficulty_ladder"]) == 2
    assert refined["anticipated_issues"][0]["signal"] == "Parla de derivar"


def test_refining_keeps_only_topics_the_hub_knows(teaching):
    """The model suggests freely; the library's vocabulary stays controlled."""
    client, _, headers = teaching
    client.get(f"{AIM}/topics", headers=headers)  # seeds the vocabulary
    exercise_id = _new_exercise(client, headers)

    client.post(f"{AIM}/exercises/{exercise_id}/refine", headers=headers, json={"raw_blocks": {}})

    body = client.get(f"{AIM}/exercises/{exercise_id}", headers=headers).json()
    assert body["topics"] == ["integrals"]
    assert body["level"] == "2n batxillerat"


def test_a_focus_note_reaches_the_model(teaching):
    client, provider, headers = teaching
    exercise_id = _new_exercise(client, headers)

    client.post(
        f"{AIM}/exercises/{exercise_id}/refine",
        headers=headers,
        json={"raw_blocks": {"statement": "x"}, "focus": "Fes més graons"},
    )

    assert "Fes més graons" in provider.structures[0].messages[0].content


def test_an_exercise_cannot_be_published_before_it_is_refined(teaching):
    client, _, headers = teaching
    exercise_id = _new_exercise(client, headers)

    response = client.post(
        f"{AIM}/exercises/{exercise_id}/publish", headers=headers, json={"topics": [], "level": ""}
    )

    assert response.status_code == 409


def test_publishing_puts_it_in_the_library_for_other_teachers(teaching):
    client, _, headers = teaching
    exercise_id = _new_exercise(client, headers)
    client.post(f"{AIM}/exercises/{exercise_id}/refine", headers=headers, json={"raw_blocks": {}})

    client.post(
        f"{AIM}/exercises/{exercise_id}/publish",
        headers=headers,
        json={"topics": ["integrals"], "level": "2n batxillerat"},
    )

    library = client.get(f"{AIM}/exercises?scope=library", headers=headers).json()
    assert [item["id"] for item in library] == [exercise_id]


def test_the_library_never_shows_drafts(teaching):
    client, _, headers = teaching
    _new_exercise(client, headers, "Encara no llest")

    assert client.get(f"{AIM}/exercises?scope=library", headers=headers).json() == []


def test_another_teacher_can_clone_a_published_exercise_but_not_a_draft(teaching):
    client, _, owner = teaching
    other = client.post(
        "/api/v1/users",
        headers=owner,
        json={"email": "altre@example.com", "password": "supersecure", "is_admin": True},
    ).json()
    other_headers = {
        "Authorization": "Bearer "
        + client.post(
            "/api/v1/auth/login",
            json={"email": "altre@example.com", "password": "supersecure", "client": "pytest"},
        ).json()["access_token"]
    }

    draft_id = _new_exercise(client, owner, "Esborrany")
    published_id = _new_exercise(client, owner, "Publicat")
    client.post(f"{AIM}/exercises/{published_id}/refine", headers=owner, json={"raw_blocks": {}})
    client.post(
        f"{AIM}/exercises/{published_id}/publish",
        headers=owner,
        json={"topics": ["integrals"], "level": "2n"},
    )

    assert client.post(f"{AIM}/exercises/{draft_id}/clone", headers=other_headers).status_code == 403

    clone = client.post(f"{AIM}/exercises/{published_id}/clone", headers=other_headers)
    assert clone.status_code == 201
    body = clone.json()
    assert body["owner_id"] == other["id"]
    assert body["status"] == "draft"
    # The clone carries the refined body, so it is runnable immediately.
    assert body["current"]["refined"]["title"] == REFINED["title"]


def test_a_teacher_cannot_edit_an_exercise_they_do_not_own(teaching):
    client, _, owner = teaching
    exercise_id = _new_exercise(client, owner)
    client.post(
        "/api/v1/users",
        headers=owner,
        json={"email": "altre@example.com", "password": "supersecure", "is_admin": True},
    )
    other = {
        "Authorization": "Bearer "
        + client.post(
            "/api/v1/auth/login",
            json={"email": "altre@example.com", "password": "supersecure", "client": "pytest"},
        ).json()["access_token"]
    }

    response = client.patch(f"{AIM}/exercises/{exercise_id}", headers=other, json={"title": "Meu"})

    assert response.status_code == 403


def test_a_student_cannot_reach_the_authoring_api(teaching):
    client, _, admin = teaching
    student = client.post(
        "/api/v1/users",
        headers=admin,
        json={"email": "alumne@example.com", "password": "supersecure", "is_admin": False},
    ).json()
    client.put(f"{AIM}/members/{student['id']}", headers=admin, json={"role": "student"})
    headers = {
        "Authorization": "Bearer "
        + client.post(
            "/api/v1/auth/login",
            json={"email": "alumne@example.com", "password": "supersecure", "client": "pytest"},
        ).json()["access_token"]
    }

    assert client.get(f"{AIM}/exercises", headers=headers).status_code == 403
    assert client.post(f"{AIM}/exercises", headers=headers, json={"title": "x"}).status_code == 403


def test_a_hub_with_no_model_says_so_rather_than_failing_opaquely(tmp_path):
    client, _ = build_client(tmp_path, provider=FakeProvider(configured=False))
    with client:
        headers = register_admin(client)
        exercise_id = _new_exercise(client, headers)

        response = client.post(
            f"{AIM}/exercises/{exercise_id}/refine", headers=headers, json={"raw_blocks": {}}
        )

    assert response.status_code == 503


def test_an_exercise_that_was_never_run_can_be_deleted(teaching):
    """The refusal once a session exists is covered in `test_aim_sessions.py`."""
    client, _, headers = teaching
    exercise_id = _new_exercise(client, headers)
    client.post(f"{AIM}/exercises/{exercise_id}/refine", headers=headers, json={"raw_blocks": {}})

    assert client.delete(f"{AIM}/exercises/{exercise_id}", headers=headers).status_code == 204
    assert client.get(f"{AIM}/exercises/{exercise_id}", headers=headers).status_code == 404


def test_topics_are_seeded_on_first_read(teaching):
    client, _, headers = teaching

    topics = client.get(f"{AIM}/topics", headers=headers).json()

    assert {"slug": "integrals", "label": "Integrals"} in topics
    # Idempotent: reading twice does not duplicate them.
    assert len(client.get(f"{AIM}/topics", headers=headers).json()) == len(topics)
