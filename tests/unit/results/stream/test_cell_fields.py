"""The cell fields a run rebuilds on read hold the values written down here by hand.

The run is the monthly V-valley of ``tests._helpers.transient_network_run``. In
January (step 0) the whole axis flows. In June (step 5) the outlet alone flows. The
mapped network is the axis, and a cell one row up the axis is 100 m of descent away.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.budget.terms import ACTING_PACKAGES, budget_terms_for
from hydromodpy.results.derive.stream_network import cell_fields
from hydromodpy.results.derive.stream_network.cell_fields import REBUILT_FIELD_ROWS, rebuilt_rows
from hydromodpy.results.derive.stream_network.comparison import (
    AGREEMENT_LABELS,
    network_comparison_from_run,
)
from hydromodpy.results.derive.virtual_fields import (
    SIMULATED_ACTIVE_NETWORK,
    package_cells_rows,
    simulated_active_network_stack,
)
from hydromodpy.results.field_registry import FIELD_REGISTRY, REBUILT_FIELDS
from tests._helpers.transient_network_run import HEAD, HILLSLOPE, MIDDLE, OUTLET, transient_run
from tests.unit.display._network_comparison_run import CELL_M, NX, cell

JANUARY, JUNE = 0, 5
AXIS = [OUTLET, MIDDLE, HEAD]
PIT = cell(1, 1)


class Group(dict):
    """A budget group of a store, which carries attributes."""

    attrs: dict = {}


def held_run():
    """Return the transient run, hashable so the memo can hold it."""
    run = transient_run()
    run.__class__ = type("HeldRun", (type(run),), {"__hash__": object.__hash__})
    return run


def at(field: str, step: int, cells: list[int], run=None) -> list[float]:
    return rebuilt_rows(run or transient_run(), field, [step])[0][cells].tolist()


@pytest.mark.parametrize(
    ("field", "step", "cells", "expected"),
    [
        ("simulated_active_network", JANUARY, AXIS + [HILLSLOPE], [1, 1, 1, 0]),
        ("simulated_active_network", JUNE, AXIS, [1, 0, 0]),
        ("network_agreement", JANUARY, AXIS + [HILLSLOPE], [1, 1, 1, 0]),
        ("network_agreement", JUNE, AXIS + [HILLSLOPE], [1, 3, 3, 0]),
        ("downslope_distance", JUNE, [MIDDLE, HEAD], [CELL_M, 2 * CELL_M]),
    ],
)
def test_a_step_holds_the_hand_value(field, step, cells, expected) -> None:
    assert at(field, step, cells) == expected


def test_distance_is_nan_where_no_cell_disagrees() -> None:
    row = rebuilt_rows(transient_run(), "downslope_distance", [JANUARY, JUNE])
    assert np.isnan(row[0]).all()
    assert np.isnan(row[1][[OUTLET, HILLSLOPE]]).all()


def test_a_simulated_only_cell_measures_its_descent_to_the_map() -> None:
    # The hillslope releases in June: its water reaches the axis two columns on.
    run = transient_run()
    run.stack[JUNE, HILLSLOPE] = 1.0
    cells = [HILLSLOPE, cell(1, 2)]

    assert at("network_agreement", JUNE, cells, run) == [2, 2]
    assert at("downslope_distance", JUNE, cells, run) == [2 * CELL_M, CELL_M]


def test_the_agreement_and_the_distance_are_those_of_the_comparison_the_run_scores() -> None:
    run = transient_run()
    scored = network_comparison_from_run(run, timestep=JUNE)
    rows = rebuilt_rows(run, "network_agreement", [JUNE])[0]
    far = rebuilt_rows(run, "downslope_distance", [JUNE])[0]

    np.testing.assert_array_equal(rows, scored.agreement)
    missing = scored.agreement == 3
    np.testing.assert_array_equal(far[missing], scored.distance_to_simulated_m[missing])


def test_the_network_equals_the_stack_the_exports_read() -> None:
    run = transient_run()
    np.testing.assert_array_equal(
        rebuilt_rows(run, SIMULATED_ACTIVE_NETWORK, [JANUARY, JUNE]),
        simulated_active_network_stack(run, [JANUARY, JUNE]),
    )


def test_the_depression_is_the_closed_fill_and_is_served_at_every_step() -> None:
    run = transient_run()
    surface = run.mesh.topography.copy()
    surface[PIT] = -5.0
    run.mesh.topography = surface

    rows = rebuilt_rows(run, "depression_fill_depth", [0, 5, 9])

    assert REBUILT_FIELD_ROWS["depression_fill_depth"].static
    assert (rows == rows[0]).all()
    # The pit spills over the outlet cell at 0 m, plus the flood epsilon of 1 mm.
    assert rows[0][PIT] == pytest.approx(5.0, abs=2e-3)
    assert np.delete(rows[0], PIT).tolist() == [0.0] * (NX * 3 - 1)


def test_the_graph_is_built_once_for_every_step_asked_one_by_one(monkeypatch) -> None:
    built = []
    real = cell_fields.flow_geometry_from_run
    monkeypatch.setattr(
        cell_fields, "flow_geometry_from_run", lambda *a, **k: built.append(1) or real(*a, **k)
    )
    run = held_run()

    for step in range(6):
        rebuilt_rows(run, "network_agreement", [step])
        rebuilt_rows(run, "downslope_distance", [step])

    assert len(built) == 1


@pytest.mark.parametrize("field", ["simulated_active_network", "network_agreement"])
def test_a_run_without_a_release_flux_is_refused_by_name(field) -> None:
    run = transient_run()
    run.has_field = lambda variable, **_: variable == "topography"

    with pytest.raises(ValueError, match=f"{field} is not available.*no per-cell release_flux"):
        rebuilt_rows(run, field, [0])


def test_a_run_without_a_mesh_top_cannot_route_a_depression() -> None:
    run = transient_run()
    run.mesh.topography = None

    with pytest.raises(ValueError, match="no mesh topography"):
        rebuilt_rows(run, "depression_fill_depth", [0])


def test_the_classes_are_written_once_in_the_registry() -> None:
    assert AGREEMENT_LABELS == dict(REBUILT_FIELDS["network_agreement"].classes)
    assert "package_cells" not in FIELD_REGISTRY
    classes = dict(REBUILT_FIELDS["package_cells"].classes)
    assert [classes[code] for code in range(1, len(ACTING_PACKAGES) + 1)] == [
        name for name, _ in ACTING_PACKAGES
    ]
    assert (classes[0], classes[8]) == ("no exchange", "several")
    assert set(budget_terms_for("package_cells")) == {t for _, ts in ACTING_PACKAGES for t in ts}


def test_the_package_acting_on_a_cell_is_coded_by_priority() -> None:
    drain = np.array([[1.0, 0, 2, 0], [0, 0, 3, 0]])
    river = np.array([[0.0, 5, 4, 0], [0, 0, 0, 0]])
    root = {"budget": Group(drain=drain, river=river)}

    rows = package_cells_rows(root, 0, 2)

    assert rows.tolist() == [[2, 4, 8, 0], [0, 0, 2, 0]]
    assert rows.max(axis=0).tolist() == [2, 4, 8, 0]
