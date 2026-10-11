"""One question to the Assistent, from the person's words to the saved answer.

The model gets the conversation so far, the database's description and the
tools in :mod:`.tools`, and goes round — think, call tools, read what they
returned — until it answers or runs out of rounds. What it says streams out as
it is written; what it shows (tables, charts, proposals) is stored with the
answer as *blocks*, interleaved with its text in the order they happened.

The turn yields frames for the client, one dict each:

* ``{"type": "user", "message": …}`` — the question, as saved;
* ``{"type": "status", "text": …}`` — what it is doing right now;
* ``{"type": "delta", "text": …}`` — answer text as it arrives;
* ``{"type": "block", "block": …}`` — something it showed;
* ``{"type": "done", "message": …}`` or ``{"type": "error", "detail": …, "message": …}``,
  exactly one, last.

The answer is saved however the turn ends — failure, or the client leaving.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ...config import Settings
from ...models import AssistantConversation, AssistantMessage, AssistantProposal, User
from ..llm import LLMError, LLMNotConfigured, LLMProvider, Message, ToolTurnRequest
from . import proposals
from .bridge import Bridge
from .sandbox import schema_text
from .serialize import message_dict, proposal_dict
from .tools import STATUS_TEXT, TOOLS, Toolbox

logger = logging.getLogger(__name__)

#: Earlier messages replayed to the model, newest kept.
HISTORY_MESSAGES = 40
LOCAL_TZ = ZoneInfo("Europe/Madrid")

ROLE_LABEL = {"admin": "secretari/a", "administratiu": "administratiu/va", "professor": "professor/a"}

INSTRUCTIONS = """\
Ets l'Assistent de Cosecre (beta), dins l'aplicació de comptabilitat d'un institut: el registre de \
factures i tiquets, els extractes bancaris, les justificacions de pagaments i les sol·licituds del \
professorat. Parles amb {name} ({role}). Avui és {today} (hora local {now}).

Com treballes:
- Respon en la llengua en què et parlen (català, castellà…), de manera breu i precisa, com un company \
de secretaria que domina les dades. Markdown senzill: llistes, **negreta**, `codi`, taules petites.
- Mai no inventis xifres: tota dada surt d'una eina. Si una consulta no troba res, digues-ho.
- Per a xifres, rànquings i comparacions, `run_sql`. Per ensenyar resultats, `show_table`, \
`show_chart` o `show_metrics` amb el mateix `sql`, en comptes de copiar les dades al text. \
Després comenta en una o dues frases el que és important.
- Imports en euros amb format català (1.234,56 €). Les dates de les dades són 'AAAA-MM-DD'; \
«la setmana passada» és de dilluns a diumenge de la setmana anterior a la d'avui.
- Interpreta «les factures que vaig fer/entrar» com els documents amb `created_by_id = {user_id}`, \
llevat que el context digui una altra cosa.

