"""Changes the Assistent proposes, and applying them once a person says yes.

The model has no write tool. What it has is ``propose_changes``: a list of API
calls, which this module checks against the bridge's rules, previews — for an
edit, it reads the record first and keeps the values the edit would replace —
and stores as an :class:`~cosecre_hub.models.AssistantProposal`. Nothing
changes until the person presses *Aplica*.

Applying then:

1. reads every edited record again and refuses the whole proposal, changing
   nothing, if any value it would overwrite has moved since the preview;
2. replays the calls one by one, as the person, through the ordinary routes —
   so validation, the sheet and Drive behave exactly as they do by hand;
3. does all of it inside one history action, so a single *Desfés* reverts it.

It stops at the first call that fails; what went through before stays (and
undoes with the rest).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from ...models import AssistantProposal, User
from .. import history
from .bridge import Bridge, BridgeRefused

MAX_ACTIONS = 200

#: Fields worth showing for a record that is about to be deleted.
_IDENTIFYING = (
    "num_doc_intern", "internal_doc_number", "num_factura", "proveidor", "data_factura", "import",
    "codi", "concepte", "data", "import_value", "title", "file_name", "status",
)


class ProposalInvalid(ValueError):
    pass


def _label(action: dict[str, Any]) -> str:
    return str(action.get("label") or action.get("description") or "").strip()[:300]


def preview(bridge: Bridge, raw_actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Check and preview every call. Raises :class:`ProposalInvalid` for the first bad one."""
    if not isinstance(raw_actions, list) or not raw_actions:
        raise ProposalInvalid("Una proposta necessita almenys una acció.")
    if len(raw_actions) > MAX_ACTIONS:
        raise ProposalInvalid(f"Com a molt {MAX_ACTIONS} accions per proposta; divideix-la.")
    actions: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_actions, start=1):
        if not isinstance(raw, dict):
            raise ProposalInvalid(f"L'acció {index} no és un objecte.")
        try:
            resolved = bridge.resolve(str(raw.get("method", "")), str(raw.get("path", "")))
            bridge.check_write(resolved)
        except BridgeRefused as exc:
            raise ProposalInvalid(f"Acció {index}: {exc}") from exc
        body = raw.get("body")
        if body is not None and not isinstance(body, (dict, list)):
            raise ProposalInvalid(f"Acció {index}: el cos ha de ser un objecte JSON.")
        action: dict[str, Any] = {
            "method": resolved.method,
            "path": resolved.path,
            "template": resolved.template,
            "body": body,
            "label": _label(raw),
            "before": None,
            "changes": [],
        }
        if resolved.method in {"PATCH", "PUT", "DELETE"} and bridge.has_route("GET", resolved.path):
            current = bridge.call("GET", resolved.path)
            if not current.ok:
                raise ProposalInvalid(
                    f"Acció {index}: no s'ha pogut llegir {resolved.path} ({current.detail() or current.status_code})."
                )
            if isinstance(current.data, dict):
                action["before"] = _compact(current.data, body if isinstance(body, dict) else None)
                if resolved.method != "DELETE" and isinstance(body, dict):
                    action["changes"] = [
                        {"field": name, "before": current.data.get(name), "after": value}
                        for name, value in body.items()
                    ]
        actions.append(action)
    return actions


def _compact(record: dict[str, Any], body: dict[str, Any] | None) -> dict[str, Any]:
    """The part of a record the preview and the staleness check need."""
    keep = set(_IDENTIFYING) | set(body or {})
    return {name: value for name, value in record.items() if name in keep and not isinstance(value, (dict, list))}


def create(
    session: Session, bridge: Bridge, conversation_id: int, summary: str, raw_actions: list[dict[str, Any]]
) -> AssistantProposal:
    actions = preview(bridge, raw_actions)
    proposal = AssistantProposal(
        conversation_id=conversation_id,
        summary=(summary or "").strip()[:1000] or "Canvis proposats per l'assistent",
        actions=actions,
    )
    session.add(proposal)
    session.commit()
    return proposal


def _same(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)) and not isinstance(left, bool):
        return abs(float(left) - float(right)) < 1e-9
    return left == right


async def apply(session: Session, bridge: Bridge, proposal: AssistantProposal, user: User) -> AssistantProposal:
    if proposal.status != "pending":
        raise ProposalInvalid("Aquesta proposta ja s'ha decidit.")
    # The routes write with their own sessions; this one must not hold SQLite's lock.
    session.commit()

    # 1. Nothing it would overwrite may have moved since the preview.
    for index, action in enumerate(proposal.actions, start=1):
        before = action.get("before")
        if not before:
            continue
        current = await bridge.acall("GET", action["path"])
        if not current.ok or not isinstance(current.data, dict):
            return _decide(session, proposal, "stale", [], f"Acció {index}: el registre ja no hi és.")
        watched = [c["field"] for c in action.get("changes", [])] or list(before)
        moved = [name for name in watched if name in before and not _same(current.data.get(name), before[name])]
        if moved:
            return _decide(
                session,
                proposal,
                "stale",
                [],
                f"Acció {index}: {', '.join(moved)} ha canviat des de la proposta. Demana-la de nou.",
            )

    # 2–3. Replay, as one undoable action.
    results: list[dict[str, Any]] = []
    label = f"Assistent: {proposal.summary}"[:255]
    with history.action(label, kind="person", user_id=user.id) as ctx:
        for action in proposal.actions:
            response = await bridge.acall(action["method"], action["path"], body=action.get("body"))
            results.append(
                {"ok": response.ok, "status_code": response.status_code, "detail": response.detail()[:500]}
            )
            if not response.ok:
                break
        action_id = ctx.id
    proposal.history_action_id = action_id
    done = sum(1 for result in results if result["ok"])
    if done == len(proposal.actions):
        status, detail = "applied", ""
    elif done:
        status, detail = "partial", f"S'han aplicat {done} de {len(proposal.actions)} accions; la següent ha fallat."
    else:
        status, detail = "failed", results[-1]["detail"] if results else "No s'ha aplicat res."
    return _decide(session, proposal, status, results, detail)


def discard(session: Session, proposal: AssistantProposal) -> AssistantProposal:
    if proposal.status != "pending":
        raise ProposalInvalid("Aquesta proposta ja s'ha decidit.")
    return _decide(session, proposal, "discarded", [], "")


def _decide(
    session: Session, proposal: AssistantProposal, status: str, results: list[dict[str, Any]], detail: str
) -> AssistantProposal:
    proposal.status = status
    proposal.results = results
    proposal.detail = detail
    proposal.decided_at = datetime.now(UTC)
    session.commit()
    return proposal


STATUS_TEXT = {
    "pending": "pendent de confirmar",
    "applied": "aplicada",
    "partial": "aplicada en part",
    "failed": "ha fallat",
    "stale": "no aplicada: les dades havien canviat",
    "discarded": "descartada per l'usuari",
}


def describe(proposal: AssistantProposal) -> str:
    """One line the model reads back on later turns."""
    text = f"[Proposta #{proposal.id} «{proposal.summary}» ({len(proposal.actions)} accions): {STATUS_TEXT.get(proposal.status, proposal.status)}"
    if proposal.detail:
        text += f" — {proposal.detail}"
    return text + "]"
