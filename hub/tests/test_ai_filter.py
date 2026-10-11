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
    "kind": "filtre",
    "sql": "",
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


def _client(tmp_path, *, reading=None, jev=None, configured=True, provider=None):
    provider = provider or FakeProvider(structured_payload=dict(reading or READING), configured=configured)
    client, _ = build_client(tmp_path, provider=provider, classifier=DocumentClassifier(jev))
    return client


def sure(**labels):
    """Jev confident on every question; ``labels`` set the ones that say something."""
    answers = {name: JevAnswer(label="", confidence=0.97) for name in ("tipus", "pagament", "compte", "estat", "enviat", "periode")}
    answers["mode"] = JevAnswer(label="llista", confidence=0.95)
    answers["obert"] = JevAnswer(label="no", confidence=0.95)
    answers.update({name: JevAnswer(label=label, confidence=0.95) for name, label in labels.items()})
    return answers


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
    # Jev is only ever asked closed questions — the filters, and whether there is more to read.
    assert set(jev.questions) == {"tipus", "pagament", "compte", "estat", "enviat", "periode", "mode", "obert"}


def test_jev_alone_still_filters_when_the_language_model_is_down(tmp_path):
    jev = FakeJev({"estat": JevAnswer(label="needs_validation", confidence=0.8)})
    with _client(tmp_path, jev=jev, configured=False) as client:
        headers = register_admin(client)
        result = client.post(URL, headers=headers, json={"query": "què tinc per revisar"}).json()
    assert result["filters"] == {"estat": "needs_validation"}
    assert result["models"] == {"jev": "ok", "openai": "off"}


def test_a_question_jev_settles_never_reaches_the_language_model(tmp_path):
    provider = FakeProvider(structured_payload=dict(READING))
    jev = FakeJev(sure(pagament="Pendent de pagament", compte="Menjador", periode="aquest_curs"))
    with _client(tmp_path, jev=jev, provider=provider) as client:
        headers = register_admin(client)
        result = client.post(URL, headers=headers, json={"query": "menjador pendent d'aquest curs"}).json()

    assert provider.structures == []
    assert result["models"] == {"jev": "ok", "openai": "skipped"}
    assert result["filters"]["pagament"] == "Pendent de pagament"
    assert result["filters"]["compte"] == "Menjador"
    assert result["filters"]["des"].endswith("-09-01")
    assert result["search"] == ""
    assert result["explanation"] == "Documents pendents de pagament del compte Menjador d'aquest curs."


@pytest.mark.parametrize(
    ("query", "answers"),
    [
        # Something open to read: a name.
        ("pendents de Pérez", sure(pagament="Pendent de pagament", obert="si")),
        # Jev unsure of one answer.
        ("material", {**sure(), "compte": JevAnswer(label="Material i Sortides", confidence=0.7)}),
        # A digit is an amount, a date or a number, whatever Jev thinks.
        ("més de 100 €", sure()),
        # A figure needs a query only the language model can write.
        ("quant hem gastat", sure(mode="xifra")),
    ],
)
def test_the_language_model_steps_in_when_jev_cannot_finish(tmp_path, query, answers):
    provider = FakeProvider(structured_payload=dict(READING))
    with _client(tmp_path, jev=FakeJev(answers), provider=provider) as client:
        headers = register_admin(client)
        result = client.post(URL, headers=headers, json={"query": query}).json()
    assert len(provider.structures) == 1
    assert result["models"] == {"jev": "ok", "openai": "ok"}
    assert result["search"] == "Pérez"


def _entry(session, ref, **fields):
    from cosecre_hub.models import Document

    session.add(Document(internal_doc_number=ref, status="needs_validation", **fields))


def test_a_question_for_a_figure_is_answered_with_a_query_and_its_filters(tmp_path):
    reading = {
        **READING,
        "kind": "pregunta",
        "pagament": "cap",
        "text": "",
        "sql": (
            "SELECT proveidor AS \"Proveïdor\", ROUND(SUM(import), 2) AS \"Total (€)\" "
            "FROM documents WHERE compte = 'Material i Sortides' GROUP BY proveidor ORDER BY 2 DESC LIMIT 20"
        ),
        "explanation": "Despesa per proveïdor al compte de Material i Sortides aquest curs.",
    }
    with _client(tmp_path, reading=reading) as client:
        headers = register_admin(client)
        with client.app.state.session_factory() as session:
            _entry(session, "DOC-1", proveidor="Pérez", import_value=40.0, pressupost_afectat="Material i Sortides")
            _entry(session, "DOC-2", proveidor="Pérez", import_value=60.5, pressupost_afectat="Material i Sortides")
            _entry(session, "DOC-3", proveidor="Abacus", import_value=20.0, pressupost_afectat="Material i Sortides")
            _entry(session, "DOC-4", proveidor="Càtering", import_value=900.0, pressupost_afectat="Menjador")
            session.commit()
        result = client.post(URL, headers=headers, json={"query": "a qui hem comprat més material aquest curs"}).json()

    answer = result["answer"]
    assert answer["error"] is None
    assert answer["columns"] == ["Proveïdor", "Total (€)"]
    assert answer["rows"] == [["Pérez", 100.5], ["Abacus", 20.0]]
    # The list underneath shows the documents behind the figure.
    assert result["filters"]["compte"] == "Material i Sortides"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT email, hashed_password FROM users",
        "DELETE FROM documents",
        "SELECT 1; DROP TABLE documents",
        "ATTACH DATABASE '/tmp/x.db' AS x",
        "PRAGMA table_info(documents)",
        "SELECT load_extension('x')",
        "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) SELECT count(*) FROM n",
    ],
)
def test_a_query_reads_the_register_and_nothing_else(tmp_path, sql):
    from cosecre_hub.services.register_sql import QueryRefused, run_query

    with _client(tmp_path) as client:
        with client.app.state.session_factory() as session:
            with pytest.raises(QueryRefused):
                run_query(session, sql)


def test_a_query_that_fails_still_leaves_the_filters(tmp_path):
    reading = {**READING, "kind": "pregunta", "sql": "SELECT nope FROM documents"}
    with _client(tmp_path, reading=reading) as client:
        headers = register_admin(client)
        result = client.post(URL, headers=headers, json={"query": "quants pendents de Pérez"}).json()
    assert result["answer"]["error"].startswith("La consulta no és vàlida")
    assert result["filters"]["pagament"] == "Pendent de pagament"


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
