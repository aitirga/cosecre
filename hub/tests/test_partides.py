"""Budget lines: the esfer@ import, the secretari/a's assignments, Jev's proposals."""

from __future__ import annotations

import io
import json
from datetime import date

from openpyxl import Workbook

from conftest import build_client, make_user, register_admin
from cosecre_hub.api.partides import esfera, suggest
from cosecre_hub.models import Document
from cosecre_hub.services.classification import DocumentClassifier, JevClient, JevError

API = "/api/v1/partides"


def esfera_export(exercici: int = 2026, *, drop: tuple[str, ...] = ()) -> bytes:
    """The shape of esfer@'s "Dades del pressupost" XLS, as an xlsx."""
    rows = [
        [None] * 5,
        [None, None, None, f"Data: 12/10/{exercici}", None],
        ["Dades del pressupost", None, None, f"Exercici: {exercici}", None],
        ["Nom: Escola de Prova", "Nif: S0800000A", None, "Codi: 08000000", None],
        [None, f"Any Pressupost {exercici}", "Total Ingressos 1.000,00", "Total Despeses 7.500,00", None],
        ["Tipus", "Codi partida", "Codi finalista", "Nom partida", "Import Pressupost"],
        ["Ingressos", None, None, None, None],
        [None, "I/3000001", None, "Venda de béns", 0.0],
        [None, "I/8700001", None, "Romanents d'exercicis anteriors", 1000.0],
        [None, None, None, "Total Ingressos", 1000.0],
        ["Despeses", None, None, None, None],
        [None, "D/220000100/4210", None, "Material d'oficina i didàctic no inventariable", 5000.0],
        [None, "   D/220000100/4210.01", "   MOTXILLES2526", "   25-26 Material escolar INF - MOTXILLES", 2000.0],
        [None, "   D/220000100/4210.29", "   ", "   Material oficina", 3000.0],
        [None, "D/223000100/4210", None, "Transports (autocars per a sortides curriculars)", 2500.0],
        [None, "   D/223000100/4210.11", "   FAMILIESSORTIDES2526", "   25-26 Autocars INFANTIL.", 2500.0],
        [None, "D/226003900/4210", None, "Despeses per comissions bancàries", 0.0],
        [None, None, None, "Total Despeses", 7500.0],
    ]
    book = Workbook()
    sheet = book.active
    for row in rows:
        if row[1] and row[1].strip() in drop:
            continue
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def upload(client, headers, content: bytes, *, dry_run: bool = False):
    return client.post(
        f"{API}/import",
        headers=headers,
        files={"file": ("Dades del pressupost.xlsx", content)},
        data={"dry_run": "true" if dry_run else "false"},
    )


def add_document(client, reference: str = "DOC-1", **values) -> int:
    defaults = {
        "internal_doc_number": reference,
        "tipus_document": "Factura",
        "proveidor": "Autocars Pep SL",
        "cif_proveidor": "B12345678",
        "data_factura": date(2026, 3, 10),
        "import_value": 420.0,
        "descripcio": "Servei d'autocar sortida",
        "descripcio_compra": "Autocar per la sortida d'infantil al Tibidabo",
        "status": "needs_validation",
    }
    defaults.update(values)
    with client.app.state.session_factory() as session:
        document = Document(**defaults)
        session.add(document)
        session.commit()
        return document.id


def lines(client, headers) -> dict[str, dict]:
    return {p["codi"]: p for p in client.get(API, headers=headers).json()["partides"]}


# ── Reading the export ──────────────────────────────────────────────────────


def test_the_parser_reads_the_tree_the_funds_and_the_header():
    budget = esfera.parse(esfera_export(), "x.xlsx")
    assert (budget.exercici, budget.centre, budget.nif, budget.codi_centre) == (
        2026,
        "Escola de Prova",
        "S0800000A",
        "08000000",
    )
    assert budget.total_despeses == 7500.0
    by_code = {p.codi: p for p in budget.partides}
    assert by_code["D/220000100/4210.01"].codi_pare == "D/220000100/4210"
    assert by_code["D/220000100/4210.01"].codi_finalista == "MOTXILLES2526"
    assert by_code["D/220000100/4210.01"].nom == "25-26 Material escolar INF - MOTXILLES"
    assert by_code["D/223000100/4210"].codi_pare is None
    assert by_code["I/3000001"].tipus == "ingres"
    assert esfera.fund_family("PlaDeXoc25_26") == ("PLADEXOC", "Pla de Xoc")
    assert esfera.fund_family("PMOEPROA25_26_FSE")[0] == "PMOEPROA"
    assert esfera.fund_family("FAM_MAT_2324_2425")[0] == "FAMILIESMATERIAL"


