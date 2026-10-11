"""Teachers send invoices in; the office validates them in the register."""

from __future__ import annotations

import pytest

from conftest import build_client, make_user, register_admin
from fake_sheets import FakeSheets

API = "/api/v1"
JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


@pytest.fixture
def school(tmp_path):
    """``(client, admin, secretaria, teacher, other_teacher)``, all as headers."""
    client, _ = build_client(tmp_path, sheet_service=FakeSheets())
    with client:
        admin = register_admin(client)
        secretaria = make_user(client, admin, "secretaria")
        teacher = make_user(client, admin, "professor", email="laia@example.com")
        other = make_user(client, admin, "professor", email="pau@example.com")
        yield client, admin, secretaria, teacher, other


def submit(client, headers, *, request_id=None, source="camera"):
    data = {"source": source}
    if request_id is not None:
        data["request_id"] = str(request_id)
    return client.post(
        f"{API}/submissions/upload",
        headers=headers,
        files={"file": ("tiquet.jpg", JPEG, "image/jpeg")},
        data=data,
    )


def _notes(client, headers):
    return client.get(f"{API}/notifications", headers=headers).json()


def test_a_teachers_invoice_lands_in_the_register_for_the_office(school):
    client, admin, secretaria, teacher, _other = school
    response = submit(client, teacher)
    assert response.status_code == 200, response.text
    reference = response.json()["internal_doc_number"]

    # Read by the same models as the office's own uploads.
    mine = client.get(f"{API}/submissions", headers=teacher).json()
    assert [s["num_doc_intern"] for s in mine] == [reference]
    assert mine[0]["status"] == "needs_validation"
    assert mine[0]["has_file"] is True

    record = client.get(f"{API}/documents/records/{reference}", headers=secretaria).json()
    assert record["created_by"]["role"] == "professor"
    assert record["created_by"]["name"] == "Professor"

    # The office hears once it has been read, with a link to the entry.
    note = _notes(client, secretaria)[0]
    assert note["kind"] == "document_submitted"
    assert note["link"] == {"name": "register", "query": {"doc": reference}}
    assert _notes(client, admin)[0]["kind"] == "document_submitted"


def test_the_teacher_hears_when_it_is_validated(school):
    client, _admin, secretaria, teacher, _other = school
    reference = submit(client, teacher).json()["internal_doc_number"]

    validated = client.post(f"{API}/documents/records/{reference}/validate", headers=secretaria)
    assert validated.status_code == 200
    note = _notes(client, teacher)[0]
    assert note["kind"] == "document_validated"
    assert note["link"]["name"] == "my-invoices"
    assert client.get(f"{API}/submissions", headers=teacher).json()[0]["validat"] is True


def test_the_office_uploading_its_own_tells_nobody(school):
    client, admin, secretaria, _teacher, _other = school
    assert submit(client, secretaria).status_code == 200
    assert _notes(client, admin) == []


def test_teachers_see_only_their_own(school):
    client, _admin, secretaria, teacher, other = school
    reference = submit(client, teacher).json()["internal_doc_number"]

    assert client.get(f"{API}/submissions", headers=other).json() == []
    assert client.get(f"{API}/submissions/{reference}/file", headers=other).status_code == 404
    assert client.get(f"{API}/submissions/{reference}/file", headers=teacher).status_code == 200
    # The register itself stays the office's.
    assert client.get(f"{API}/documents/records", headers=teacher).status_code == 403
    assert client.get(f"{API}/documents/records/{reference}", headers=teacher).status_code == 403


