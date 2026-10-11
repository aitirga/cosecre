"""Asking the register a question in plain words."""

from __future__ import annotations

from datetime import date

import pytest

from conftest import FakeProvider, build_client, make_user, register_admin

from cosecre_hub.services.ai_filter import period_range
from cosecre_hub.services.classification import DocumentClassifier, JevAnswer, JevClient, JevError

URL = "/api/v1/documents/records/ai-filter"

READING = {
    "tipus": "cap",
    "pagament": "pendent",
    "compte": "material",
    "estat": "cap",
    "enviat": "cap",
    "periode": "aquest_curs",
    "date_from": "",
    "date_to": "",
    "amount_min": 100,
    "amount_max": None,
    "text": "Pérez",
    "explanation": "Factures pendents de Pérez de més de 100 € d'aquest curs.",
}


class FakeJev(JevClient):
    def __init__(self, answers=None, fail=False):
        self.model = "jev-fake"
        self.answers = answers or {}
        self.fail = fail
        self.questions = None

    def decide(self, state, questions):
        if self.fail:
            raise JevError("down")
        self.questions = questions
        return dict(self.answers)

    def close(self):
        pass


def _client(tmp_path, *, reading=None, jev=None, configured=True):
    provider = FakeProvider(structured_payload=dict(reading or READING), configured=configured)
    client, _ = build_client(tmp_path, provider=provider, classifier=DocumentClassifier(jev))
    return client


def test_the_language_model_alone_fills_every_filter(tmp_path):
    with _client(tmp_path) as client:
        headers = register_admin(client)
        result = client.post(URL, headers=headers, json={"query": "pendents de Pérez de més de 100 €"}).json()

    assert result["filters"]["pagament"] == "Pendent de pagament"
    assert result["filters"]["compte"] == "Material i Sortides"
    assert result["filters"]["min"] == "100"
    assert "tipus" not in result["filters"]
    assert result["search"] == "Pérez"
    assert result["models"] == {"jev": "off", "openai": "ok"}
    # "Aquest curs" becomes September to August.
    assert result["filters"]["des"].endswith("-09-01")
    assert result["filters"]["fins"].endswith("-08-31")


def test_a_confident_jev_overrules_the_language_model(tmp_path):
    jev = FakeJev(
        {
            "compte": JevAnswer(label="Menjador", confidence=0.93),
            "pagament": JevAnswer(label="Pendent de pagament", confidence=0.9),
            "tipus": JevAnswer(label="Albarà", confidence=0.4),
        }
    )
    with _client(tmp_path, jev=jev) as client:
        headers = register_admin(client)
        result = client.post(URL, headers=headers, json={"query": "menjador pendent"}).json()

    assert result["filters"]["compte"] == "Menjador"
    assert result["sources"]["compte"]["source"] == "jev"
    assert result["sources"]["pagament"]["source"] == "jev+openai"
    # An unsure Jev does not add a filter the language model did not see.
    assert "tipus" not in result["filters"]
    # Jev is only ever asked closed questions.
    assert set(jev.questions) == {"tipus", "pagament", "compte", "estat", "enviat", "periode"}


def test_jev_alone_still_filters_when_the_language_model_is_down(tmp_path):
    jev = FakeJev({"estat": JevAnswer(label="needs_validation", confidence=0.8)})
    with _client(tmp_path, jev=jev, configured=False) as client:
        headers = register_admin(client)
        result = client.post(URL, headers=headers, json={"query": "què tinc per revisar"}).json()
    assert result["filters"] == {"estat": "needs_validation"}
    assert result["models"] == {"jev": "ok", "openai": "off"}


def test_no_model_at_all_is_said_plainly(tmp_path):
    with _client(tmp_path, jev=FakeJev(fail=True), configured=False) as client:
        headers = register_admin(client)
        response = client.post(URL, headers=headers, json={"query": "factures"})
    assert response.status_code == 503


def test_explicit_dates_beat_a_named_period(tmp_path):
    reading = {**READING, "date_from": "2026-03-03", "date_to": "2026-03-15"}
    with _client(tmp_path, reading=reading) as client:
        headers = register_admin(client)
        result = client.post(URL, headers=headers, json={"query": "del 3 al 15 de març"}).json()
    assert (result["filters"]["des"], result["filters"]["fins"]) == ("2026-03-03", "2026-03-15")


def test_it_is_the_offices_tool(tmp_path):
    with _client(tmp_path) as client:
        admin = register_admin(client)
        teacher = make_user(client, admin, "professor")
        assert client.post(URL, headers=teacher, json={"query": "factures"}).status_code == 403


@pytest.mark.parametrize(
    ("period", "today", "expected"),
    [
        ("aquest_mes", date(2026, 2, 10), (date(2026, 2, 1), date(2026, 2, 28))),
        ("mes_passat", date(2026, 1, 10), (date(2025, 12, 1), date(2025, 12, 31))),
        ("aquest_trimestre", date(2026, 11, 5), (date(2026, 10, 1), date(2026, 12, 31))),
        ("trimestre_passat", date(2026, 2, 1), (date(2025, 10, 1), date(2025, 12, 31))),
        ("aquest_curs", date(2026, 3, 1), (date(2025, 9, 1), date(2026, 8, 31))),
        ("aquest_curs", date(2026, 10, 11), (date(2026, 9, 1), date(2027, 8, 31))),
        ("curs_passat", date(2026, 10, 11), (date(2025, 9, 1), date(2026, 8, 31))),
        ("any_passat", date(2026, 10, 11), (date(2025, 1, 1), date(2025, 12, 31))),
    ],
)
def test_periods(period, today, expected):
    assert period_range(period, today) == expected


def test_every_answer_is_a_value_the_register_filters_accept():
    from cosecre_hub.schemas.documents import COMPTES, ESTATS_PAGAMENT, TIPUS_DOCUMENT
    from cosecre_hub.services.ai_filter import FIELDS

    allowed = {
        "tipus": set(TIPUS_DOCUMENT),
        "pagament": set(ESTATS_PAGAMENT) | {"—"},
        "compte": set(COMPTES) | {"—"},
        "estat": {"needs_validation", "validated", "error", "active", "unmatched", "outside"},
        "enviat": {"professorat"},
    }
    for name, values in allowed.items():
        labels = {label for label, _ in FIELDS[name].options.values()} - {""}
        assert labels <= values, name
    today = date(2026, 10, 11)
    assert all(period_range(label, today) for label, _ in FIELDS["periode"].options.values() if label)
