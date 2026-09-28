"""The one-instant and persistence maps open on the catchment, in metres.

Measured on the example 04 gallery: the seepage map drew a yes-or-no field
with a continuous red ramp, so a reader looked for fractions of seepage the
field does not hold; the three maps drew the whole buffered model box in
kilometres from its corner, while the confusion map beside them opened on the
catchment in projected metres. The maps now share the frame, the axes and a
key that counts the cells a reader sees inside the outline.
"""

from __future__ import annotations

import numpy as np
import pytest
from matplotlib.colors import to_hex

from hydromodpy.display.figures._stream_comparison import CELL_WEIGHT_PT, VEIL_ALPHA
from hydromodpy.display.figures.flow_intermittence_map import FlowIntermittenceMap
from hydromodpy.display.figures.flow_persistence_map import FlowPersistenceMap
from hydromodpy.display.figures.seepage_map import SEEPAGE_COLOR, SeepageMap
from tests.unit.results._transient_network_run import transient_run

from ._network_comparison_run import (
    AXIS_COLUMN,
    CELL_M,
    NX,
    NY,
    cell,
    comparison_run,
    legend_labels,
    legend_note,
)

CATCHMENT = (1, 2, 3)
"""The columns the delineated catchment holds: the valley without its rims."""


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _seepage_run(seeping: list[int], *, catchment=CATCHMENT):
    run = comparison_run(catchment_columns=catchment)
    mask = np.zeros(NX * NY)
    mask[seeping] = 1.0
    fields = {"seepage_mask": mask}
    run.has_field = lambda variable, **_: variable in fields
    run.field = lambda variable, **_: fields[variable]
    return run


def _veils(ax) -> list:
    return [patch for patch in ax.patches if patch.get_alpha() == VEIL_ALPHA]


# --------------------------------------------------------------------------- #
# the seepage map
# --------------------------------------------------------------------------- #


def test_the_seepage_map_draws_two_classes_and_no_ramp(mpl) -> None:
    run = _seepage_run([cell(AXIS_COLUMN, 0), cell(AXIS_COLUMN, 1)])
    fig, ax = mpl.subplots()

    SeepageMap().render(run, ax)

    assert len(fig.axes) == 1, "a yes-or-no field takes no colour bar"
    seepage = [c for c in ax.collections if c.get_label() == "_seepage"]
    assert len(seepage) == 1
    assert len(seepage[0].get_paths()) == 2
    assert seepage[0].get_linewidths()[0] == pytest.approx(CELL_WEIGHT_PT)
    assert to_hex(seepage[0].get_facecolor()[0]) == SEEPAGE_COLOR


def test_the_seepage_key_counts_the_cells_inside_the_catchment(mpl) -> None:
    # One seeping cell inside the catchment, one on a rim outside it.
    run = _seepage_run([cell(AXIS_COLUMN, 0), cell(0, 1)])
    fig, ax = mpl.subplots()

    SeepageMap().render(run, ax)

    labels = legend_labels(ax)
    assert "seepage (1 cells)" in labels
    assert f"no seepage ({len(CATCHMENT) * NY - 1} cells)" in labels
    assert "cells counted in the catchment" in legend_note(ax)


def test_the_seepage_map_opens_on_the_catchment_in_projected_metres(mpl) -> None:
    run = _seepage_run([cell(AXIS_COLUMN, 0)])
    fig, ax = mpl.subplots()

    SeepageMap().render(run, ax)

    assert ax.get_xlabel() == "x (m)"
    assert ax.get_ylabel() == "y (m)"
    xmin, xmax = ax.get_xlim()
    assert xmin > 0.5 * CELL_M
    assert xmax < (NX - 0.5) * CELL_M
    assert len(_veils(ax)) == 1


def test_the_whole_mesh_is_still_one_option_away(mpl) -> None:
    run = _seepage_run([cell(AXIS_COLUMN, 0), cell(0, 1)])
    fig, ax = mpl.subplots()

    SeepageMap().render(run, ax, extent="mesh")

    assert ax.get_xlim() == pytest.approx((0.0, NX * CELL_M))
    assert not _veils(ax)
    assert "seepage (2 cells)" in legend_labels(ax)
    assert "over the whole mesh" in legend_note(ax)


# --------------------------------------------------------------------------- #
# the persistence maps
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("figure", [FlowPersistenceMap(), FlowIntermittenceMap()], ids=type)
def test_the_persistence_maps_open_on_the_catchment(mpl, figure) -> None:
    run = transient_run()
    run.geographic = lambda feature: comparison_run(catchment_columns=CATCHMENT).geographic(feature)
    fig, ax = mpl.subplots()

    figure.render(run, ax, overlays=())

    assert ax.get_xlabel() == "x (m)"
    xmin, xmax = ax.get_xlim()
    assert xmin > 0.5 * CELL_M
    assert xmax < (NX - 0.5) * CELL_M
    assert len(_veils(ax)) == 1
    note = legend_note(ax)
    assert "cells counted in the catchment" in note
    assert "tau" not in note and "tau" not in ax.get_title()


def test_the_intermittence_key_counts_the_catchment_only(mpl) -> None:
    run = transient_run()
    run.geographic = lambda feature: comparison_run(catchment_columns=CATCHMENT).geographic(feature)
    fig, ax = mpl.subplots()

    FlowIntermittenceMap().render(run, ax, overlays=())

    dry = next(label for label in legend_labels(ax) if label.startswith("dry"))
    # Nine catchment cells, three of them on the axis that flows.
    assert dry == "dry (6 cells)"


@pytest.mark.parametrize("figure", [FlowPersistenceMap(), FlowIntermittenceMap()], ids=type)
def test_the_persistence_maps_keep_the_mesh_on_request(mpl, figure) -> None:
    fig, ax = mpl.subplots()

    figure.render(transient_run(), ax, overlays=(), extent="mesh")

    assert ax.get_xlim() == pytest.approx((0.0, NX * CELL_M))
    assert "over the whole mesh" in legend_note(ax)
