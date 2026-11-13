"""The reference of a figure request, read from the code that validates it.

Each table comes from an object of the new figure path and nothing is typed here
about its content:

- the fields of a figure and of a panel: the Pydantic models of ``display/request.py``
  and the closed tables their validators read;
- the frames, engines and other closed values: ``FRAMES``, ``ENGINES``, ``WHEN``,
  ``WIDTHS_MM``, ``FORMATS``, ``ZONES``, ``GROUP_KEYS`` and the theme table;
- the quantities: ``QUANTITY_KINDS``;
- the variables: the four registries of ``results/field_registry.py``;
- the presets: ``display.presets.PRESETS``, and the special figures: ``display.request.SPECIALS``;
- the overlays: ``OVERLAY_FIELDS`` and ``display.overlays.OVERLAYS``.

Usage: python -m tools.docs.figure_requests OUT.json
"""

from __future__ import annotations

import argparse
import collections.abc
import importlib
import inspect
import json
import types
import typing
from pathlib import Path
from typing import Any

from pydantic.fields import FieldInfo


def _first_line(doc: str | None) -> str:
    return (doc or "").strip().split("\n", 1)[0].strip()


def type_text(annotation: Any) -> str:
    """A short, readable spelling of a field annotation."""
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin is typing.Annotated:
        return type_text(args[0])
    if origin in (typing.Union, types.UnionType):
        return " or ".join(type_text(a) for a in args)
    if origin is typing.Literal:
        return " or ".join(repr(a) for a in args)
    if origin is collections.abc.Callable:
        return "function"
    if origin is not None:
        inner = ", ".join(type_text(a) for a in args)
        return f"{getattr(origin, '__name__', str(origin))}[{inner}]"
    if annotation is type(None):
        return "none"
    return getattr(annotation, "__name__", str(annotation))


def _literals(annotation: Any) -> list[str]:
    """Every value of a ``Literal`` found anywhere in an annotation."""
    if typing.get_origin(annotation) is typing.Literal:
        return [str(a) for a in typing.get_args(annotation)]
    found: list[str] = []
    for arg in typing.get_args(annotation):
        found.extend(_literals(arg))
    return found


def _default_text(info: FieldInfo) -> str:
    value = info.get_default(call_default_factory=True)
    if value is None:
        return "unset"
    return json.dumps(value, default=str)


def _accepted(name: str, info: FieldInfo) -> list[str]:
    """The values a field takes, from the table its validator reads, else from its type."""
    from hydromodpy.core.pipeline_steps import STEP_NAMES
    from hydromodpy.core.units.kinds import LAYER_REDUCTIONS
    from hydromodpy.display import request as rq
    from hydromodpy.display.presets import PRESETS

    tables: dict[str, list[str]] = {
        "type": list(rq.FRAMES),
        "by": list(rq.GROUP_KEYS),
        "overlays": list(rq.OVERLAY_FIELDS),
        "layer": [w for w in LAYER_REDUCTIONS if w is not None],
        "station": [rq.ZONE_PREFIX + z for z in rq.ZONES],
        "width": [f"{key} ({mm} mm)" for key, mm in rq.WIDTHS_MM.items()],
        "when": [*(k for k in rq.WHEN if k != rq.AFTER), f"{rq.AFTER}<step>"],
        "engine": list(rq.ENGINES),
        "formats": list(rq.FORMATS),
        "holes": list(rq.PANEL_FIELDS),
        "variable": [rq.BUDGET],
        "preset": list(PRESETS),
    }
    if name == "when":
        tables["when"].append(f"with <step> one of {', '.join(STEP_NAMES)}")
    return tables.get(name) or _literals(info.annotation)


def _field_rows(model: type, skip: set[str]) -> list[dict[str, Any]]:
    rows = []
    for name, info in model.model_fields.items():
        if name in skip:
            continue
        rows.append(
            {
                "name": name,
                "type": type_text(info.annotation),
                "default": _default_text(info),
                "description": info.description or "",
                "accepted": _accepted(name, info),
            }
        )
    return rows


def fields() -> dict[str, list[dict[str, Any]]]:
    """The fields of a figure, of a panel, and the one a panel of a preset adds."""
    from hydromodpy.display.request import FigureRequest, PanelFields, PanelRequest

    panel = set(PanelFields.model_fields)
    return {
        "figure": _field_rows(FigureRequest, panel | {"special"}),
        "panel": _field_rows(PanelFields, set()),
        "preset_panel": _field_rows(PanelRequest, panel),
    }