def test_a_file_that_is_not_the_export_is_refused_with_where_to_find_it(hub):
    client, _ = hub
    admin = register_admin(client)
    book = Workbook()
    book.active.append(["Data", "Import"])
    buffer = io.BytesIO()
    book.save(buffer)
    response = upload(client, admin, buffer.getvalue())
    assert response.status_code == 422
    assert "Consulta les dades del pressupost" in response.json()["detail"]


# ── Import ──────────────────────────────────────────────────────────────────


def test_a_dry_run_says_what_would_change_and_changes_nothing(hub):
    client, _ = hub
    admin = register_admin(client)
    preview = upload(client, admin, esfera_export(), dry_run=True).json()
    assert preview["dry_run"] is True
    assert preview["created"] == 8
    assert preview["despeses"] == 6
    assert preview["nif_matches"] is None
    assert client.get(API, headers=admin).json()["exercici"] is None

    done = upload(client, admin, esfera_export()).json()
    assert done["created"] == 8
    budget = client.get(API, headers=admin).json()
    assert budget["exercici"] == 2026
    assert budget["centre"] == "Escola de Prova"
    by_code = {p["codi"]: p for p in budget["partides"]}
    assert by_code["D/220000100/4210"]["te_fills"] is True
    assert by_code["D/220000100/4210.01"]["fons"] == "MOTXILLES"
    assert by_code["D/226003900/4210"]["te_fills"] is False


def test_reimporting_keeps_context_and_retires_only_lines_in_use(hub):
    client, _ = hub
    admin = register_admin(client)
    upload(client, admin, esfera_export())
    by_code = lines(client, admin)
    office = by_code["D/220000100/4210.29"]["id"]
    bus = by_code["D/223000100/4210.11"]["id"]
    client.put(f"{API}/lines/{office}/context", headers=admin, json={"context": "Paper i tòner"})
    add_document(client)
    assert client.put(
        f"{API}/documents/DOC-1", headers=admin, json={"partides": [{"partida_id": bus}]}
    ).status_code == 200

    summary = upload(
        client, admin, esfera_export(drop=("D/223000100/4210.11", "D/226003900/4210"))
    ).json()
    assert (summary["retired"], summary["removed"], summary["unchanged"]) == (1, 1, 6)

    after = lines(client, admin)
    assert after["D/220000100/4210.29"]["context"] == "Paper i tòner"
    assert after["D/223000100/4210.11"]["retirada"] is True
    assert "D/226003900/4210" not in after


def test_a_new_year_inherits_what_was_written_about_the_same_line(hub):
    client, _ = hub
    admin = register_admin(client)
    upload(client, admin, esfera_export(2025))
    office = lines(client, admin)["D/220000100/4210.29"]["id"]
    client.put(f"{API}/lines/{office}/context", headers=admin, json={"context": "Paper i tòner"})

    summary = upload(client, admin, esfera_export(2026)).json()
    assert summary["context_inherited"] == 1
    assert lines(client, admin)["D/220000100/4210.29"]["context"] == "Paper i tòner"
    assert client.get(API, headers=admin).json()["exercicis"] == [2026, 2025]


def test_the_import_checks_the_nif_against_the_centre(hub):
    client, _ = hub
    admin = register_admin(client)
    settings = client.get("/api/v1/documents/settings", headers=admin).json()
    settings.pop("classifier_configured")
    settings.pop("drive_folder_configured")
    client.put("/api/v1/documents/settings", headers=admin, json={**settings, "school_cif": "Q0000000J"})
    assert upload(client, admin, esfera_export(), dry_run=True).json()["nif_matches"] is False


# ── Assigning ───────────────────────────────────────────────────────────────


def test_only_the_secretari_writes_the_office_reads(hub):
    client, _ = hub
    admin = register_admin(client)
    office = make_user(client, admin, "administratiu")
    upload(client, admin, esfera_export())
    add_document(client)
    line = lines(client, admin)["D/220000100/4210.29"]["id"]

    assert client.get(API, headers=office).status_code == 200
    assert client.get(f"{API}/queue", headers=office).status_code == 200
    body = {"partides": [{"partida_id": line}]}
    assert client.put(f"{API}/documents/DOC-1", headers=office, json=body).status_code == 403
    assert upload(client, office, esfera_export()).status_code == 403
    assert client.put(f"{API}/context", headers=office, json={"context": "x"}).status_code == 403
    assert (
        client.put(f"{API}/lines/{line}/context", headers=office, json={"context": "x"}).status_code
        == 403
    )
    assert client.post(f"{API}/documents/DOC-1/suggest", headers=office).status_code == 403


