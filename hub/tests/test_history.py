from __future__ import annotations

from datetime import date

from test_documents import RECORDS, register, upload  # noqa: F401  (fixture)

from cosecre_hub.models import BankMovement, Document, PaymentMatch, StatementImport

HISTORY = "/api/v1/history"


def _sync(client, headers):
    return client.post(f"{RECORDS}/sync", headers=headers).json()


def _record(client, headers, reference):
    return client.get(f"{RECORDS}/{reference}", headers=headers)


def test_an_edit_is_undone_and_redone_and_the_sheet_follows(register):
    client, headers, sheet, _ = register
    reference = upload(client, headers)
    client.patch(f"{RECORDS}/{reference}", headers=headers, json={"descripcio": "Pintura"})
    assert sheet.row_for(reference)["descripcio"] == "Pintura"

    state = client.get(HISTORY, headers=headers).json()
    assert state["undo"]["label"] == "Document editat"
    assert state["undo"]["detail"].startswith("F-2026/001")

    undone = client.post(f"{HISTORY}/undo", headers=headers)
    assert undone.status_code == 200, undone.text
    assert undone.json()["message"] == "Desfet: Document editat"
    assert _record(client, headers, reference).json()["descripcio"] == "Material de ferreteria"
    assert sheet.row_for(reference)["descripcio"] == "Material de ferreteria"

    assert client.get(HISTORY, headers=headers).json()["redo"]["label"] == "Document editat"
    assert client.post(f"{HISTORY}/redo", headers=headers).status_code == 200
    assert _record(client, headers, reference).json()["descripcio"] == "Pintura"
    assert sheet.row_for(reference)["descripcio"] == "Pintura"


def test_a_new_change_ends_what_could_be_redone(register):
    client, headers, _, _ = register
    reference = upload(client, headers)
    client.patch(f"{RECORDS}/{reference}", headers=headers, json={"descripcio": "A"})
    client.post(f"{HISTORY}/undo", headers=headers)
    client.patch(f"{RECORDS}/{reference}", headers=headers, json={"descripcio": "B"})
    assert client.get(HISTORY, headers=headers).json()["redo"] is None


def test_a_deleted_document_comes_back_with_its_row_and_drive_file(register):
    client, headers, sheet, _ = register
    reference = upload(client, headers)
    assert client.delete(f"{RECORDS}/{reference}", headers=headers).status_code == 204
    assert not sheet.rows and not sheet.drive and len(sheet.trash) == 1

    assert client.post(f"{HISTORY}/undo", headers=headers).status_code == 200
    record = _record(client, headers, reference)
    assert record.status_code == 200 and record.json()["file_url"]
    assert sheet.row_for(reference)["num_factura"] == "F-2026/001"
    assert len(sheet.drive) == 1 and not sheet.trash

    # And deleting it again is a redo away.
    assert client.post(f"{HISTORY}/redo", headers=headers).status_code == 200
    assert _record(client, headers, reference).status_code == 404
    assert not sheet.rows


def test_an_upload_can_be_undone(register):
    client, headers, sheet, _ = register
    reference = upload(client, headers)
    state = client.get(HISTORY, headers=headers).json()
    assert state["undo"]["label"] == "Document pujat"
    assert client.post(f"{HISTORY}/undo", headers=headers).status_code == 200
    assert _record(client, headers, reference).status_code == 404
    assert not sheet.rows and not sheet.drive


def test_an_undo_never_overwrites_a_later_change(register):
    client, headers, _, _ = register
    reference = upload(client, headers)
    client.patch(f"{RECORDS}/{reference}", headers=headers, json={"descripcio": "Primer"})
    first = client.get(HISTORY, headers=headers).json()["undo"]["id"]
    client.patch(f"{RECORDS}/{reference}", headers=headers, json={"descripcio": "Segon"})

    refused = client.post(f"{HISTORY}/{first}/undo", headers=headers)
    assert refused.status_code == 409
    assert "s'ha tornat a canviar" in refused.json()["detail"]
    assert _record(client, headers, reference).json()["descripcio"] == "Segon"


def test_undo_is_per_person_and_history_shows_everyone(register):
    client, headers, _, _ = register
    reference = upload(client, headers)
    client.patch(f"{RECORDS}/{reference}", headers=headers, json={"descripcio": "Meu"})
    created = client.post("/api/v1/users", headers=headers, json={
        "email": "altra@xtec.cat", "password": "supersecure2", "display_name": "Altra",
    })
    assert created.status_code in (200, 201), created.text
    login = client.post("/api/v1/auth/login", json={"email": "altra@xtec.cat", "password": "supersecure2"}).json()
    other = {"Authorization": f"Bearer {login['access_token']}"}

    state = client.get(HISTORY, headers=other).json()
    assert state["undo"] is None
    assert [a["label"] for a in state["actions"]][:2] == ["Document editat", "Document pujat"]
    assert client.post(f"{HISTORY}/undo", headers=other).status_code == 404


def test_a_restored_duplicate_comes_back_and_stays(register):
    client, headers, sheet, _ = register
    first = upload(client, headers)
    second = upload(client, headers)
    _sync(client, headers)
    removed = client.get("/api/v1/documents/duplicates", headers=headers).json()
    assert [r["reference"] for r in removed] == [second] and removed[0]["restored_at"] is None

    assert client.post(f"{HISTORY}/{removed[0]['action_id']}/undo", headers=headers).status_code == 200
    _sync(client, headers)
    _sync(client, headers)

    assert {d["num_doc_intern"] for d in client.get(RECORDS, headers=headers).json()} == {first, second}
    assert {row["num_doc_intern"] for row in sheet.rows.values()} == {first, second}
    assert client.get("/api/v1/documents/duplicates", headers=headers).json()[0]["restored_at"]


def test_changes_made_in_bulk_are_recorded_too(register):
    client, headers, _, _ = register
    reference = upload(client, headers)
    with client.app.state.session_factory() as session:
        document = session.query(Document).filter_by(internal_doc_number=reference).one()
        statement = StatementImport(source="caixa_xls", compte="General")
        session.add(statement)
        session.flush()
        movement = BankMovement(
            import_id=statement.id, fingerprint="m1", source="caixa_xls", compte="General",
            data=date(2026, 2, 1), import_value=-100.0, match_status="proposed",
        )
        session.add(movement)
        session.flush()
        session.add(PaymentMatch(movement_id=movement.id, document_id=document.id, status="proposed"))
        session.commit()
        movement_id = movement.id

    changed = client.patch(f"/api/v1/statements/movements/{movement_id}", headers=headers, json={"categoria": "comissio"})
    assert changed.status_code == 200, changed.text
    with client.app.state.session_factory() as session:
        assert session.query(PaymentMatch).count() == 0

    assert client.post(f"{HISTORY}/undo", headers=headers).status_code == 200
    with client.app.state.session_factory() as session:
        assert session.query(PaymentMatch).count() == 1
        assert session.get(BankMovement, movement_id).categoria == "pagament"
