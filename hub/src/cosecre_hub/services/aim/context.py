"""What the tutor remembers about one student.

Rebuilt from the last handful of turns plus the previous profile, never from
the whole transcript — so a refresh costs the same on turn 40 as on turn 4.
"""

from __future__ import annotations

from typing import Any

from ..llm import LLMRegistry, Message, StructuredRequest

STUDENT_CONTEXT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "level": {
            "type": "string",
            "enum": ["inicial", "en_progres", "solid", "avancat"],
        },
        #: Which rung of the exercise's ladder they are on. The monitor compares
        #: this against turn count to notice a student who has stopped moving.
        "current_step": {"type": "integer"},
        "consecutive_failures": {"type": "integer"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "recurring_errors": {"type": "array", "items": {"type": "string"}},
        "misconceptions": {"type": "array", "items": {"type": "string"}},
        "effective_hints": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "next_focus": {"type": "string"},
    },
}

INSTRUCTIONS = """\
Ets qui pren notes sobre com treballa un alumne de matemàtiques, per tal que el
tutor s'hi pugui adaptar el proper cop.

Escriu en català, en tercera persona i sense judicis de valor: descriu què fa
l'alumne, no si és bo o dolent. Les pistes que han funcionat són les que li han
fet avançar de debò, no simplement les que li has dit.

`consecutive_failures` compta els intents seguits en el mateix graó sense
avançar; torna a zero quan avança.
"""

#: Enough to see the shape of the last exchange, few enough that a refresh is
#: O(1) rather than growing with the conversation.
WINDOW = 12


class StudentContextService:
    def __init__(self, registry: LLMRegistry, *, model: str | None = None):
        self._registry = registry
        self._model = model

    def refresh(
        self,
        *,
        transcript: list[tuple[str, str]],
        previous: dict[str, Any] | None,
        exercise_title: str,
    ):
        recent = transcript[-WINDOW:]
        lines = "\n".join(
            f"{'ALUMNE' if role == 'user' else 'TUTOR'}: {content}" for role, content in recent
        )
        prior = (
            f"\n\nNotes anteriors:\n{previous}"
            if previous
            else "\n\nNo hi ha notes anteriors: aquestes són les primeres."
        )

        result = self._registry.get(None).structured(
            StructuredRequest(
                messages=[
                    Message(
                        role="user",
                        content=f"Exercici: {exercise_title}\n\nÚltims torns:\n{lines}{prior}",
                    )
                ],
                schema_name="aim_student_context",
                json_schema=STUDENT_CONTEXT_SCHEMA,
                instructions=INSTRUCTIONS,
                model=self._model,
            )
        )
        return result.data, result.usage
