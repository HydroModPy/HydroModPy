"""The stream comparison figures: framing and redraw with the run settings."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from matplotlib.colors import to_hex

from hydromodpy.core.scoring.stream_defaults import STREAM_CRITERION_DEFAULTS
from hydromodpy.display.figures import _stream_comparison
from hydromodpy.display.figures._stream_comparison import (
    CELL_WEIGHT_PT,
    VEIL_ALPHA,
    comparison_from_run,
)
from hydromodpy.display.figures.flow_intermittence_map import FlowIntermittenceMap
from hydromodpy.display.figures.flow_persistence_map import FlowPersistenceMap
from hydromodpy.display.figures.seepage_map import SEEPAGE_COLOR, SeepageMap
from tests._helpers.sealed_runs import sealed_search
from tests._helpers.transient_network_run import transient_run

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

# The one-instant and persistence maps open on the catchment, in meters.
#
# Measured on the example 04 gallery: the seepage map drew a yes-or-no field
# with a continuous red ramp, so a reader looked for fractions of seepage the
# field does not hold; the three maps drew the whole buffered model box in
# kilometers from its corner, while the confusion map beside them opened on the
# catchment in projected meters. The maps now share the frame, the axes and a
# key that counts the cells a reader sees inside the outline.

CATCHMENT = (1, 2, 3)


"""The columns the delineated catchment holds: the valley without its rims."""


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

    assert len(fig.axes) == 1, "a yes-or-no field takes no color bar"
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


# The stream maps redraw the comparison with the settings the run was scored by.
#
# ``comparison_from_run`` reads the network output the run sealed, so a map of a
# trial scored at ``tau = 0`` over a ``touch`` map, weighted by area, draws that
# partition and not the defaults. A knob a caller names wins over the run's.

SEALED = {
    "outputs": {
        "streams": {
            "support": "network",
            "model": {
                "seepage_threshold": 0.0,
                "neighbours": "D4",
                "weighting": "area",
            },
            "map": {"complete": "data.hydrography", "drawn_by": "touch", "position_accuracy": 40.0},
            "time": "first",
        }
    }
}


@pytest.fixture
def captured(monkeypatch):
    """Record the knobs the redraw is asked for, without building it."""
    calls: list[dict] = []

    def record(sim, **knobs):
        calls.append(knobs)
        return object()

    monkeypatch.setattr(_stream_comparison, "network_comparison_from_run", record)
    return calls


def test_a_run_that_sealed_no_output_is_redrawn_with_the_defaults(captured) -> None:
    comparison_from_run(comparison_run())

    assert captured == [
        {
            "tau_specific_ratio": STREAM_CRITERION_DEFAULTS.tau_specific_ratio,
            "diagonal_neighbors": STREAM_CRITERION_DEFAULTS.diagonal_neighbors,
            "timestep": -1,
            "observed_rasterization": STREAM_CRITERION_DEFAULTS.observed_rasterization,
            "observed_position_accuracy_m": None,
            "heads_snap_radius_m": STREAM_CRITERION_DEFAULTS.heads_snap_radius_m,
            "heads_min_drained_area_km2": STREAM_CRITERION_DEFAULTS.heads_min_drained_area_km2,
            "clip_map_to_catchment": STREAM_CRITERION_DEFAULTS.clip_map_to_catchment,
        }
    ]


def test_a_run_that_sealed_an_output_is_redrawn_with_its_settings(captured) -> None:
    run = comparison_run()
    run.dir = sealed_search(SEALED)
    comparison_from_run(run)

    assert captured == [
        {
            "tau_specific_ratio": 0.0,
            "diagonal_neighbors": False,
            "timestep": 0,
            "observed_rasterization": "touch",
            "observed_position_accuracy_m": 40.0,
            "heads_snap_radius_m": STREAM_CRITERION_DEFAULTS.heads_snap_radius_m,
            "heads_min_drained_area_km2": STREAM_CRITERION_DEFAULTS.heads_min_drained_area_km2,
            "clip_map_to_catchment": STREAM_CRITERION_DEFAULTS.clip_map_to_catchment,
        }
    ]


def test_a_knob_the_caller_names_wins_over_the_run(captured) -> None:
    run = comparison_run()
    run.dir = sealed_search(SEALED)
    comparison_from_run(run, tau_specific_ratio=1.0e-3, diagonal_neighbors=True, timestep=-1)

    knobs = captured[0]
    assert knobs["tau_specific_ratio"] == 1.0e-3
    assert knobs["diagonal_neighbors"] is True
    assert knobs["timestep"] == -1
    assert knobs["observed_rasterization"] == "touch"


class _WeakRun(SimpleNamespace):
    """A run the memo can key on by identity, as it keys on a real one."""

    __eq__ = object.__eq__
    __hash__ = object.__hash__


def test_the_redraw_is_built_once_per_run_and_settings(captured) -> None:
    run = _WeakRun(**vars(comparison_run()))
    comparison_from_run(run)
    comparison_from_run(run)
    run.dir = sealed_search(SEALED)
    comparison_from_run(run)

    assert len(captured) == 2


def _without_recharge():
    return comparison_run(seepage_cells=[cell(AXIS_COLUMN, 2)], kept_recharge=False)


def test_the_sealed_threshold_reaches_the_partition() -> None:
    """A trial scored at tau = 0 needed no recharge, and neither does its redraw."""
    with pytest.raises(ValueError, match="kept no criterion mean recharge"):
        comparison_from_run(_without_recharge())

    run = _without_recharge()
    run.dir = sealed_search(SEALED)
    comparison = comparison_from_run(run)

    assert comparison.tau_specific_ratio == 0.0
    assert sorted(int(i) for i in comparison.simulated.nonzero()[0]) == [
        cell(AXIS_COLUMN, row) for row in range(3)
    ]