def frames() -> list[dict[str, Any]]:
    """One row per frame: the shapes it draws, its default overlays and its module."""
    from hydromodpy.display.request import FRAMES

    rows = []
    for name, frame in FRAMES.items():
        doc = ""
        if frame.ready:
            doc = _first_line(importlib.import_module(f"hydromodpy.display.frames.{name}").__doc__)
        rows.append(
            {
                "name": name,
                "ready": frame.ready,
                "shapes": list(frame.shapes),
                "overlays": list(frame.overlays),
                "summary": doc,
            }
        )
    return rows


def vocabularies() -> list[dict[str, Any]]:
    """The closed values that are not frames: engines, when, widths, formats, zones, keys."""
    from hydromodpy.core.pipeline_steps import STEP_NAMES
    from hydromodpy.display import request as rq
    from hydromodpy.display.theme import THEMES

    return [
        {
            "name": "engine",
            "values": [
                {"value": k, "note": ", ".join(e.formats), "ready": e.ready}
                for k, e in rq.ENGINES.items()
            ],
        },
        {
            "name": "when",
            "values": [
                {
                    "value": f"{k}<step>" if k == rq.AFTER else k,
                    "note": ", ".join(STEP_NAMES) if k == rq.AFTER else "",
                    "ready": v,
                }
                for k, v in rq.WHEN.items()
            ],
        },
        {
            "name": "width",
            "values": [
                {"value": k, "note": f"{mm} mm", "ready": True} for k, mm in rq.WIDTHS_MM.items()
            ],
        },
        {
            "name": "formats",
            "values": [{"value": f, "note": "", "ready": True} for f in rq.FORMATS],
        },
        {
            "name": "zone",
            "values": [{"value": rq.ZONE_PREFIX + z, "note": "", "ready": True} for z in rq.ZONES],
        },
        {
            "name": "group key",
            "values": [{"value": k, "note": "", "ready": True} for k in rq.GROUP_KEYS],
        },
        {"name": "theme", "values": [{"value": k, "note": "", "ready": True} for k in THEMES]},
    ]


def quantities() -> list[dict[str, Any]]:
    """One row per quantity kind, with what a figure does with it."""
    from hydromodpy.core.units.kinds import QUANTITY_KINDS, scale_of

    return [
        {
            "name": name,
            "stored_unit": kind.stored_unit,
            "display_unit": kind.display_unit,
            "sign": kind.sign,
            "scale": scale_of(kind),
            "log": kind.log,
            "per_area": kind.per_area,
            "layers": kind.layers or "none",
            "isolines": kind.isolines,
            "cumulates_to": kind.cumulates_to or "",
            "extensive": kind.extensive,
            "drawable": kind.drawable,
        }
        for name, kind in QUANTITY_KINDS.items()
    ]


def natural_frame(shape: str | None, quantity: str) -> str:
    """The frame a variable of this shape takes when a panel names no type."""
    from hydromodpy.core.units.kinds import QUANTITY_KINDS
    from hydromodpy.display.request import FRAMES

    if not QUANTITY_KINDS[quantity].drawable:
        return "never drawn"
    if shape is None:
        return "table"
    return next((key for key, frame in FRAMES.items() if shape in frame.shapes), "none")


def variables() -> list[dict[str, Any]]:
    """The variables a figure can draw, one group per registry."""
    from hydromodpy.results import field_registry as reg
    from hydromodpy.results.storage.parquet_schemas import column_unit

    groups = []
    for title, registry in (
        ("FIELD_REGISTRY", reg.FIELD_REGISTRY),
        ("TIME_SERIES_REGISTRY", reg.TIME_SERIES_REGISTRY),
        ("REBUILT_FIELDS", reg.REBUILT_FIELDS),
    ):
        rows = [
            {
                "name": name,
                "label": d.label,
                "unit": d.units,
                "quantity": d.quantity,
                "shape": d.shape,
                "frame": natural_frame(d.shape, d.quantity),
            }
            for name, d in registry.items()
        ]
        groups.append({"registry": title, "rows": rows})
    columns = []
    for name, d in reg.COLUMN_REGISTRY.items():
        table, _, column = name.partition(".")
        columns.append(
            {
                "name": name,
                "label": d.label,
                "unit": column_unit(table, column),
                "quantity": d.quantity,
                "shape": "",
                "frame": natural_frame(None, d.quantity),
            }
        )
    groups.append({"registry": "COLUMN_REGISTRY", "rows": columns})
    groups.append({"registry": "Trial columns of a session", "rows": _trial_columns()})
    groups.append({"registry": "Budget terms", "rows": _budget_terms()})
    return groups


