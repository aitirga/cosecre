from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from conftest import FakeProvider, build_client, make_user, register_admin
from fake_sheets import FakeSheets
from test_documents import RECORDS, upload

from cosecre_hub.services.assistant.sandbox import QueryRefused, Sandbox
from cosecre_hub.services.llm import ToolCall, ToolEvent, ToolSession, ToolTurnRequest, Usage

ASSISTANT = "/api/v1/assistant"


# ── A model that follows a script ────────────────────────────────────────────


@dataclass
class ScriptedSession(ToolSession):
    provider: "ToolProvider"
    request: ToolTurnRequest

    def step(self) -> Iterator[ToolEvent]:
        script = self.provider.script.pop(0)
        if callable(script):
            script = script(self.provider)
        text, calls = script if isinstance(script, tuple) else (script, [])
        if text:
            yield ToolEvent(type="delta", text=text)
        yield ToolEvent(
            type="completed",
            text=text,
            tool_calls=[
                ToolCall(call_id=f"call-{index}", name=name, arguments=json.dumps(args))
                for index, (name, args) in enumerate(calls)
            ],
            usage=Usage(input_tokens=10, output_tokens=5),
            model="fake-tools",
        )

    def add_results(self, results: list[tuple[str, str]]) -> None:
        self.provider.results.append(results)


@dataclass
class ToolProvider(FakeProvider):
    #: One entry per model step: answer text, ``(text, [(tool, args)])``, or a
    #: function of the provider returning either (to use earlier results).
    script: list[Any] = field(default_factory=list)
    results: list[list[tuple[str, str]]] = field(default_factory=list)
    requests: list[ToolTurnRequest] = field(default_factory=list)

    def start_tools(self, request: ToolTurnRequest) -> ToolSession:
        self._guard()
        self.requests.append(request)
        return ScriptedSession(self, request)


@pytest.fixture
def office(tmp_path):
    """``(client, headers, sheet, provider)``: an admin, a fake sheet and a scripted model."""
    sheet = FakeSheets()
    provider = ToolProvider()
    client, _ = build_client(tmp_path, sheet_service=sheet, provider=provider)
    with client:
        yield client, register_admin(client), sheet, provider


def _conversation(client, headers) -> int:
    response = client.post(f"{ASSISTANT}/conversations", headers=headers, json={})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _ask(client, headers, conversation_id: int, text: str) -> list[dict[str, Any]]:
    response = client.post(
        f"{ASSISTANT}/conversations/{conversation_id}/messages", headers=headers, json={"text": text}
    )
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines() if line]


def _output(provider: ToolProvider, step: int = 0, call: int = 0) -> str:
    return provider.results[step][call][1]


# ── The sandbox ──────────────────────────────────────────────────────────────


def test_the_sandbox_reads_the_copy_and_refuses_everything_else(office):
    client, headers, _, _ = office
    upload(client, headers)
    session = client.app.state.session_factory()
    sandbox = Sandbox(session)
    try:
        result = sandbox.query("SELECT internal_doc_number, import_value FROM documents")
        assert result.rows == [["DOC-0001", 100.0]] or len(result.rows) == 1
        assert sandbox.query("SELECT email, role FROM users").rows[0][1] == "admin"

        for refused in (
            "DELETE FROM documents",
            "UPDATE documents SET import_value = 1",
            "SELECT password_hash FROM users",
            "SELECT * FROM refresh_sessions",
            "SELECT 1; SELECT 2",
            "ATTACH DATABASE 'x.db' AS other",
            "WITH x AS (SELECT 1) DELETE FROM documents",
            "SELECT load_extension('evil')",
            "PRAGMA table_info(documents)",
        ):
            with pytest.raises(QueryRefused):
                sandbox.query(refused)
        # The copy is all it could ever reach; the hub's own table is untouched.
        assert session.execute(__import__("sqlalchemy").text("SELECT count(*) FROM documents")).scalar() == 1
    finally:
        sandbox.close()
        session.close()


# ── Chats ────────────────────────────────────────────────────────────────────