def test_an_invoice_takes_several_lines_but_never_a_heading(hub):
    client, _ = hub
    admin = register_admin(client)
    upload(client, admin, esfera_export())
    add_document(client)
    by_code = lines(client, admin)

    heading = client.put(
        f"{API}/documents/DOC-1",
        headers=admin,
        json={"partides": [{"partida_id": by_code["D/220000100/4210"]["id"]}]},
    )
    assert heading.status_code == 422
    assert "subpartides" in heading.json()["detail"]

    split = [
        {"partida_id": by_code["D/223000100/4210.11"]["id"], "import_assignat": 300},
        {"partida_id": by_code["D/220000100/4210.29"]["id"], "import_assignat": 120},
    ]
    item = client.put(f"{API}/documents/DOC-1", headers=admin, json={"partides": split}).json()
    assert item["estat"] == "assignada"
    assert [a["import_assignat"] for a in item["assignments"]] == [300, 120]
    assert lines(client, admin)["D/223000100/4210.11"]["imputat"] == 300

    cleared = client.put(f"{API}/documents/DOC-1", headers=admin, json={"partides": []}).json()
    assert cleared["estat"] == "pendent"


def test_the_queue_leaves_out_quotes_and_documents_being_read(hub):
    client, _ = hub
    admin = register_admin(client)
    add_document(client, "DOC-1")
    add_document(client, "DOC-2", tipus_document="Pressupost")
    add_document(client, "DOC-3", status="processing")
    queue = client.get(f"{API}/queue", headers=admin).json()
    assert [item["reference"] for item in queue] == ["DOC-1"]
    assert queue[0]["curs"] == "25-26"


def test_deleting_an_invoice_forgets_its_lines(hub):
    client, _ = hub
    admin = register_admin(client)
    upload(client, admin, esfera_export())
    add_document(client)
    line = lines(client, admin)["D/220000100/4210.29"]["id"]
    client.put(f"{API}/documents/DOC-1", headers=admin, json={"partides": [{"partida_id": line}]})
    assert client.delete("/api/v1/documents/records/DOC-1", headers=admin).status_code == 204

    from cosecre_hub.api.partides.models import DocumentPartida

    with client.app.state.session_factory() as session:
        assert session.query(DocumentPartida).count() == 0


# ── Jev ─────────────────────────────────────────────────────────────────────


class FakeJev(JevClient):
    def __init__(self, answers=None, fail=False):
        self.model = "jev-fake"
        self.answers = answers
        self.fail = fail
        self.asked: list[tuple[dict, dict]] = []

    def ask(self, state, questions):
        if self.fail:
            raise JevError("down")
        self.asked.append((json.loads(state), questions))
        return self.answers(questions) if callable(self.answers) else dict(self.answers or {})

    def close(self):
        pass


def _jev_client(tmp_path, jev):
    client, _ = build_client(tmp_path, classifier=DocumentClassifier(jev))
    return client


def _prefer(code_ids: dict[str, int], favourite: str, *, split: float = 0.1, runner_up: str | None = None):
    def answer(questions):
        keys = list(questions["partida"]["criteria"])
        probabilities = {key: 0.0 for key in keys}
        probabilities[f"p{code_ids[favourite]}"] = 0.7
        if runner_up:
            probabilities[f"p{code_ids[runner_up]}"] = 0.25
        probabilities["cap"] = 1 - sum(probabilities.values())
        return {
            "partida": {
                "type": "choice",
                "choice": f"p{code_ids[favourite]}",
                "confidence": 0.66,
                "probabilities": probabilities,
            },
            "diverses": {"type": "noul", "noul": split},
        }

    return answer


def test_jev_proposes_a_preliminary_line_from_the_leaves_with_the_context(tmp_path):
    jev = FakeJev()
    with _jev_client(tmp_path, jev) as client:
        admin = register_admin(client)
        upload(client, admin, esfera_export())
        by_code = lines(client, admin)
        ids = {code: line["id"] for code, line in by_code.items()}
        client.put(f"{API}/context", headers=admin, json={"context": "Els autocars van a Transports."})
        client.put(
            f"{API}/lines/{ids['D/223000100/4210.11']}/context",
            headers=admin,
            json={"context": "Sortides d'infantil"},
        )
        jev.answers = _prefer(ids, "D/223000100/4210.11")
        add_document(client)

        item = client.post(f"{API}/documents/DOC-1/suggest", headers=admin).json()

    assert item["estat"] == "proposta"
    assert item["assignments"] == [
        {
            "partida_id": ids["D/223000100/4210.11"],
            "import_assignat": None,
            "origen": "jev",
            "confianca": 0.7,
            "confirmada": False,
        }
    ]
    assert item["suggestion"]["ranking"][0]["partida_id"] == ids["D/223000100/4210.11"]

    state, questions = jev.asked[0]
    assert state["curs_escolar_de_la_factura"] == "25-26"
    assert state["criteris_del_centre"] == "Els autocars van a Transports."
    assert state["factura"]["que_es_compra_segons_el_professor"].startswith("Autocar")
    criteria = questions["partida"]["criteria"]
    # Headings are not options; leaves and the way out are.
    assert f"p{ids['D/220000100/4210']}" not in criteria
    assert f"p{ids['I/3000001']}" not in criteria
    assert criteria[f"p{ids['D/223000100/4210.11']}"]["quan_s_usa"] == "Sortides d'infantil"
    assert criteria[f"p{ids['D/223000100/4210.11']}"]["fons"] == "Famílies · sortides"
    assert "cap" in criteria
    assert questions["diverses"]["type"] == "noul"