def _trial_columns() -> list[dict[str, Any]]:
    """The names a panel of a session writes: ``trials.cost``, ``trials.parameter``, ``trials.<name>``."""
    from hydromodpy.display import request as rq

    forms = {
        "cost": "Cost of each completed trial.",
        rq.PARAMETER_TOKEN: "Each searched parameter in turn.",
        "<parameter name>": "Value of one searched parameter.",
    }
    return [
        {"name": f"{rq.TRIALS}.{form}", "label": note, "unit": "", "quantity": "", "frame": ""}
        for form, note in forms.items()
    ]


def _budget_terms() -> list[dict[str, Any]]:
    """The per-cell terms that ``variable = 'budget'`` stands for, as the request model reads them."""
    from hydromodpy.display.request import BUDGET, GROUPS, SERIES
    from hydromodpy.results import field_registry as reg

    return [
        {
            "name": name,
            "label": d.label,
            "unit": d.units,
            "quantity": d.quantity,
            "shape": d.shape,
            "frame": f"{SERIES}, {GROUPS} of {BUDGET}",
        }
        for name, d in reg.FIELD_REGISTRY.items()
        if d.zarr_path.startswith(reg.BUDGET_GROUP) and name not in reg.NOT_AQUIFER_TERMS
    ]


def _written(panel: Any) -> dict[str, str]:
    """The fields a preset panel writes, except its frame and its holes."""
    from hydromodpy.display.request import PANEL_FIELDS

    return {
        key: json.dumps(getattr(panel, key), default=str)
        for key in PANEL_FIELDS
        if key in panel.model_fields_set and key != "type"
    }


def presets() -> list[dict[str, Any]]:
    """The shipped presets made of panels, with the frame each panel resolves to."""
    from hydromodpy.display.presets import PRESETS
    from hydromodpy.display.request import FigureRequest, expand

    rows = []
    for name, request in PRESETS.items():
        if request.special is not None:
            continue
        resolved = expand(FigureRequest(preset=name), PRESETS)
        rows.append(
            {
                "name": name,
                "width": resolved.width,
                "panels": [
                    {
                        "frame": done.type,
                        "written": _written(panel),
                        "holes": list(panel.holes or ()),
                    }
                    for panel, done in zip(request.panels, resolved.panels, strict=True)
                ],
            }
        )
    return rows


def specials() -> list[dict[str, Any]]:
    """The special figures: their row of ``SPECIALS`` and the summary of their module."""
    from hydromodpy.display import special
    from hydromodpy.display.request import SPECIALS

    rows = []
    for name, row in SPECIALS.items():
        module = importlib.import_module(f"{special.__name__}.{name}")
        rows.append(
            {
                "name": name,
                "subject": row.subject,
                "width": row.width or "",
                "keywords": list(row.keywords),
                "reads": [*row.variables, *row.tables],
                "summary": _first_line(module.__doc__),
                "module": module.__name__,
            }
        )
    return rows


def overlays() -> list[dict[str, Any]]:
    """One row per overlay: the registered fields it reads and what its function does."""
    from hydromodpy.display.overlays import OVERLAYS
    from hydromodpy.display.request import FRAMES, OVERLAY_FIELDS

    return [
        {
            "name": name,
            "reads": list(reads),
            "default_in": [key for key, frame in FRAMES.items() if name in frame.overlays],
            "summary": _first_line(inspect.getdoc(OVERLAYS[name])),
        }
        for name, reads in OVERLAY_FIELDS.items()
    ]


def build() -> dict[str, Any]:
    return {
        "fields": fields(),
        "frames": frames(),
        "vocabularies": vocabularies(),
        "quantities": quantities(),
        "variables": variables(),
        "presets": presets(),
        "specials": specials(),
        "overlays": overlays(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out")
    args = ap.parse_args()
    payload = build()
    Path(args.out).write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str))
    print({k: len(v) for k, v in payload.items()})


if __name__ == "__main__":
    main()
