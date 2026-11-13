"""The figure port, played on every name the request path serves.

The contract is the one the batch renderer relies on: a request expands and renders, or is
refused with a sentence (``ValueError`` of ``expand``, ``DisplayError`` or
``FigureNotApplicable`` of ``render``), which the renderer turns into a skipped figure with
that reason. Any other exception is a defect, because a run that asks
``on_error = "raise"`` stops on it.

The subjects are the frozen example, copied out of the tree: the runs ``demo`` and
``calage``, the session ``calage`` and the ``RunSet`` of the project. Each name meets each
subject once: every preset and special, every drawable variable, the budget, the columns
of the tables and the ``trials.*`` columns of the session. A name the example cannot draw
is named with its reasons, never dropped. Figures of transport and of lakes find no such
run in the example, so they are refused here and drawn by none of these subjects.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any

import pytest

from hydromodpy.core.exceptions import DisplayError
from hydromodpy.display.presets import PRESETS
from hydromodpy.display.render import render
from hydromodpy.display.request import BUDGET, expand, request_of
from hydromodpy.display.theme import get_theme
from hydromodpy.results.field_registry import (
    COLUMN_REGISTRY,
    FIELD_REGISTRY,
    REBUILT_FIELDS,
    TIME_SERIES_REGISTRY,
    kind_of,
)

from ._installed_probe import REPO_ROOT

EXAMPLE = REPO_ROOT / "tests/regression/frozen_runs/v2.0.0/current/projects/example"

DRAWN_FLOOR = 34
"""Distinct names the example draws, measured at 34 on 129 names on 2026-11-13."""

VARIABLES = [
    name
    for name in (*FIELD_REGISTRY, *REBUILT_FIELDS, *TIME_SERIES_REGISTRY)
    if kind_of(name).drawable
]
NAMES = (*PRESETS, *VARIABLES, BUDGET, *COLUMN_REGISTRY)
THEME = replace(get_theme("default"), dpi=40)


@dataclass(frozen=True)
class Outcome:
    """What one name did with one subject: ``drawn``, ``refused`` or ``defect``."""

    kind: str
    detail: str = ""


@pytest.fixture(scope="module")
def subjects(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    """The four subjects of the copied example, opened once for the file."""
    import hydromodpy

    root = tmp_path_factory.mktemp("figure_port") / "example"
    shutil.copytree(EXAMPLE, root)
    project = hydromodpy.open(root)
    with project.store as catalog:
        yield {
            "run_demo": catalog["demo"],
            "run_calage": catalog["calage"],
            "session_calage": project.sessions["calage"],
            "runset": project.runs(),
        }


def _play(name: str, subject: Any) -> Outcome:
    import matplotlib.pyplot as plt

    fields = {"type": "distribution"} if name.startswith("trials.") else {}
    fields = {"type": "table"} if name in COLUMN_REGISTRY else fields
    fields = {"station": "zone:catchment"} if name == BUDGET else fields
    try:
        figure = expand(request_of(name, PRESETS, **fields), PRESETS)
    except ValueError as exc:
        return Outcome("refused", str(exc))
    try:
        drawn = render(figure, subject, theme=THEME)
    except DisplayError as exc:
        return Outcome("refused", str(exc))
    except Exception as exc:
        return Outcome("defect", f"{type(exc).__name__}: {exc}")
    finally:
        plt.close("all")
    plt.close(drawn)
    return Outcome("drawn")


@pytest.fixture(scope="module")
def outcomes(subjects: dict[str, Any]) -> dict[str, dict[str, Outcome]]:
    """Each name played on each subject, once for the file."""
    names = [*NAMES, *(f"trials.{c}" for c in subjects["session_calage"].trials.columns)]
    return {name: {label: _play(name, s) for label, s in subjects.items()} for name in names}


def test_every_name_is_drawn_or_refused_with_a_sentence(
    outcomes: dict[str, dict[str, Outcome]],
) -> None:
    rows = [
        (name, label, row) for name, subject in outcomes.items() for label, row in subject.items()
    ]

    assert len(rows) == 4 * len(outcomes)
    assert [(n, label, r.detail) for n, label, r in rows if r.kind == "defect"] == []
    assert all(r.detail.strip() for _, _, r in rows if r.kind == "refused")


def test_the_example_draws_its_floor_and_names_what_it_refuses(
    outcomes: dict[str, dict[str, Outcome]],
) -> None:
    """Every name is drawn at least once, or refused on every subject with its reasons."""
    drawn = {n for n, rows in outcomes.items() if any(r.kind == "drawn" for r in rows.values())}
    never = {
        n: sorted({r.detail for r in rows.values()})
        for n, rows in outcomes.items()
        if n not in drawn
    }

    assert len(drawn) >= DRAWN_FLOOR, never
    assert all(r.kind == "refused" and r.detail for n in never for r in outcomes[n].values()), never