def test_a_question_is_answered_with_a_query_a_table_and_a_chart(office):
    client, headers, _, provider = office
    upload(client, headers)
    provider.script = [
        ("Ho miro.", [("run_sql", {"sql": "SELECT count(*) AS n, sum(import_value) AS total FROM documents"})]),
        (
            "",
            [
                ("show_table", {"title": "Per proveïdor", "sql": "SELECT proveidor AS \"Proveïdor\", sum(import_value) AS \"Total\" FROM documents GROUP BY 1"}),
                ("show_chart", {"title": "Per mes", "kind": "bar", "sql": "SELECT substr(data_factura,1,7) AS mes, sum(import_value) AS total FROM documents GROUP BY 1", "unit": "€"}),
            ],
        ),
        "Hi ha **1** document, per 100,00 €.",
    ]
    conversation_id = _conversation(client, headers)
    frames = _ask(client, headers, conversation_id, "Quant hem gastat?")

    assert frames[0]["type"] == "user"
    assert frames[-1]["type"] == "done", frames[-1]
    assert json.loads(_output(provider))["rows"] == [[1, 100.0]]
    message = frames[-1]["message"]
    kinds = [block["type"] for block in message["blocks"]]
    assert kinds == ["text", "step", "table", "chart", "text"]
    table = message["blocks"][2]
    assert table["columns"] == ["Proveïdor", "Total"] and table["rows"][0][1] == 100.0
    chart = message["blocks"][3]
    assert chart["labels"] == ["2026-01"] and chart["series"][0]["values"] == [100.0]
    assert message["content"] == "Ho miro.\n\nHi ha **1** document, per 100,00 €."

    # The model was told about the database and who it is talking to.
    request = provider.requests[0]
    assert "documents" in request.instructions and "admin@example.com" in request.instructions
    assert {tool.name for tool in request.tools} >= {"run_sql", "propose_changes", "call_api"}

    # Saved, and titled after the first question.
    read = client.get(f"{ASSISTANT}/conversations/{conversation_id}", headers=headers).json()
    assert read["title"] == "Quant hem gastat?"
    assert [m["role"] for m in read["messages"]] == ["user", "assistant"]


def test_a_refused_query_goes_back_to_the_model_as_an_error(office):
    client, headers, _, provider = office
    provider.script = [
        ("", [("run_sql", {"sql": "DELETE FROM documents"})]),
        "No puc fer-ho així.",
    ]
    frames = _ask(client, headers, _conversation(client, headers), "Esborra-ho tot")
    assert _output(provider).startswith("Error:")
    step = next(b for b in frames[-1]["message"]["blocks"] if b["type"] == "step")
    assert step["ok"] is False


def test_the_api_can_be_read_as_the_person_but_not_its_secrets(office):
    client, headers, _, provider = office
    reference = upload(client, headers)
    provider.script = [
        ("", [
            ("call_api", {"path": f"/documents/records/{reference}"}),
            ("call_api", {"path": "/auth/sessions"}),
            ("call_api", {"path": f"/documents/records/{reference}/file"}),
            ("list_api", {"search": "documents records"}),
        ]),
        "Fet.",
    ]
    _ask(client, headers, _conversation(client, headers), "Llegeix")
    assert json.loads(_output(provider, 0, 0))["num_factura"] == "F-2026/001"
    assert _output(provider, 0, 1).startswith("Error:")
    assert _output(provider, 0, 2).startswith("Error:")
    catalog = _output(provider, 0, 3)
    assert "PATCH /documents/records/{reference}" in catalog and "import" in catalog


def test_chats_are_private_and_can_be_deleted(office):
    client, admin, _, provider = office
    secretaria = make_user(client, admin, "secretaria")
    provider.script = ["Hola!"]
    mine = _conversation(client, admin)
    _ask(client, admin, mine, "Hola")

    assert client.get(f"{ASSISTANT}/conversations", headers=secretaria).json() == []
    assert client.get(f"{ASSISTANT}/conversations/{mine}", headers=secretaria).status_code == 404
    assert client.delete(f"{ASSISTANT}/conversations/{mine}", headers=secretaria).status_code == 404

    assert client.delete(f"{ASSISTANT}/conversations/{mine}", headers=admin).status_code == 204
    assert client.get(f"{ASSISTANT}/conversations", headers=admin).json() == []


def test_teachers_have_no_assistant(office):
    client, admin, _, _ = office
    teacher = make_user(client, admin, "professor")
    assert client.get(f"{ASSISTANT}/conversations", headers=teacher).status_code == 403


