"""Turning what a teacher typed into an exercise the tutor can run.

The prompt and the schema live here rather than in the browser, following
``services/extraction.py``: a client that supplies its own schema can drift from
what the server stores, and the teacher never needed to see either.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..llm import LLMError, LLMRegistry, Message, StructuredRequest
from .plots import PLOT_SPEC_SCHEMA, AimPlotSpec

INSTRUCTIONS = """\
Ets un dissenyador d'exercicis de matemàtiques per a un institut català.
Rebràs les notes en brut d'un professor i les has de convertir en un exercici
ben format, en català.

Regles:
- Conserva la intenció del professor. No canviïs el problema ni els números.
- El plantejament ha de ser autònom: qui el llegeixi ha de saber què fer.
- L'escala de dificultat va del pas més senzill al més exigent. Cada graó ha de
  ser una passa que l'alumne pugui fer sol, amb una pista que no reveli la
  solució.
- Els entrebancs són errors concrets que has vist en alumnes reals: cadascun
  amb el senyal que el delata i la pregunta que el desencalla.
- Fes servir LaTeX entre signes de dòlar per a qualsevol expressió matemàtica.
- No resolguis mai l'exercici.
"""

REFINED_EXERCISE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "statement_md": {"type": "string"},
        "difficulty_ladder": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step": {"type": "integer"},
                    "label": {"type": "string"},
                    "prompt": {"type": "string"},
                    "escalation": {"type": "string"},
                },
            },
        },
        "anticipated_issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue": {"type": "string"},
                    "signal": {"type": "string"},
                    "hint": {"type": "string"},
                },
            },
        },
        "suggested_topics": {"type": "array", "items": {"type": "string"}},
        "suggested_level": {"type": "string"},
        "plot_requests": {"type": "array", "items": {"type": "string"}},
    },
}


class DifficultyStep(BaseModel):
    step: int
    label: str
    prompt: str
    escalation: str


class AnticipatedIssue(BaseModel):
    issue: str
    signal: str
    hint: str


class RefinedExercise(BaseModel):
    """The validated result. Nothing reaches the database without passing here.

    A malformed generation becomes "torna-ho a provar" rather than a broken
    exercise in front of a class.
    """

    title: str
    statement_md: str
    difficulty_ladder: list[DifficultyStep] = Field(default_factory=list)
    anticipated_issues: list[AnticipatedIssue] = Field(default_factory=list)
    suggested_topics: list[str] = Field(default_factory=list)
    suggested_level: str = ""
    plot_requests: list[str] = Field(default_factory=list)


class GeneratedPlots(BaseModel):
    plots: list[AimPlotSpec] = Field(default_factory=list)


class ExerciseAuthoringService:
    """The wizard's model calls."""

    def __init__(self, registry: LLMRegistry, *, model: str | None = None):
        self._registry = registry
        self._model = model

    def refine(self, raw_blocks: dict[str, Any], *, focus: str | None = None):
        prompt = _describe_blocks(raw_blocks)
        if focus:
            prompt += f"\n\nEl professor demana especialment: {focus}"

        result = self._registry.get(None).structured(
            StructuredRequest(
                messages=[Message(role="user", content=prompt)],
                schema_name="refined_exercise",
                json_schema=REFINED_EXERCISE_SCHEMA,
                instructions=INSTRUCTIONS,
                model=self._model,
            )
        )
        try:
            refined = RefinedExercise.model_validate(result.data)
        except ValidationError as exc:
            raise LLMError("El model ha retornat un exercici incomplet.") from exc
        return refined, result.usage

    def plots(self, context: str, requests: list[str]):
        """Ask for figures as declarative specs.

        The model never emits markup or code — it fills in a closed schema that
        the client renders as SVG. See ``services/aim/plots.py`` for why.
        """
        wanted = "\n".join(f"- {item}" for item in requests) or "- una figura útil"
        result = self._registry.get(None).structured(
            StructuredRequest(
                messages=[
                    Message(
                        role="user",
                        content=(
                            f"Exercici:\n{context}\n\nGràfics demanats:\n{wanted}\n\n"
                            "Genera l'especificació de cada gràfic."
                        ),
                    )
                ],
                schema_name="aim_plots",
                json_schema={
                    "type": "object",
                    "properties": {"plots": {"type": "array", "items": PLOT_SPEC_SCHEMA}},
                },
                instructions=(
                    "Genera especificacions de gràfics per a un exercici de matemàtiques. "
                    "Les expressions es fan servir amb la variable x i només poden fer servir "
                    "+ - * / ^ ( ) i les funcions sin cos tan sqrt abs exp ln log min max, "
                    "amb les constants pi i e. Escriu les etiquetes en català."
                ),
                model=self._model,
            )
        )
        try:
            generated = GeneratedPlots.model_validate(result.data)
        except ValidationError as exc:
            raise LLMError("El model ha retornat un gràfic que no es pot representar.") from exc
        return generated.plots, result.usage


#: Wizard step → the heading the model sees. Ordered as the teacher fills them.
BLOCK_LABELS: list[tuple[str, str]] = [
    ("title", "Títol"),
    ("statement", "Plantejament"),
    ("difficulty", "Dificultat i com escala"),
    ("issues", "Entrebancs que preveu el professor"),
    ("plots", "Gràfics que caldrien"),
    ("notes", "Notes addicionals"),
]


def _describe_blocks(raw_blocks: dict[str, Any]) -> str:
    parts = [
        f"## {label}\n{str(raw_blocks.get(key) or '').strip()}"
        for key, label in BLOCK_LABELS
        if str(raw_blocks.get(key) or "").strip()
    ]
    return "\n\n".join(parts) or "El professor no ha escrit res encara."
