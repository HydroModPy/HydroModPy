"""Stream comparison maps on a grid of CELL_M metres: framing, cell counts and redraw.

The seepage and persistence maps open on the catchment, in metres. The redraw reads
the settings the run was scored by (threshold, neighbours, weighting).
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from matplotlib.colors import to_hex

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

# The columns the delineated catchment holds: the valley without its rims.
CATCHMENT = (1, 2, 3)


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


def test_seepage_map_two_classes(mpl) -> None:
    run = _seepage_run([cell(AXIS_COLUMN, 0), cell(AXIS_COLUMN, 1)])
    fig, ax = mpl.subplots()

    SeepageMap().render(run, ax)

    assert len(fig.axes) == 1, "a yes-or-no field takes no color bar"
    seepage = [c for c in ax.collections if c.get_label() == "_seepage"]
    assert len(seepage) == 1
    assert len(seepage[0].get_paths()) == 2
    assert seepage[0].get_linewidths()[0] == pytest.approx(CELL_WEIGHT_PT)
    assert to_hex(seepage[0].get_facecolor()[0]) == SEEPAGE_COLOR


def test_seepage_map_whole_mesh(mpl) -> None:
    run = _seepage_run([cell(AXIS_COLUMN, 0), cell(0, 1)])
    fig, ax = mpl.subplots()

    SeepageMap().render(run, ax, extent="mesh")

    assert ax.get_xlim() == pytest.approx((0.0, NX * CELL_M))
    assert not _veils(ax)
    assert "seepage (2 cells)" in legend_labels(ax)
    assert "over the whole mesh" in legend_note(ax)


def test_intermittence_counts_catchment(mpl) -> None:
    run = transient_run()
    run.geographic = lambda feature: comparison_run(catchment_columns=CATCHMENT).geographic(feature)
    fig, ax = mpl.subplots()

    FlowIntermittenceMap().render(run, ax, overlays=())

    dry = next(label for label in legend_labels(ax) if label.startswith("dry"))
    # Nine catchment cells, three of them on the axis that flows.
    assert dry == "dry (6 cells)"


@pytest.mark.parametrize("figure", [FlowPersistenceMap(), FlowIntermittenceMap()], ids=type)
def test_persistence_maps_whole_mesh(mpl, figure) -> None:
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


class _WeakRun(SimpleNamespace):
    """A run the memo can key on by identity, as it keys on a real one."""

    __eq__ = object.__eq__
    __hash__ = object.__hash__


def test_redraw_built_once(captured) -> None:
    run = _WeakRun(**vars(comparison_run()))
    comparison_from_run(run)
    comparison_from_run(run)
    run.dir = sealed_search(SEALED)
    comparison_from_run(run)

    assert len(captured) == 2


def _without_recharge():
    return comparison_run(seepage_cells=[cell(AXIS_COLUMN, 2)], kept_recharge=False)


def test_sealed_threshold_in_partition() -> None:
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
