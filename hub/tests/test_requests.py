"""Requests to the office: who sees them, who moves them, who is told."""

from __future__ import annotations

from conftest import make_user, register_admin

API = "/api/v1"


def _people(client):
    admin = register_admin(client)
    secretaria = make_user(client, admin, "secretaria")
    teacher = make_user(client, admin, "professor", email="laia@example.com")
    other = make_user(client, admin, "professor", email="pau@example.com")
    return admin, secretaria, teacher, other


def _ask(client, headers, **overrides):
    body = {
        "kind": "compra",
        "title": "Plastilina per a P5",
        "description": "Per al taller de dijous.",
        "amount": 42.5,
        "proveidor": "Papereria Pérez",
        "compte": "Material i Sortides",
        **overrides,
    }
    response = client.post(f"{API}/requests", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _count(client, headers):
    return client.get(f"{API}/notifications/unread-count", headers=headers).json()["count"]


def test_a_teacher_asks_and_the_office_hears(hub):
    client, _ = hub
    admin, secretaria, teacher, _other = _people(client)

    created = _ask(client, teacher)
    assert created["code"] == f"SOL-{created['id']:04d}"
    assert created["status"] == "oberta"
    assert created["requester"]["role"] == "professor"
    assert created["allowed_statuses"] == ["cancellada"]

    # Everyone in the office is told; the teacher who asked is not.
    assert _count(client, admin) == 1
    assert _count(client, secretaria) == 1
    assert _count(client, teacher) == 0
    note = client.get(f"{API}/notifications", headers=secretaria).json()[0]
    assert note["link"] == {"name": "requests", "query": {"sol": str(created["id"])}}
    assert "Compra" in note["title"]


def test_teachers_see_only_their_own(hub):
    client, _ = hub
    _admin, secretaria, teacher, other = _people(client)
    mine = _ask(client, teacher)
    _ask(client, other, kind="consulta", title="Quan es paga la sortida?")

    assert [r["id"] for r in client.get(f"{API}/requests", headers=teacher).json()] == [mine["id"]]
    assert len(client.get(f"{API}/requests", headers=secretaria).json()) == 2
    assert client.get(f"{API}/requests/{mine['id']}", headers=other).status_code == 404
    assert (
        client.post(f"{API}/requests/{mine['id']}/messages", headers=other, json={"body": "hola"}).status_code
        == 404
    )


def test_a_question_carries_no_money(hub):
    client, _ = hub
    _admin, _secretaria, teacher, _other = _people(client)
    asked = _ask(client, teacher, kind="consulta", title="Dubte", amount=10, compte="General")
    assert asked["amount"] is None
    assert asked["compte"] == ""


def test_an_unknown_account_is_refused(hub):
    client, _ = hub
    _admin, _secretaria, teacher, _other = _people(client)
    response = client.post(
        f"{API}/requests", headers=teacher, json={"kind": "compra", "title": "x", "compte": "Banc"}
    )
    assert response.status_code == 422


def test_the_office_replying_takes_the_request(hub):
    client, _ = hub
    _admin, secretaria, teacher, _other = _people(client)
    asked = _ask(client, teacher)

    replied = client.post(
        f"{API}/requests/{asked['id']}/messages", headers=secretaria, json={"body": "Ho mirem avui."}
    ).json()
    assert replied["status"] == "en_revisio"
    assert replied["assignee"]["role"] == "secretaria"
    assert [m["kind"] for m in replied["messages"]] == ["message", "status"]
    assert _count(client, teacher) == 1

    # The teacher answers: only the assignee hears, not the whole office.
    client.post(f"{API}/requests/{asked['id']}/messages", headers=teacher, json={"body": "Gràcies!"})
    assert _count(client, secretaria) == 2  # the new request, then the reply


def test_status_moves_follow_the_rules(hub):
    client, _ = hub
    _admin, secretaria, teacher, _other = _people(client)
    asked = _ask(client, teacher)
    rid = asked["id"]

    # A teacher cannot approve their own purchase.
    assert client.post(f"{API}/requests/{rid}/status", headers=teacher, json={"status": "aprovada"}).status_code == 409
    # Refusing needs a reason.
    assert client.post(f"{API}/requests/{rid}/status", headers=secretaria, json={"status": "rebutjada"}).status_code == 422

    approved = client.post(
        f"{API}/requests/{rid}/status", headers=secretaria, json={"status": "aprovada", "note": "Endavant."}
    ).json()
    assert approved["status"] == "aprovada"
    assert approved["allowed_statuses"] == ["en_revisio", "resolta"]
    # Decided: too late for the teacher to withdraw it.
    assert client.post(f"{API}/requests/{rid}/status", headers=teacher, json={"status": "cancellada"}).status_code == 409
    notes = client.get(f"{API}/notifications", headers=teacher).json()
    assert notes[0]["body"] == "Endavant."


def test_a_teacher_withdraws_a_request_and_the_thread_closes(hub):
    client, _ = hub
    _admin, secretaria, teacher, _other = _people(client)
    rid = _ask(client, teacher)["id"]

    cancelled = client.post(f"{API}/requests/{rid}/status", headers=teacher, json={"status": "cancellada"}).json()
    assert cancelled["status"] == "cancellada"
    assert cancelled["can_reply"] is False
    assert client.post(f"{API}/requests/{rid}/messages", headers=secretaria, json={"body": "?"}).status_code == 409
    assert _count(client, secretaria) == 2  # created, then withdrawn


def test_assigning_tells_the_assignee_and_only_office_can(hub):
    client, _ = hub
    admin, secretaria, teacher, _other = _people(client)
    rid = _ask(client, teacher)["id"]
    secretaria_id = client.get(f"{API}/auth/me", headers=secretaria).json()["id"]
    teacher_id = client.get(f"{API}/auth/me", headers=teacher).json()["id"]

    assert client.post(f"{API}/requests/{rid}/assign", headers=teacher, json={"assignee_id": secretaria_id}).status_code == 403
    assert client.post(f"{API}/requests/{rid}/assign", headers=admin, json={"assignee_id": teacher_id}).status_code == 422

    assigned = client.post(f"{API}/requests/{rid}/assign", headers=admin, json={"assignee_id": secretaria_id})
    assert assigned.status_code == 200
    assert _count(client, secretaria) == 2


def test_notifications_are_private_and_can_be_read(hub):
    client, _ = hub
    admin, secretaria, teacher, _other = _people(client)
    _ask(client, teacher)
    _ask(client, teacher, title="Una altra")

    mine = client.get(f"{API}/notifications", headers=secretaria).json()
    assert len(mine) == 2
    assert client.post(f"{API}/notifications/{mine[0]['id']}/read", headers=admin).status_code == 404
    assert client.post(f"{API}/notifications/{mine[0]['id']}/read", headers=secretaria).status_code == 200
    assert _count(client, secretaria) == 1

    client.post(f"{API}/notifications/read-all", headers=secretaria)
    assert _count(client, secretaria) == 0
    assert _count(client, admin) == 2


def test_the_office_list_is_the_office_only(hub):
    client, _ = hub
    _admin, secretaria, teacher, _other = _people(client)
    people = client.get(f"{API}/requests/office", headers=secretaria).json()
    assert sorted(p["role"] for p in people) == ["admin", "secretaria"]
    assert client.get(f"{API}/requests/office", headers=teacher).status_code == 403
