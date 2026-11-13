"""List what can be drawn, draw again the figures of a run found through its project index.

The work behind ``hmp config figures`` and ``hmp show --figure``: list the presets, the
special figures, the frames and the variables of the new path, and mark what a run holds.
Draw again every figure a run recorded, and read ``--opt NAME=VALUE`` items into request
fields.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from hydromodpy.core.state.result_dirs import project_root_at
from hydromodpy.display.presets import PRESETS
from hydromodpy.display.request import (
    BUDGET,
    FRAMES,
    SPECIALS,
    FigureRequest,
    budget_terms,
    natural_frame,
    required_variables,
)
from hydromodpy.results.field_registry import (
    COLUMN_REGISTRY,
    FIELD_REGISTRY,
    REBUILT_FIELDS,
    TIME_SERIES_REGISTRY,
    kind_of,
    label_of,
)

KINDS = ("variable", "preset", "special", "frame")
"""The kinds of row ``figure_listing`` gives."""
HELD, ABSENT, CHECKED_LATER = "held", "not in this run", "checked when drawn"


def regen_figures(sim_ref: str, *, workspace: Any = None) -> list[Path]:
    """Draw again every figure the ledger of a run records; return the files written.

    The index is opened read-only: the figures are files of the run directory.
    """
    from hydromodpy.display.runs import log_render_summary
    from hydromodpy.display.runs import regen_figures as regen_run_figures
    from hydromodpy.results.catalog.facade import Catalog

    workspace_root = project_root_at(workspace)
    with Catalog(workspace_root) as catalog:
        sid = catalog.resolve(sim_ref)
        run_dir = catalog.run_dir_for(sid)
        report = regen_run_figures(catalog[sid], run_dir)
    log_render_summary(report, destination=run_dir)
    return list(report.written)


def parse_request_fields(items: Sequence[str]) -> dict[str, Any]:
    """Read ``NAME=VALUE`` items into the fields of a figure request.

    A value is a TOML value (``12``, ``[8, 4]``, ``"text"``, ``false``), else the
    bare text. The request model checks the names and the types when it is built.
    """
    import tomllib

    fields: dict[str, Any] = {}
    for item in items:
        name, sep, raw = str(item).partition("=")
        name = name.strip()
        if not sep or not name:
            raise ValueError(f"--opt {item!r}: write NAME=VALUE, as in --opt station=lake:1.")
        try:
            fields[name] = tomllib.loads(f"value = {raw}")["value"]
        except tomllib.TOMLDecodeError:
            fields[name] = raw
    return fields


def figure_listing(
    sim_ref: str | None = None,
    *,
    workspace: Any = None,
    presets_of: Callable[[Any], Mapping[str, FigureRequest]] | None = None,
) -> list[dict[str, str]]:
    """Return one row per thing a figure can be asked by: variables, presets, specials, frames.

    A row has ``name``, ``kind``, ``frame`` (the subject of a special), ``label``,
    ``unit``, ``detail`` and ``status``. Every row comes from the tables of the request
    path, so a new variable, preset or frame shows up without a line here. With
    ``sim_ref`` the status says what the run holds: ``held`` or ``not in this run`` for a
    variable, ``held`` or ``missing: a, b`` for a preset, and ``checked when drawn`` for
    a special and a table column, which declare no need. Without it the status is empty.
    ``presets_of`` maps the run to the presets it can draw, else the shipped ones count.
    The index is opened read-only.
    """
    if sim_ref is None:
        return _rows(None, PRESETS)
    from hydromodpy.results.catalog.facade import Catalog

    with Catalog(project_root_at(workspace)) as catalog:
        run = catalog[catalog.resolve(sim_ref)]
        return _rows(run, PRESETS if presets_of is None else presets_of(run))


def _rows(run: Any, presets: Mapping[str, FigureRequest]) -> list[dict[str, str]]:
    rows = [_preset_row(run, name, presets) for name in sorted(presets) if name not in SPECIALS]
    rows += [_special_row(run, name) for name in sorted(SPECIALS)]
    rows += [_frame_row(name) for name, frame in FRAMES.items() if frame.ready]
    rows += [_variable_row(run, name) for name in _variables()]
    rows += [_column_row(run, name) for name in COLUMN_REGISTRY]
    return rows


def _row(name: str, kind: str, frame: str, **more: str) -> dict[str, str]:
    row = {"name": name, "kind": kind, "frame": frame, "label": "", "unit": "", "detail": ""}
    return {**row, "status": "", **more}


def _variables() -> list[str]:
    """The registered names that have a natural frame, so a bare name draws them."""
    names = [*FIELD_REGISTRY, *REBUILT_FIELDS, *TIME_SERIES_REGISTRY, BUDGET]
    drawn = []
    for name in dict.fromkeys(names):
        if name != BUDGET and not kind_of(name).drawable:
            continue
        try:
            natural_frame([name])
        except ValueError:
            continue  # a shape no frame takes is not asked for by name
        drawn.append(name)
    return drawn


def _variable_row(run: Any, name: str) -> dict[str, str]:
    frame = natural_frame([name])
    if name == BUDGET:
        return _row(name, "variable", frame, detail="one panel per budget term the run kept")
    unit = kind_of(name).display_unit
    status = "" if run is None else (HELD if _holds(run, name) else ABSENT)
    return _row(name, "variable", frame, label=label_of(name), unit=unit, status=status)


def _holds(run: Any, name: str) -> bool:
    if name == BUDGET:  # a budget figure draws the terms the run kept
        return any(run.has_field(term) for term in budget_terms())
    if name in TIME_SERIES_REGISTRY:
        return bool(run.stations(name))
    return bool(run.has_field(name))


def _column_row(run: Any, name: str) -> dict[str, str]:
    status = "" if run is None else CHECKED_LATER
    return _row(name, "variable", "table", label=label_of(name), status=status)


def _preset_row(run: Any, name: str, presets: Mapping[str, FigureRequest]) -> dict[str, str]:
    request = presets[name]
    panels = request.panels or ()
    frames = list(
        dict.fromkeys(panel.type or natural_frame(list(panel.variable or ())) for panel in panels)
    )
    holes = list(dict.fromkeys(hole for panel in panels for hole in panel.holes or ()))
    detail = "holes: " + ", ".join(holes) if holes else "no hole"
    status = ""
    if run is not None:
        needs = required_variables(request, presets, terms=False)
        missing = [need for need in needs if not _holds(run, need)]
        status = "missing: " + ", ".join(missing) if missing else HELD
    return _row(name, "preset", ", ".join(frames), detail=detail, status=status)


def _special_row(run: Any, name: str) -> dict[str, str]:
    row = SPECIALS[name]
    reads = [*row.variables, *row.tables]
    parts = ["holes: " + ", ".join(row.keywords)] if row.keywords else []
    parts += ["reads: " + ", ".join(reads)] if reads else []
    status = "" if run is None else CHECKED_LATER
    return _row(name, "special", row.subject, detail="; ".join(parts), status=status)


def _frame_row(name: str) -> dict[str, str]:
    fields = importlib.import_module(f"hydromodpy.display.frames.{name}").FIELDS
    return _row(name, "frame", "", detail=", ".join(fields))
