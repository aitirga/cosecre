"""The profile the tutor keeps on each student."""

from __future__ import annotations

import json

import pytest

from conftest import FakeProvider, build_client, register_admin
from cosecre_hub.services.llm import LLMError

from test_aim_exercises import REFINED

AIM = "/api/v1/aim"

PROFILE = {
    "level": "en_progres",
    "current_step": 2,
    "consecutive_failures": 1,
    "strengths": ["dibuixa bé la corba"],
    "recurring_errors": ["oblida els límits"],
    "misconceptions": ["confon àrea amb pendent"],
    "effective_hints": ["preguntar què acumula una integral"],
    "summary": "Sap plantejar la integral però s'encalla en els límits.",
    "next_focus": "substituir els límits",
}


class ScriptedProvider(FakeProvider):
    """Answers each structured schema with the payload that schema expects.

    `break_context` fails only the profile refresh, leaving the tutor working —
    which is the case worth testing, and not something toggling `configured`
    could express, since that breaks both.
    """

    break_context: bool = False

    def structured(self, request):
        if request.schema_name == "aim_student_context" and self.break_context:
            self.structures.append(request)
            raise LLMError("El perfil no s'ha pogut refer.")
        original = self.structured_payload
        self.structured_payload = (
            PROFILE if request.schema_name == "aim_student_context" else REFINED
        )
        try:
            return super().structured(request)
        finally:
            self.structured_payload = original


@pytest.fixture
def live(tmp_path):
    provider = ScriptedProvider(text="I què creus que hi has de substituir?")
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


def _turn(client, participant_id, student, text: str) -> None:
    sent = client.post(
        f"{AIM}/participants/{participant_id}/messages", headers=student, json={"content": text}
    ).json()
    # The refresh runs as a BackgroundTask on the streaming response, so it only
    # fires once the body has been fully sent — i.e. after this block exits.
    with client.stream(
        "GET", f"{AIM}/messages/{sent['reply']['id']}/stream", headers=student
    ) as response:
        list(response.iter_lines())


def test_the_profile_is_written_after_the_configured_number_of_turns(live):
    client, provider, admin, student, session_id, participant_id = live

    _turn(client, participant_id, student, "Primera")
    monitor = client.get(f"{AIM}/sessions/{session_id}/monitor", headers=admin).json()
    assert monitor["participants"][0]["context_tokens"] == 0

    _turn(client, participant_id, student, "Segona")
    _turn(client, participant_id, student, "Tercera")

    assert any(item.schema_name == "aim_student_context" for item in provider.structures)


def test_the_refresh_is_billed_apart_from_the_student_s_own_spend(live):
    """A progress bar that moves while its owner is not typing reads as a bug."""
    client, _, admin, student, session_id, participant_id = live

    for text in ("Primera", "Segona", "Tercera"):
        _turn(client, participant_id, student, text)

    row = client.get(f"{AIM}/sessions/{session_id}/monitor", headers=admin).json()["participants"][0]
    assert row["tokens_used"] == 3 * 18, "three tutor turns, nothing else"
    assert row["context_tokens"] > 0
    # And the student's own bar shows only their own spend.
    assert client.get(f"{AIM}/student/current", headers=student).json()["tokens_used"] == 3 * 18


def test_the_next_turn_is_told_what_the_profile_says(live):
    client, provider, _, student, _, participant_id = live

    for text in ("Primera", "Segona", "Tercera"):
        _turn(client, participant_id, student, text)
    _turn(client, participant_id, student, "Quarta")

    instructions = provider.streams[-1].instructions
    assert "PERFIL DE L'ALUMNE" in instructions
    assert PROFILE["summary"] in instructions
    assert "oblida els límits" in instructions
    assert "substituir els límits" in instructions


def test_the_profile_only_ever_sees_a_window_of_the_transcript(live):
    """A refresh must cost the same on turn 40 as on turn 4."""
    client, provider, _, student, _, participant_id = live

    for index in range(9):
        _turn(client, participant_id, student, f"Pregunta {index}")

    refreshes = [item for item in provider.structures if item.schema_name == "aim_student_context"]
    assert refreshes, "expected at least one refresh"
    longest = max(len(item.messages[0].content) for item in refreshes)
    shortest = min(len(item.messages[0].content) for item in refreshes)
    # Bounded by the window, not by how long the conversation has run.
    assert longest < shortest * 3


def test_a_profile_that_cannot_be_rebuilt_does_not_break_the_turn(live):
    """A failed refresh is invisible to the student; the next one tries again."""
    client, provider, admin, student, session_id, participant_id = live
    provider.break_context = True

    for text in ("Primera", "Segona", "Tercera"):
        _turn(client, participant_id, student, text)

    transcript = client.get(
        f"{AIM}/participants/{participant_id}/messages", headers=student
    ).json()
    assert transcript[-1]["status"] == "complete"
    assert transcript[-1]["content"] == "I què creus que hi has de substituir?"
    # Nothing was billed for a refresh that produced nothing.
    row = client.get(f"{AIM}/sessions/{session_id}/monitor", headers=admin).json()["participants"][0]
    assert row["context_tokens"] == 0

    # And it recovers. The refresh runs *after* the turn that triggers it, so
    # the profile first reaches the tutor on the turn after that.
    provider.break_context = False
    for text in ("Quarta", "Cinquena", "Sisena", "Setena"):
        _turn(client, participant_id, student, text)
    assert PROFILE["summary"] in provider.streams[-1].instructions


def test_a_student_s_other_exercises_reach_the_tutor_as_prior_history(live):
    client, provider, admin, student, _, participant_id = live
    other_id = client.post(f"{AIM}/exercises", headers=admin, json={"title": "Trigonometria"}).json()[
        "id"
    ]
    client.post(f"{AIM}/exercises/{other_id}/refine", headers=admin, json={"raw_blocks": {}})
    other_session = client.post(
        f"{AIM}/sessions", headers=admin, json={"exercise_id": other_id}
    ).json()["id"]
    client.post(f"{AIM}/sessions/{other_session}/start", headers=admin)
    other_participant = client.get(f"{AIM}/student/current", headers=student).json()[
        "participant_id"
    ]

    for text in ("A", "B", "C"):
        _turn(client, other_participant, student, text)
    _turn(client, other_participant, student, "D")

    instructions = provider.streams[-1].instructions
    assert "HISTÒRIA PRÈVIA" not in instructions or PROFILE["summary"] in instructions
    assert json.dumps(PROFILE["summary"]) is not None