def test_without_a_model_the_chat_says_so(tmp_path):
    client, _ = build_client(tmp_path, provider=ToolProvider(configured=False))
    with client:
        headers = register_admin(client)
        assert client.get(f"{ASSISTANT}/status", headers=headers).json()["ready"] is False
        conversation_id = _conversation(client, headers)
        response = client.post(
            f"{ASSISTANT}/conversations/{conversation_id}/messages", headers=headers, json={"text": "Hola"}
        )
        assert response.status_code == 503


def test_the_assistant_model_comes_from_the_config(tmp_path):
    provider = ToolProvider(script=["Hola"])
    client, _ = build_client(
        tmp_path, provider=provider, assistant_model="gpt-6.1-sol", assistant_reasoning_effort="medium"
    )
    with client:
        headers = register_admin(client)
        status = client.get(f"{ASSISTANT}/status", headers=headers).json()
        assert status["model"] == "gpt-6.1-sol" and status["reasoning_effort"] == "medium"
        _ask(client, headers, _conversation(client, headers), "Hola")
    assert provider.requests[0].model == "gpt-6.1-sol"
    assert provider.requests[0].reasoning_effort == "medium"


# ── Proposals ────────────────────────────────────────────────────────────────


def _propose(client, headers, provider, actions, summary="Import a 100 €"):
    provider.script = [("", [("propose_changes", {"summary": summary, "actions": actions})]), "Revisa-ho."]
    conversation_id = _conversation(client, headers)
    frames = _ask(client, headers, conversation_id, "Canvia-ho")
    block = next(b for b in frames[-1]["message"]["blocks"] if b["type"] == "proposal")
    return conversation_id, block["proposal"]


def test_a_proposal_changes_nothing_until_applied_and_undoes_in_one_go(office):
    client, headers, sheet, provider = office
    first = upload(client, headers)
    # A second entry the hub will not take for a duplicate of the first.
    client.patch(f"{RECORDS}/{first}", headers=headers, json={"num_factura": "F-2026/000"})
    second = upload(client, headers, content=b"\xff\xd8\xff other")
    conversation_id, proposal = _propose(
        client,
        headers,
        provider,
        [
            {"method": "PATCH", "path": f"/documents/records/{first}", "body": {"import": 100}, "label": first},
            {"method": "PATCH", "path": f"/documents/records/{second}", "body": {"import": 100, "descripcio": "Revisat"}},
        ],
    )
    assert "NO s'ha canviat res" in _output(provider)
    assert proposal["status"] == "pending"
    assert proposal["actions"][1]["changes"] == [
        {"field": "import", "before": 100.0, "after": 100},
        {"field": "descripcio", "before": "Material de ferreteria", "after": "Revisat"},
    ]
    assert client.get(f"{RECORDS}/{second}", headers=headers).json()["descripcio"] == "Material de ferreteria"

    applied = client.post(f"{ASSISTANT}/proposals/{proposal['id']}/apply", headers=headers)
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    assert client.get(f"{RECORDS}/{second}", headers=headers).json()["descripcio"] == "Revisat"
    assert sheet.row_for(second)["descripcio"] == "Revisat"

    history = client.get("/api/v1/history", headers=headers).json()
    assert history["undo"]["label"] == "Assistent: Import a 100 €"
    assert history["undo"]["id"] == applied.json()["history_action_id"]
    assert client.post("/api/v1/history/undo", headers=headers).status_code == 200
    assert client.get(f"{RECORDS}/{second}", headers=headers).json()["descripcio"] == "Material de ferreteria"

    # Applying twice is refused; and the model hears how it went next time.
    assert client.post(f"{ASSISTANT}/proposals/{proposal['id']}/apply", headers=headers).status_code == 409
    provider.script = ["D'acord."]
    _ask(client, headers, conversation_id, "I ara?")
    replay = provider.requests[-1].messages[1].content
    assert f"Proposta #{proposal['id']}" in replay and "aplicada" in replay


def test_a_proposal_is_refused_when_the_data_moved_since(office):
    client, headers, _, provider = office
    reference = upload(client, headers)
    _, proposal = _propose(
        client, headers, provider,
        [{"method": "PATCH", "path": f"/documents/records/{reference}", "body": {"descripcio": "IA"}}],
    )
    client.patch(f"{RECORDS}/{reference}", headers=headers, json={"descripcio": "A mà"})
    applied = client.post(f"{ASSISTANT}/proposals/{proposal['id']}/apply", headers=headers).json()
    assert applied["status"] == "stale" and "descripcio" in applied["detail"]
    assert client.get(f"{RECORDS}/{reference}", headers=headers).json()["descripcio"] == "A mà"


