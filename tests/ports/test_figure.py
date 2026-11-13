"""The figure port, played on every figure the registry serves.

The contract is the one the batch renderer relies on: when
``unavailable_reason(subject)`` says nothing, ``plot(subject)`` draws, or
raises ``FigureNotApplicable`` with a sentence, which the renderer turns into
a skipped figure with that reason. Any other exception is a defect, because a
run that asks ``on_error = "raise"`` stops on it.

The subjects are the frozen example of a pre-release, copied out of the tree: the
runs ``demo`` and ``calage``, the session ``calage`` and the ``RunSet`` of the
project. Each figure meets each subject once. A figure the example cannot draw
is named with its reasons, never dropped. Figures of transport and of lakes
find no such run in the example, so they are counted refused here and drawn
by none of these subjects.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from hydromodpy.display.figure_registry import figures
from hydromodpy.display.figure_registry import get as figure
from hydromodpy.display.subject import FigureNotApplicable

from ._installed_probe import REPO_ROOT

EXAMPLE = (
    REPO_ROOT
    / "tests"
    / "regression"
    / "frozen_runs"
    / "v2.0.0"
    / "current"
    / "projects"
    / "example"
)

DRAWN_FLOOR = 21
"""Distinct figures the example draws, measured at 21 on 72 figures, in about 4 s."""

FIGURE_NAMES = tuple(figures.names())


@dataclass(frozen=True)
class Outcome:
    """What one figure did with one subject: ``drawn``, ``refused`` or ``defect``."""

    subject: str
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


@pytest.fixture(scope="module")
def outcomes(subjects: dict[str, Any]) -> dict[str, list[Outcome]]:
    """Each figure played on each subject, once for the file."""
    import matplotlib.pyplot as plt

    played: dict[str, list[Outcome]] = {}
    for name in FIGURE_NAMES:
        fig = figure(name)
        rows = played.setdefault(name, [])
        for label, subject in subjects.items():
            reason = fig.unavailable_reason(subject)
            if reason is not None:
                rows.append(Outcome(label, "refused", reason))
                continue
            try:
                drawn = fig.plot(subject, dpi=40)
            except FigureNotApplicable as exc:
                rows.append(Outcome(label, "refused", str(exc)))
            except Exception as exc:
                rows.append(Outcome(label, "defect", f"{type(exc).__name__}: {exc}"))
            else:
                plt.close(drawn)
                rows.append(Outcome(label, "drawn"))
            finally:
                plt.close("all")
    return played


def test_the_cases_are_the_figures_of_the_registry() -> None:
    assert sorted(FIGURE_NAMES) == sorted(figures.names())


@pytest.mark.parametrize("name", FIGURE_NAMES)
def test_an_accepted_subject_is_drawn_or_refused_with_a_sentence(
    name: str, outcomes: dict[str, list[Outcome]]
) -> None:
    rows = outcomes[name]
    defects = [row for row in rows if row.kind == "defect"]

    assert len(rows) == 4
    assert defects == []
    assert all(row.detail.strip() for row in rows if row.kind == "refused")


def test_the_example_draws_its_floor_and_names_what_it_refuses(
    outcomes: dict[str, list[Outcome]],
) -> None:
    """Every figure is drawn at least once, or refused on every subject with its reasons."""
    drawn = sorted(name for name, rows in outcomes.items() if any(r.kind == "drawn" for r in rows))
    never = {
        name: sorted({row.detail for row in rows})
        for name, rows in outcomes.items()
        if name not in drawn
    }

    assert len(drawn) >= DRAWN_FLOOR, never
    assert all(row.kind == "refused" and row.detail for name in never for row in outcomes[name]), (
        never
    )
    assert set(drawn) | set(never) == set(FIGURE_NAMES)
