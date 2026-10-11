"""Any list's search, asked for in plain words."""

from __future__ import annotations

import pytest

from conftest import FakeProvider, build_client, make_user, register_admin

from cosecre_hub.services.classification import DocumentClassifier, JevAnswer, JevClient

URL = "/api/v1/ai-search"

SPEC = {
    "subject": "moviments d'un extracte bancari",
    "search_hint": "concepte, import, factura",
    "filters": [
        {
            "name": "categoria",
            "label": "Categoria",
            "options": [
                {"value": "pagament", "label": "Pagament"},
                {"value": "comissio", "label": "Comissió bancària"},
            ],
        },
        {
            "name": "justificat",
            "label": "Factura",
            "options": [{"value": "no", "label": "Sense factura"}, {"value": "si", "label": "Amb factura"}],
        },
    ],
    "ranges": [
        {"kind": "date", "label": "Data", "from_name": "des", "to_name": "fins"},
        {"kind": "amount", "label": "Import", "from_name": "min", "to_name": "max"},
    ],
}

READING = {
    "categoria": "pagament",
    "justificat": "no",
    "periode": "cap",
    "date_from": "2026-03-01",
    "date_to": "2026-03-31",
    "amount_min": -200,
    "amount_max": None,
    "text": "Amazon",
    "explanation": "Pagaments a Amazon de més de 200 € del març sense factura.",
}


class FakeJev(JevClient):
    def __init__(self, answers=None):
        self.model = "jev-fake"
        self.answers = answers or {}
        self.questions = None

    def decide(self, state, questions):
        self.questions = questions
        return dict(self.answers)

    def close(self):
        pass


def _client(tmp_path, provider, jev=None):
    client, _ = build_client(tmp_path, provider=provider, classifier=DocumentClassifier(jev))
    return client


def test_the_language_model_reads_closed_lists_ranges_and_words(tmp_path):
    provider = FakeProvider(structured_payload=dict(READING))
    with _client(tmp_path, provider) as client:
        headers = register_admin(client)
        result = client.post(URL, headers=headers, json={**SPEC, "query": "pagaments a amazon de més de 200 € del març sense factura"}).json()
    assert result["filters"] == {
        "categoria": "pagament",
        "justificat": "no",
        "des": "2026-03-01",
        "fins": "2026-03-31",
        # An amount is a size, whichever way the money went.
        "min": "200",
    }
    assert result["search"] == "Amazon"
    assert result["models"] == {"jev": "off", "openai": "ok"}


def test_jev_settles_a_plain_question_alone(tmp_path):
    provider = FakeProvider(structured_payload=dict(READING))
    jev = FakeJev(
        {
            "categoria": JevAnswer(label="comissio", confidence=0.96),
            "justificat": JevAnswer(label="", confidence=0.95),
            "periode": JevAnswer(label="mes_passat", confidence=0.93),
            "obert": JevAnswer(label="no", confidence=0.94),
        }
    )
    with _client(tmp_path, provider, jev) as client:
        headers = register_admin(client)
        result = client.post(URL, headers=headers, json={**SPEC, "query": "comissions del mes passat"}).json()
    assert provider.structures == []
    assert result["models"]["openai"] == "skipped"
    assert result["filters"]["categoria"] == "comissio"
    assert {"des", "fins"} <= set(result["filters"])
    assert result["explanation"].startswith("Categoria: Comissió bancària")
    assert set(jev.questions) == {"categoria", "justificat", "periode", "obert"}


def test_a_list_without_ranges_is_not_asked_about_dates(tmp_path):
    spec = {**SPEC, "ranges": []}
    provider = FakeProvider(structured_payload={"categoria": "cap", "justificat": "cap", "text": "x", "explanation": "x"})
    jev = FakeJev()
    with _client(tmp_path, provider, jev) as client:
        headers = register_admin(client)
        result = client.post(URL, headers=headers, json={**spec, "query": "algo"}).json()
    assert "periode" not in jev.questions
    assert result["filters"] == {}


def test_every_role_may_ask_and_the_spec_is_checked(tmp_path):
    provider = FakeProvider(structured_payload=dict(READING))
    with _client(tmp_path, provider) as client:
        admin = register_admin(client)
        teacher = make_user(client, admin, "professor")
        assert client.post(URL, headers=teacher, json={**SPEC, "query": "pagaments"}).status_code == 200
        bad = {**SPEC, "filters": [{"name": "DROP TABLE", "label": "x", "options": [{"value": "a", "label": "a"}]}]}
        assert client.post(URL, headers=admin, json={**bad, "query": "pagaments"}).status_code == 422