def test_a_proposal_cannot_reach_accounts_or_backups(office):
    client, headers, _, provider = office
    for action in (
        {"method": "PATCH", "path": "/users/1", "body": {"role": "admin"}},
        {"method": "POST", "path": "/backups/x/restore"},
        {"method": "POST", "path": "/history/undo"},
        {"method": "PATCH", "path": "/no/such/route"},
        {"method": "GET", "path": "/documents/records"},
    ):
        provider.script = [("", [("propose_changes", {"summary": "x", "actions": [action]})]), "No."]
        _ask(client, headers, _conversation(client, headers), "Fes-ho")
        assert provider.results[-1][0][1].startswith("Error:"), action


def test_a_proposal_can_be_discarded(office):
    client, headers, _, provider = office
    reference = upload(client, headers)
    _, proposal = _propose(
        client, headers, provider,
        [{"method": "DELETE", "path": f"/documents/records/{reference}"}],
    )
    assert proposal["actions"][0]["before"]["num_factura"] == "F-2026/001"
    discarded = client.post(f"{ASSISTANT}/proposals/{proposal['id']}/discard", headers=headers).json()
    assert discarded["status"] == "discarded"
    assert client.get(f"{RECORDS}/{reference}", headers=headers).status_code == 200


# ── The OpenAI side, without the network ────────────────────────────────────


class _Item:
    def __init__(self, **values):
        self.values = values

    def model_dump(self, exclude_none: bool = False):
        return {k: v for k, v in self.values.items() if not (exclude_none and v is None)}


class _Responses:
    def __init__(self, turns):
        self.turns = turns
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs):
        # A snapshot: the session keeps growing the same list afterwards.
        self.calls.append({**kwargs, "input": list(kwargs["input"])})
        return iter(self.turns.pop(0))


def _event(kind: str, **values):
    return type("Event", (), {"type": kind, **values})()


def test_the_openai_session_carries_reasoning_calls_and_results_statelessly():
    from types import SimpleNamespace

    from cosecre_hub.config import Settings
    from cosecre_hub.services.llm import Message, OpenAIProvider, ToolSpec

    reasoning = _Item(type="reasoning", id="rs_1", summary=[], encrypted_content="opaque")
    call = _Item(type="function_call", call_id="c1", name="run_sql", arguments='{"sql": "SELECT 1"}', id="fc_1")
    done = _Item(type="message", role="assistant", content=[{"type": "output_text", "text": "Fet"}])
    responses = _Responses([
        [_event("response.completed", response=SimpleNamespace(output=[reasoning, call], output_text="", usage=None))],
        [
            _event("response.output_text.delta", delta="Fe"),
            _event("response.output_text.delta", delta="t"),
            _event("response.completed", response=SimpleNamespace(output=[done], output_text="Fet", usage=None)),
        ],
    ])
    provider = OpenAIProvider(Settings(_env_file=None, openai_api_key="sk-test"))
    provider._client = SimpleNamespace(responses=responses)

    session = provider.start_tools(
        ToolTurnRequest(
            messages=[Message(role="user", content="Quants?")],
            tools=[ToolSpec(name="run_sql", description="SQL", parameters={"type": "object"})],
            model="gpt-6.1-sol",
            reasoning_effort="medium",
        )
    )
    first = list(session.step())
    assert first[-1].tool_calls == [ToolCall(call_id="c1", name="run_sql", arguments='{"sql": "SELECT 1"}')]
    session.add_results([("c1", '{"rows": [[1]]}')])
    second = list(session.step())
    assert [e.text for e in second if e.type == "delta"] == ["Fe", "t"]
    assert second[-1].text == "Fet" and second[-1].tool_calls == []

    sent = responses.calls[1]
    assert sent["model"] == "gpt-6.1-sol" and sent["reasoning"] == {"effort": "medium"}
    assert sent["store"] is False and sent["include"] == ["reasoning.encrypted_content"]
    assert sent["tools"][0]["name"] == "run_sql" and sent["tools"][0]["type"] == "function"
    assert [item.get("type", "message") for item in sent["input"]] == [
        "message", "reasoning", "function_call", "function_call_output",
    ]
    assert sent["input"][1]["encrypted_content"] == "opaque"
    assert sent["input"][3] == {"type": "function_call_output", "call_id": "c1", "output": '{"rows": [[1]]}'}
