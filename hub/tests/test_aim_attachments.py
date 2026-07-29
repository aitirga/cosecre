"""Photos a student sends with a question."""

from __future__ import annotations

import base64
import json

import pytest

from conftest import FakeProvider, build_client, register_admin

from test_aim_exercises import REFINED

AIM = "/api/v1/aim"

#: One transparent pixel — the smallest thing the upload path will accept.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


@pytest.fixture
def live(tmp_path):
    provider = FakeProvider(structured_payload=REFINED, text="Què hi veus, en aquesta foto?")
    client, _ = build_client(tmp_path, provider=provider)
    with client:
        admin = register_admin(client)
        exercise_id = client.post(
            f"{AIM}/exercises", headers=admin, json={"title": "Paràboles"}
        ).json()["id"]
        client.post(f"{AIM}/exercises/{exercise_id}/refine", headers=admin, json={"raw_blocks": {}})

        created = client.post(
            "/api/v1/users",
            headers=admin,
            json={"email": "anna@example.com", "password": "supersecure", "display_name": "Anna"},
        ).json()
        client.put(f"{AIM}/members/{created['id']}", headers=admin, json={"role": "student"})
        student = {
            "Authorization": "Bearer "
            + client.post(
                "/api/v1/auth/login",
                json={"email": "anna@example.com", "password": "supersecure", "client": "pytest"},
            ).json()["access_token"]
        }

        session_id = client.post(
            f"{AIM}/sessions", headers=admin, json={"exercise_id": exercise_id}
        ).json()["id"]
        client.post(f"{AIM}/sessions/{session_id}/start", headers=admin)
        participant_id = client.get(f"{AIM}/student/current", headers=student).json()[
            "participant_id"
        ]
        yield client, provider, admin, student, participant_id


def _upload(client, participant_id, student, name="foto.png", mime="image/png", body=None):
    return client.post(
        f"{AIM}/participants/{participant_id}/attachments",
        headers=student,
        files={"file": (name, body if body is not None else PNG, mime)},
    )


def test_a_photo_is_accepted_and_a_pdf_is_not(live):
    """A PDF mid-conversation is not useful, and takes a different model path."""
    client, _, _, student, participant_id = live

    assert _upload(client, participant_id, student).status_code == 201
    pdf = _upload(client, participant_id, student, "apunts.pdf", "application/pdf", b"%PDF-1.4")
    assert pdf.status_code == 400


def test_a_photo_reaches_the_model_with_the_question(live):
    client, provider, _, student, participant_id = live
    attachment_id = _upload(client, participant_id, student).json()["id"]

    first = client.post(
        f"{AIM}/participants/{participant_id}/messages",
        headers=student,
        json={"content": "He fet això, va bé?", "attachment_ids": [attachment_id]},
    ).json()
    with client.stream(
        "GET", f"{AIM}/messages/{first['reply']['id']}/stream", headers=student
    ) as response:
        list(response.iter_lines())

    # The photo travels with the *next* turn's history, which is where the model
    # sees it — the turn that sent it is the one being answered.
    second = client.post(
        f"{AIM}/participants/{participant_id}/messages",
        headers=student,
        json={"content": "I ara?"},
    ).json()
    with client.stream(
        "GET", f"{AIM}/messages/{second['reply']['id']}/stream", headers=student
    ) as response:
        list(response.iter_lines())

    carried = [
        message
        for message in provider.streams[-1].messages
        if message.content == "He fet això, va bé?"
    ]
    assert carried and len(carried[0].attachments) == 1
    assert carried[0].attachments[0].mime_type == "image/png"
    assert carried[0].attachments[0].path.exists()


def test_the_transcript_lists_the_photo(live):
    client, _, _, student, participant_id = live
    attachment_id = _upload(client, participant_id, student).json()["id"]
    client.post(
        f"{AIM}/participants/{participant_id}/messages",
        headers=student,
        json={"content": "Mira", "attachment_ids": [attachment_id]},
    )

    transcript = client.get(f"{AIM}/participants/{participant_id}/messages", headers=student).json()

    question = next(item for item in transcript if item["role"] == "user")
    assert [item["id"] for item in question["attachments"]] == [attachment_id]


def test_a_photo_belonging_to_someone_else_cannot_be_adopted(live):
    """An id is not a capability: the upload has to be this student's own."""
    client, _, admin, student, participant_id = live
    other = client.post(
        "/api/v1/users",
        headers=admin,
        json={"email": "bru@example.com", "password": "supersecure"},
    ).json()
    client.put(f"{AIM}/members/{other['id']}", headers=admin, json={"role": "student"})
    intruder = {
        "Authorization": "Bearer "
        + client.post(
            "/api/v1/auth/login",
            json={"email": "bru@example.com", "password": "supersecure", "client": "pytest"},
        ).json()["access_token"]
    }
    other_participant = client.get(f"{AIM}/student/current", headers=intruder).json()[
        "participant_id"
    ]
    stolen = _upload(client, participant_id, student).json()["id"]

    client.post(
        f"{AIM}/participants/{other_participant}/messages",
        headers=intruder,
        json={"content": "meu", "attachment_ids": [stolen]},
    )

    transcript = client.get(
        f"{AIM}/participants/{other_participant}/messages", headers=intruder
    ).json()
    assert all(not item["attachments"] for item in transcript)


def test_the_owner_and_their_teacher_can_fetch_it_and_nobody_else(live):
    client, _, admin, student, participant_id = live
    attachment_id = _upload(client, participant_id, student).json()["id"]

    other = client.post(
        "/api/v1/users",
        headers=admin,
        json={"email": "bru@example.com", "password": "supersecure"},
    ).json()
    client.put(f"{AIM}/members/{other['id']}", headers=admin, json={"role": "student"})
    intruder = {
        "Authorization": "Bearer "
        + client.post(
            "/api/v1/auth/login",
            json={"email": "bru@example.com", "password": "supersecure", "client": "pytest"},
        ).json()["access_token"]
    }

    assert client.get(f"{AIM}/attachments/{attachment_id}/file", headers=student).status_code == 200
    assert client.get(f"{AIM}/attachments/{attachment_id}/file", headers=admin).status_code == 200
    assert client.get(f"{AIM}/attachments/{attachment_id}/file", headers=intruder).status_code == 403


def test_photos_land_in_their_own_directory(live, tmp_path):
    """A student's photo never sits beside an invoice."""
    client, _, _, student, participant_id = live

    _upload(client, participant_id, student)

    assert list((tmp_path / "uploads" / "aim").glob("*.png"))


def test_an_empty_upload_is_refused(live):
    client, _, _, student, participant_id = live

    response = _upload(client, participant_id, student, body=b"")

    assert response.status_code == 400
    assert json.loads(response.text)["detail"]