def test_an_invoice_can_answer_one_of_your_requests(school):
    client, _admin, secretaria, teacher, other = school
    asked = client.post(
        f"{API}/requests",
        headers=teacher,
        json={"kind": "reemborsament", "title": "Material del súper", "amount": 8.9},
    ).json()

    # Not someone else's request.
    assert submit(client, other, request_id=asked["id"]).status_code == 404

    reference = submit(client, teacher, request_id=asked["id"]).json()["internal_doc_number"]
    detail = client.get(f"{API}/requests/{asked['id']}", headers=teacher).json()
    assert [d["num_doc_intern"] for d in detail["documents"]] == [reference]
    assert client.get(f"{API}/requests", headers=secretaria).json()[0]["document_count"] == 1

    record = client.get(f"{API}/documents/records/{reference}", headers=secretaria).json()
    assert record["request_code"] == asked["code"]
    # The office hears about the invoice with the request it belongs to.
    assert asked["code"] in _notes(client, secretaria)[0]["body"]


def test_a_cancelled_request_takes_no_more_invoices(school):
    client, _admin, _secretaria, teacher, _other = school
    asked = client.post(f"{API}/requests", headers=teacher, json={"kind": "compra", "title": "x"}).json()
    client.post(f"{API}/requests/{asked['id']}/status", headers=teacher, json={"status": "cancellada"})
    assert submit(client, teacher, request_id=asked["id"]).status_code == 409


def test_jobs_are_followed_by_their_owner_only(school):
    client, _admin, _secretaria, teacher, other = school
    job_id = submit(client, teacher).json()["job_id"]
    assert client.get(f"{API}/submissions/jobs/{job_id}", headers=teacher).status_code == 200
    assert client.get(f"{API}/submissions/jobs/{job_id}", headers=other).status_code == 404


def test_a_teacher_fills_in_and_validates_their_own(school):
    client, _admin, secretaria, teacher, other = school
    reference = submit(client, teacher).json()["internal_doc_number"]

    record = client.get(f"{API}/submissions/{reference}/record", headers=teacher)
    assert record.status_code == 200
    assert record.json()["num_doc_intern"] == reference
    assert client.get(f"{API}/submissions/{reference}/record", headers=other).status_code == 404

    edited = client.patch(
        f"{API}/submissions/{reference}",
        headers=teacher,
        json={"proveidor": "Llibreria Puig", "validat": True},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["proveidor"] == "Llibreria Puig"
    assert edited.json()["validat"] is True

    # Straight into the register as validated; no office review, and nobody told it to themselves.
    office = client.get(f"{API}/documents/records/{reference}", headers=secretaria).json()
    assert office["validat"] is True
    assert [n for n in _notes(client, teacher) if n["kind"] == "document_validated"] == []

    # From then on it is the office's to change.
    again = client.patch(f"{API}/submissions/{reference}", headers=teacher, json={"proveidor": "Una altra"})
    assert again.status_code == 409


def test_nobody_edits_someone_elses(school):
    client, _admin, _secretaria, teacher, other = school
    reference = submit(client, teacher).json()["internal_doc_number"]
    response = client.patch(f"{API}/submissions/{reference}", headers=other, json={"proveidor": "X"})
    assert response.status_code == 404


def test_only_an_invoice_made_out_to_the_centre_can_be_validated(school):
    client, admin, _secretaria, teacher, _other = school
    settings = client.get(f"{API}/documents/settings", headers=admin).json()
    saved = client.put(f"{API}/documents/settings", headers=admin, json={**settings, "school_cif": "s-0800636 c"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["school_cif"] == "S0800636C"
    assert client.get(f"{API}/submissions/centre", headers=teacher).json() == {"cif": "S0800636C"}

    reference = submit(client, teacher).json()["internal_doc_number"]
    wrong = client.patch(
        f"{API}/submissions/{reference}", headers=teacher, json={"cif_proveit": "B12345678", "validat": True}
    )
    assert wrong.status_code == 409
    assert "S0800636C" in wrong.json()["detail"]

    right = client.patch(
        f"{API}/submissions/{reference}", headers=teacher, json={"cif_proveit": "S 0800636-C", "validat": True}
    )
    assert right.status_code == 200, right.text
    assert right.json()["validat"] is True