Canvis a les dades:
- No pots escriure directament. L'única via és `propose_changes`: l'usuari veu cada canvi amb el \
valor d'abans i el de després, i decideix. Mai diguis que alguna cosa s'ha fet si la proposta no \
consta com a aplicada.
- Abans de proposar: troba amb `run_sql` exactament quins registres toca (i quants), mira la ruta \
amb `list_api` si no la coneixes, i proposa una acció per registre. Si la petició és ambigua o \
afecta molts registres d'una manera que podria no ser la desitjada, pregunta abans.
- Per editar un document: PATCH /documents/records/{{internal_doc_number}} amb només els camps que \
canvien (l'import es diu `import`; dates 'AAAA-MM-DD'). Validar: POST \
/documents/records/{{internal_doc_number}}/validate. Esborrar: DELETE de la mateixa ruta.
- Un moviment bancari: PATCH /statements/movements/{{id}}. Justificacions: rutes /reconciliation/….
- Sobre les propostes anteriors, el seu estat actual apareix a la conversa entre claudàtors.

{schema}
"""


def build_instructions(user: User) -> str:
    now = datetime.now(LOCAL_TZ)
    return INSTRUCTIONS.format(
        name=user.display_name or user.email,
        role=ROLE_LABEL.get(user.role, user.role),
        user_id=user.id,
        today=now.strftime("%A %Y-%m-%d"),
        now=now.strftime("%H:%M"),
        schema=schema_text(),
    )


def _replay(message: AssistantMessage, proposals_by_id: dict[int, AssistantProposal]) -> str:
    """An earlier answer as the model reads it back: its text, and what it showed."""
    parts = [message.content.strip()] if message.content.strip() else []
    for block in message.blocks or []:
        kind = block.get("type")
        if kind == "table":
            parts.append(f"[Taula mostrada: «{block.get('title', '')}», {len(block.get('rows', []))} files]")
        elif kind == "chart":
            parts.append(f"[Gràfic mostrat: «{block.get('title', '')}»]")
        elif kind == "proposal":
            proposal = proposals_by_id.get(block.get("proposal_id"))
            if proposal is not None:
                parts.append(proposals.describe(proposal))
    if message.status == "error":
        parts.append("[La resposta es va interrompre per un error.]")
    return "\n".join(parts) or "(sense text)"


def history_messages(conversation: AssistantConversation) -> list[Message]:
    by_id = {proposal.id: proposal for proposal in conversation.proposals}
    messages: list[Message] = []
    for message in conversation.messages[-HISTORY_MESSAGES:]:
        if message.role == "user":
            messages.append(Message(role="user", content=message.content))
        else:
            messages.append(Message(role="assistant", content=_replay(message, by_id)))
    return messages


class Turn:
    def __init__(
        self,
        *,
        session: Session,
        settings: Settings,
        provider: LLMProvider,
        bridge: Bridge,
        user: User,
        conversation: AssistantConversation,
    ):
        self.session = session
        self.settings = settings
        self.provider = provider
        self.bridge = bridge
        self.user = user
        self.conversation = conversation

    def run(self, text: str) -> Iterator[dict[str, Any]]:
        conversation = self.conversation
        question = AssistantMessage(conversation_id=conversation.id, role="user", content=text)
        conversation.messages.append(question)
        if not conversation.title:
            conversation.title = _title(text)
        conversation.updated_at = datetime.now(UTC)
        self.session.commit()
        yield {"type": "user", "message": message_dict(self.session, question)}

        answer = AssistantMessage(
            conversation_id=conversation.id,
            role="assistant",
            content="",
            blocks=[],
            model=self.settings.assistant_model,
        )
        blocks: list[dict[str, Any]] = []
        texts: list[str] = []
        usage = {"input_tokens": 0, "output_tokens": 0}
        toolbox = Toolbox(self.session, self.bridge, conversation.id)
        finished = False
        try:
            request = ToolTurnRequest(
                messages=history_messages(conversation),
                tools=TOOLS,
                instructions=build_instructions(self.user),
                model=self.settings.assistant_model or None,
                reasoning_effort=self.settings.assistant_reasoning_effort,
            )
            # Nothing may stay open on SQLite while the model thinks: a read
            # transaction would block every other request's writes.
            self.session.commit()
            session = self.provider.start_tools(request)
            for _round in range(self.settings.assistant_max_rounds):
                yield {"type": "status", "text": "Pensant…"}
                calls = []
                current: dict[str, Any] | None = None
                for event in session.step():
                    if event.type == "delta":
                        if current is None:
                            current = {"type": "text", "text": ""}
                            blocks.append(current)
                        current["text"] += event.text
                        yield {"type": "delta", "text": event.text}
                        continue
                    calls = event.tool_calls
                    if event.model:
                        answer.model = event.model
                    usage["input_tokens"] += event.usage.input_tokens or 0
                    usage["output_tokens"] += event.usage.output_tokens or 0
                    # A provider that answers without streaming still gets its text shown.
                    if event.text and current is None:
                        current = {"type": "text", "text": event.text}
                        blocks.append(current)
                        yield {"type": "delta", "text": event.text}
                if current is not None and current["text"].strip():
                    texts.append(current["text"].strip())
                if not calls:
                    finished = True
                    break
                results = []
                for call in calls:
                    yield {"type": "status", "text": STATUS_TEXT.get(call.name, "Treballant…")}
                    outcome = toolbox.run(call.name, call.arguments)
                    results.append((call.call_id, outcome.output))
                    for block in outcome.blocks:
                        blocks.append(block)
                        yield {"type": "block", "block": self._expand(block)}
                session.add_results(results)
                self.session.commit()
            if not finished:
                answer.status = "error"
                answer.detail = "L'assistent ha fet massa passos sense arribar a una resposta. Prova de concretar la pregunta."
        except LLMNotConfigured:
            answer.status, answer.detail = "error", "El hub no té cap clau d'OpenAI configurada."
        except LLMError as exc:
            answer.status, answer.detail = "error", f"El model ha fallat: {exc}"
        except Exception as exc:  # noqa: BLE001 — the answer is saved whatever happened
            logger.exception("Assistant turn failed")
            answer.status, answer.detail = "error", f"Error inesperat: {exc.__class__.__name__}"
        finally:
            toolbox.close()
            # Saved even when the client has gone: it is in the chat next time.
            self.session.rollback()
            answer.content = "\n\n".join(texts)
            answer.blocks = blocks
            answer.usage = usage
            conversation.messages.append(answer)
            conversation.updated_at = datetime.now(UTC)
            self.session.commit()

        message = message_dict(self.session, answer)
        if answer.status == "error":
            yield {"type": "error", "detail": answer.detail, "message": message}
        else:
            yield {"type": "done", "message": message}

    def _expand(self, block: dict[str, Any]) -> dict[str, Any]:
        if block.get("type") != "proposal":
            return block
        proposal = self.session.get(AssistantProposal, block.get("proposal_id"))
        return {**block, "proposal": proposal_dict(proposal) if proposal else None}


def _title(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= 60 else f"{line[:57].rstrip()}…"
