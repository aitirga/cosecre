"""Figures as data, never as markup or code.

The provider generates no images and runs no code, so a figure has to be
described rather than drawn. Four options were on the table and only one is
safe *and* cheap here:

- model writes matplotlib and the hub runs it — arbitrary code execution;
- model writes SVG — needs a real sanitiser (``script``, ``foreignObject``,
  ``use href``), which is a security project rather than a feature;
- add a charting library — the frontend has no UI dependencies at all, and one
  would immediately be the largest thing in the bundle;
- **model fills in a closed schema and the client draws it.**

The last one also happens to be the only one a teacher can review and edit: the
spec is visible in the wizard, and changing ``x_max`` from 10 to 5 updates the
preview. An AI-generated raster is neither reviewable nor editable.

The only model-authored "code" that survives is ``expression``, which the client
parses with a shunting-yard parser over a fixed function table — never ``eval``.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field


class FunctionSeries(BaseModel):
    #: In terms of `x`. Parsed, not evaluated — see `plot/expression.ts`.
    expression: str
    label: str


class PlotMarker(BaseModel):
    x: float
    y: float
    label: str


class FunctionPlot(BaseModel):
    kind: Literal["function"]
    title: str
    x_label: str
    y_label: str
    x_min: float
    x_max: float
    grid: bool = True
    series: list[FunctionSeries] = Field(default_factory=list)
    markers: list[PlotMarker] = Field(default_factory=list)


class PointSeries(BaseModel):
    label: str
    mode: Literal["line", "scatter"]
    points: list[tuple[float, float]] = Field(default_factory=list)


class PointsPlot(BaseModel):
    kind: Literal["points"]
    title: str
    x_label: str
    y_label: str
    series: list[PointSeries] = Field(default_factory=list)


class BarSeries(BaseModel):
    label: str
    values: list[float] = Field(default_factory=list)


class BarsPlot(BaseModel):
    kind: Literal["bars"]
    title: str
    x_label: str
    y_label: str
    categories: list[str] = Field(default_factory=list)
    series: list[BarSeries] = Field(default_factory=list)


class GeometryShape(BaseModel):
    type: Literal["segment", "circle", "polygon", "label"]
    #: Flat `[x1, y1, x2, y2, …]`. One list for every shape keeps the schema
    #: strict-mode friendly, which nested per-shape objects would not be.
    coords: list[float] = Field(default_factory=list)
    label: str = ""


class GeometryPlot(BaseModel):
    kind: Literal["geometry"]
    title: str
    shapes: list[GeometryShape] = Field(default_factory=list)


AimPlotSpec = Annotated[
    Union[FunctionPlot, PointsPlot, BarsPlot, GeometryPlot],
    Field(discriminator="kind"),
]


def _nullable_array(items: dict[str, Any]) -> dict[str, Any]:
    """An array that strict mode will accept as "may be empty or absent".

    Strict structured output makes every property required, so optionality has
    to be expressed as nullability instead of omission.
    """
    return {"anyOf": [{"type": "array", "items": items}, {"type": "null"}]}


#: Written by hand rather than derived from the models: `model_json_schema()`
#: emits `$ref`/`$defs` for every nested model, and strict mode plus a
#: discriminated union makes that a fight not worth having for one schema.
PLOT_SPEC_SCHEMA: dict[str, Any] = {
    "anyOf": [
        {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["function"]},
                "title": {"type": "string"},
                "x_label": {"type": "string"},
                "y_label": {"type": "string"},
                "x_min": {"type": "number"},
                "x_max": {"type": "number"},
                "grid": {"type": "boolean"},
                "series": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "expression": {"type": "string"},
                            "label": {"type": "string"},
                        },
                    },
                },
                "markers": _nullable_array(
                    {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                            "label": {"type": "string"},
                        },
                    }
                ),
            },
        },
        {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["points"]},
                "title": {"type": "string"},
                "x_label": {"type": "string"},
                "y_label": {"type": "string"},
                "series": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "mode": {"type": "string", "enum": ["line", "scatter"]},
                            "points": {
                                "type": "array",
                                "items": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                },
                            },
                        },
                    },
                },
            },
        },
        {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["bars"]},
                "title": {"type": "string"},
                "x_label": {"type": "string"},
                "y_label": {"type": "string"},
                "categories": {"type": "array", "items": {"type": "string"}},
                "series": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "values": {"type": "array", "items": {"type": "number"}},
                        },
                    },
                },
            },
        },
        {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["geometry"]},
                "title": {"type": "string"},
                "shapes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["segment", "circle", "polygon", "label"],
                            },
                            "coords": {"type": "array", "items": {"type": "number"}},
                            "label": {"type": "string"},
                        },
                    },
                },
            },
        },
    ]
}
