"""What differs between two models, and when the runner asks a backend to rerun.

``changed_properties`` compares the members of two ``Model`` objects by the
objects they hold. A model made by ``with_properties`` gets new read-only
mappings over the same values, so it must differ only by the properties it set,
and a model made by ``with_profiles`` only by the profiles it replaced.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pytest

from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.initial.state import HeadRule
from hydromodpy.model.model import ModelTime, Properties
from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.solver.base.rerun import changed_properties, chooses_rerun
from tests._helpers.model_factory import make_model, small_geometry, time_grid

BASE = make_model(
    properties=Properties(profiles={"K": object(), "Sy": object()}),
    boundaries=BoundaryConditionBundle(
        conditions={"west_side": object()}, active_ids=("west_side",)
    ),
    wells={"w1": object()},
    lakes={"lac": {"bedleak": 0.1}},
)
CELLS = BASE.geometry.cells.n_cells


def _k(factor: float) -> np.ndarray:
    return np.full(CELLS, 1e-5 * factor)


CHANGES: tuple[tuple[str, Any, Any, frozenset[str] | None], ...] = (
    ("the same model", BASE, BASE, frozenset()),
    ("K set", BASE, BASE.with_properties(K=_k(2.0)), frozenset({"K"})),
    ("Sy set", BASE, BASE.with_properties(Sy=0.1), frozenset({"Sy"})),
    ("K and Sy set", BASE, BASE.with_properties(K=_k(2.0), Sy=0.1), frozenset({"K", "Sy"})),
    (
        "K changed",
        BASE.with_properties(K=_k(2.0)),
        BASE.with_properties(K=_k(3.0)),
        frozenset({"K"}),
    ),
    (
        "K set again to equal values",
        BASE.with_properties(K=_k(2.0)),
        BASE.with_properties(K=_k(2.0)),
        frozenset(),
    ),
    (
        "K left on one side",
        BASE.with_properties(K=_k(2.0), Sy=0.1),
        BASE.with_properties(Sy=0.1),
        frozenset({"K"}),
    ),
    ("another geometry", BASE, replace(BASE, geometry=small_geometry()), None),
    (
        "another time grid",
        BASE,
        replace(
            BASE, time=ModelTime(grid=time_grid(10.0), regime="steady", first_period_steady=True)
        ),
        None,
    ),
    ("another start", BASE, BASE.with_initial(HeadRule("top")), None),
    (
        "every profile replaced",
        BASE,
        replace(BASE, properties=Properties(profiles={"K": object(), "Sy": object()})),
        frozenset({"K", "Sy"}),
    ),
    ("the K profile replaced", BASE, BASE.with_profiles({"K": object()}), frozenset({"K"})),
    (
        "the K profile replaced and Sy set",
        BASE,
        BASE.with_profiles({"K": object()}).with_properties(Sy=0.1),
        frozenset({"K", "Sy"}),
    ),
    (
        "a profile more",
        BASE,
        replace(
            BASE,
            properties=Properties(profiles={**BASE.properties.profiles, "Ss": object()}),
        ),
        None,
    ),
    (
        "another boundary condition",
        BASE,
        replace(
            BASE,
            boundaries=BoundaryConditionBundle(
                conditions={"west_side": object()}, active_ids=("west_side",)
            ),
        ),
        None,
    ),
    ("another well", BASE, replace(BASE, wells={"w1": object()}), None),
    ("a lake fewer", BASE, replace(BASE, lakes={}), None),
    (
        "a tuple rebuilt with the same names",
        replace(BASE, active_sinks_sources=tuple(["drain"])),
        replace(BASE, active_sinks_sources=tuple(["drain"])),
        frozenset(),
    ),
    (
        "a tuple with another name",
        replace(BASE, active_sinks_sources=tuple(["drain"])),
        replace(BASE, active_sinks_sources=tuple(["river"])),
        None,
    ),
    (
        "a tuple with one name more",
        replace(BASE, active_sinks_sources=tuple(["drain"])),
        replace(BASE, active_sinks_sources=tuple(["drain", "river"])),
        None,
    ),
    ("no previous model", None, BASE, None),
)


@pytest.mark.parametrize(
    ("case", "previous", "model", "expected"), CHANGES, ids=[c for c, *_ in CHANGES]
)
def test_changed_properties(case: str, previous: Any, model: Any, expected: Any) -> None:
    del case
    assert changed_properties(previous, model) == expected


class _Rerunning:
    mutable: ClassVar[frozenset[str]] = frozenset({"K", "Sy"})

    def rerun(self, previous: SolverRun, model: Any, slot: RunSlot) -> SolverRun | None:
        return None


class _Fixed:
    mutable: ClassVar[frozenset[str]] = frozenset()

    def rerun(self, previous: SolverRun, model: Any, slot: RunSlot) -> SolverRun | None:
        return None


class _MutableWithoutRerun:
    mutable: ClassVar[frozenset[str]] = frozenset({"K"})


def _solved(model: Any) -> SolverRun:
    return SolverRun(slot=RunSlot(Path("scratch"), "run"), model=model, written=True, solved=True)


CHOICES: tuple[tuple[str, object, SolverRun | None, Any, bool], ...] = (
    ("no previous run", _Rerunning(), None, BASE, False),
    ("K within mutable", _Rerunning(), _solved(BASE), BASE.with_properties(K=_k(2.0)), True),
    ("no change", _Rerunning(), _solved(BASE), BASE, True),
    (
        "a K profile within mutable",
        _Rerunning(),
        _solved(BASE),
        BASE.with_profiles({"K": object()}),
        True,
    ),
    ("Ss outside mutable", _Rerunning(), _solved(BASE), BASE.with_properties(Ss=1e-5), False),
    (
        "another geometry",
        _Rerunning(),
        _solved(BASE),
        replace(BASE, geometry=small_geometry()),
        False,
    ),
    (
        "a backend that is not mutable",
        _Fixed(),
        _solved(BASE),
        BASE.with_properties(K=_k(2.0)),
        False,
    ),
    (
        "mutable without rerun",
        _MutableWithoutRerun(),
        _solved(BASE),
        BASE.with_properties(K=_k(2.0)),
        False,
    ),
)


@pytest.mark.parametrize(
    ("case", "adapter", "previous", "model", "expected"), CHOICES, ids=[c for c, *_ in CHOICES]
)
def test_chooses_rerun(
    case: str, adapter: object, previous: SolverRun | None, model: Any, expected: bool
) -> None:
    del case
    assert chooses_rerun(adapter, previous, model) is expected