def test_jev_never_overwrites_what_a_person_confirmed(tmp_path):
    jev = FakeJev()
    with _jev_client(tmp_path, jev) as client:
        admin = register_admin(client)
        upload(client, admin, esfera_export())
        ids = {code: line["id"] for code, line in lines(client, admin).items()}
        jev.answers = _prefer(ids, "D/223000100/4210.11")
        add_document(client)
        client.put(
            f"{API}/documents/DOC-1",
            headers=admin,
            json={"partides": [{"partida_id": ids["D/220000100/4210.29"]}]},
        )
        item = client.post(f"{API}/documents/DOC-1/suggest", headers=admin).json()

    assert [a["partida_id"] for a in item["assignments"]] == [ids["D/220000100/4210.29"]]
    assert item["assignments"][0]["confirmada"] is True
    assert item["suggestion"] is not None


def test_a_split_purchase_gets_two_lines_and_the_supplier_history_is_a_hint(tmp_path):
    jev = FakeJev()
    with _jev_client(tmp_path, jev) as client:
        admin = register_admin(client)
        upload(client, admin, esfera_export())
        ids = {code: line["id"] for code, line in lines(client, admin).items()}
        add_document(client, "DOC-OLD", data_factura=date(2026, 1, 5))
        client.put(
            f"{API}/documents/DOC-OLD",
            headers=admin,
            json={"partides": [{"partida_id": ids["D/223000100/4210.11"]}]},
        )
        jev.answers = _prefer(ids, "D/223000100/4210.11", split=0.8, runner_up="D/220000100/4210.29")
        add_document(client, "DOC-1", cif_proveidor="B-12345678")
        item = client.post(f"{API}/documents/DOC-1/suggest", headers=admin).json()

    assert [a["partida_id"] for a in item["assignments"]] == [
        ids["D/223000100/4210.11"],
        ids["D/220000100/4210.29"],
    ]
    state, _ = jev.asked[0]
    assert state["partides_anteriors_del_mateix_proveidor"] == [
        {"partida": "25-26 Autocars INFANTIL.", "vegades": 1}
    ]


def test_without_jev_or_a_budget_the_suggestion_says_why(tmp_path, hub):
    client, _ = hub
    admin = register_admin(client)
    add_document(client)
    assert client.post(f"{API}/documents/DOC-1/suggest", headers=admin).status_code == 503

    with _jev_client(tmp_path / "jev", FakeJev(fail=True)) as other:
        (tmp_path / "jev").mkdir(exist_ok=True)
        admin = register_admin(other)
        add_document(other)
        assert other.post(f"{API}/documents/DOC-1/suggest", headers=admin).status_code == 409
        upload(other, admin, esfera_export())
        assert other.post(f"{API}/documents/DOC-1/suggest", headers=admin).status_code == 502


def test_a_school_year_runs_september_to_august():
    assert suggest.school_year(date(2025, 9, 1)) == "25-26"
    assert suggest.school_year(date(2026, 8, 31)) == "25-26"
    assert suggest.school_year(None) == ""


def test_a_split_adds_up_to_the_invoice_or_is_refused(hub):
    client, _ = hub
    admin = register_admin(client)
    upload(client, admin, esfera_export())
    add_document(client)  # 420 €
    by_code = lines(client, admin)
    bus, office = by_code["D/223000100/4210.11"]["id"], by_code["D/220000100/4210.29"]["id"]

    def put(*parts):
        body = {"partides": [{"partida_id": pid, "import_assignat": amount} for pid, amount in parts]}
        return client.put(f"{API}/documents/DOC-1", headers=admin, json=body)

    short = put((bus, 300), (office, 100))
    assert short.status_code == 422
    assert "420.00" in short.json()["detail"]
    assert put((bus, 300), (office, None)).status_code == 422
    assert put((bus, 420), (office, 0)).status_code == 422
    assert put((bus, 315.5), (office, 104.5)).status_code == 200
    # Even, unsplit: allowed, and counted half each.
    assert put((bus, None), (office, None)).status_code == 200
    assert lines(client, admin)["D/223000100/4210.11"]["imputat"] == 210
    # One line takes the whole invoice whatever it was sent with.
    alone = put((bus, 12)).json()
    assert alone["assignments"][0]["import_assignat"] is None
