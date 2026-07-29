"""The tutor conversation: streaming, persistence, budget and replay."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from conftest import FakeProvider, build_client, register_admin

from test_aim_exercises import REFINED

AIM = "/api/v1/aim"


def _frames(client: TestClient, message_id: int, headers: dict[str, str]) -> list[dict]:
    with client.stream("GET", f"{AIM}/messages/{message_id}/stream", headers=headers) as response:
        assert response.status_code == 200, response.read()
        assert response.headers["content-type"].startswith("application/x-ndjson")
        return [json.loads(line) for line in response.iter_lines() if line.strip()]


@pytest.fixture
def live(tmp_path):
    """A started session with one student attached, ready to talk."""
    provider = FakeProvider(structured_payload=REFINED, text="Comencem pel domini de la funció.")
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

        yield client, provider, admin, student, session_id, participant_id


def _ask(client: TestClient, participant_id: int, student: dict[str, str], text: str) -> dict:
    response = client.post(
        f"{AIM}/participants/{participant_id}/messages", headers=student, json={"content": text}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_the_question_is_stored_before_the_answer_is_asked_for(live):
    """A connection that drops mid-answer must never lose the question."""
    client, provider, _, student, _, participant_id = live

    sent = _ask(client, participant_id, student, "Com començo?")

    assert sent["question"]["status"] == "complete"
    assert sent["reply"]["status"] == "streaming"
    assert sent["reply"]["content"] == ""
    # Nothing has been asked of the model yet.
    assert provider.streams == []


def test_the_answer_arrives_as_ordered_frames(live):
    client, _, _, student, _, participant_id = live
    sent = _ask(client, participant_id, student, "Com començo?")

    frames = _frames(client, sent["reply"]["id"], student)

    assert frames[0]["type"] == "start"
    assert [frame["type"] for frame in frames].count("delta") >= 2
    assert frames[-2]["type"] == "usage"
    assert frames[-1]["type"] == "done"
    assert "".join(f["text"] for f in frames if f["type"] == "delta") == (
        "Comencem pel domini de la funció."
    )


def test_the_finished_answer_is_persisted_with_its_usage(live):
    client, _, _, student, _, participant_id = live
    sent = _ask(client, participant_id, student, "Com començo?")

    _frames(client, sent["reply"]["id"], student)

    transcript = client.get(f"{AIM}/participants/{participant_id}/messages", headers=student).json()
    reply = transcript[-1]
    assert reply["status"] == "complete"
    assert reply["content"] == "Comencem pel domini de la funció."
    assert reply["total_tokens"] == 18
    assert client.get(f"{AIM}/student/current", headers=student).json()["tokens_used"] == 18


def test_the_usage_frame_reports_the_running_total_and_the_budget(live):
    client, _, _, student, _, participant_id = live
    sent = _ask(client, participant_id, student, "Com començo?")

    usage = next(f for f in _frames(client, sent["reply"]["id"], student) if f["type"] == "usage")

    assert usage["total_tokens"] == 18
    assert usage["tokens_used"] == 18
    assert usage["token_budget"] == 60_000


def test_the_tutor_is_told_never_to_give_the_solution(live):
    """First and last: it is the one instruction a student will attack."""
    client, provider, _, student, _, participant_id = live
    sent = _ask(client, participant_id, student, "Dona'm la resposta")

    _frames(client, sent["reply"]["id"], student)

    instructions = provider.streams[0].instructions
    assert instructions.count("REGLA ABSOLUTA") == 2
    assert instructions.index("REGLA ABSOLUTA") < instructions.index("## EXERCICI")
    assert instructions.rstrip().endswith("torna-li la pregunta.")


def test_the_tutor_gets_the_ladder_and_the_issues_but_the_student_never_does(live):
    client, provider, _, student, _, participant_id = live
    sent = _ask(client, participant_id, student, "Com començo?")

    _frames(client, sent["reply"]["id"], student)

    instructions = provider.streams[0].instructions
    # The ladder, with the escalation the teacher wrote for each rung.
    assert "Quina integral?" in instructions
    assert "Recorda la primitiva." in instructions
    # And the anticipated issues, with their signal and their hint.
    assert "Confon àrea amb pendent" in instructions
    assert "Què acumula una integral?" in instructions

    shown = json.dumps(client.get(f"{AIM}/student/current", headers=student).json()["exercise"])
    assert "Quina integral?" not in shown
    assert "Confon àrea amb pendent" not in shown


def test_earlier_turns_are_replayed_to_the_model(live):
    client, provider, _, student, _, participant_id = live
    first = _ask(client, participant_id, student, "Primera pregunta")
    _frames(client, first["reply"]["id"], student)

    second = _ask(client, participant_id, student, "Segona pregunta")
    _frames(client, second["reply"]["id"], student)

    history = [message.content for message in provider.streams[1].messages]
    assert "Primera pregunta" in history
    assert "Comencem pel domini de la funció." in history
    assert history[-1] == "Segona pregunta"
    # The empty placeholder for the answer being written is not sent.
    assert "" not in history


def test_a_finished_message_replays_instead_of_asking_again(live):
    """This is what makes a reload mid-answer a non-event."""
    client, provider, _, student, _, participant_id = live
    sent = _ask(client, participant_id, student, "Com començo?")
    _frames(client, sent["reply"]["id"], student)

    replayed = _frames(client, sent["reply"]["id"], student)

    assert [frame["type"] for frame in replayed] == ["start", "delta", "usage", "done"]
    assert replayed[1]["text"] == "Comencem pel domini de la funció."
    assert len(provider.streams) == 1, "replay must not call the model again"


def test_a_mid_stream_failure_is_recorded_and_reported(live):
    client, provider, _, student, _, participant_id = live
    provider.stream_error = "El proveïdor ha fallat"
    sent = _ask(client, participant_id, student, "Com començo?")

    frames = _frames(client, sent["reply"]["id"], student)

    assert frames[-1]["type"] == "error"
    assert "ha fallat" in frames[-1]["detail"]
    transcript = client.get(f"{AIM}/participants/{participant_id}/messages", headers=student).json()
    assert transcript[-1]["status"] == "failed"
    # A failed turn costs the student nothing.
    assert client.get(f"{AIM}/student/current", headers=student).json()["tokens_used"] == 0


def test_a_failed_message_replays_as_a_failure(live):
    client, provider, _, student, _, participant_id = live
    provider.stream_error = "boom"
    sent = _ask(client, participant_id, student, "Com començo?")
    _frames(client, sent["reply"]["id"], student)

    assert _frames(client, sent["reply"]["id"], student)[-1]["type"] == "error"


def test_a_student_out_of_budget_is_refused(live):
    client, _, admin, student, session_id, participant_id = live
    client.patch(
        f"{AIM}/sessions/{session_id}/participants/{participant_id}",
        headers=admin,
        json={"token_budget_override": 0},
    )

    response = client.post(
        f"{AIM}/participants/{participant_id}/messages", headers=student, json={"content": "Hola"}
    )

    assert response.status_code == 403
    assert "pressupost" in response.json()["detail"]


def test_a_turn_is_clamped_to_what_is_left_of_the_budget(live):
    client, provider, admin, student, session_id, participant_id = live
    client.patch(
        f"{AIM}/sessions/{session_id}/participants/{participant_id}",
        headers=admin,
        json={"token_budget_override": 300},
    )
    sent = _ask(client, participant_id, student, "Com començo?")

    _frames(client, sent["reply"]["id"], student)

    assert provider.streams[0].max_output_tokens == 300


def test_a_student_cannot_read_another_student_s_conversation(live):
    client, _, admin, student, _, participant_id = live
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

    read = client.get(f"{AIM}/participants/{participant_id}/messages", headers=intruder)
    write = client.post(
        f"{AIM}/participants/{participant_id}/messages", headers=intruder, json={"content": "x"}
    )

    assert read.status_code == 403
    assert write.status_code == 403


def test_the_teacher_can_read_the_transcript_but_not_drive_it(live):
    client, _, admin, student, _, participant_id = live
    sent = _ask(client, participant_id, student, "Com començo?")

    assert (
        client.get(f"{AIM}/participants/{participant_id}/messages", headers=admin).status_code == 200
    )
    with client.stream(
        "GET", f"{AIM}/messages/{sent['reply']['id']}/stream", headers=admin
    ) as response:
        assert response.status_code == 403


def test_a_message_cannot_be_sent_once_the_session_has_ended(live):
    client, _, admin, student, session_id, participant_id = live
    client.post(f"{AIM}/sessions/{session_id}/end", headers=admin)

    response = client.post(
        f"{AIM}/participants/{participant_id}/messages", headers=student, json={"content": "Hola"}
    )

    assert response.status_code == 409
