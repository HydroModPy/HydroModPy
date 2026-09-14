"""The map of the drainage network a routed flux keeps active.

The figure composes: it takes the per-cell mask
:mod:`hydromodpy.results.derive.views` reduces from a time-varying field and
draws it. The reduction is tested where it lives, so these tests hand the
figure a mask that is known cell by cell and assert what the page then says:
which cells carry ink, how wide they are drawn, what frame they are drawn in,
and whether a reader can tell from the figure alone what cut produced the
network on it.

The mesh is the grid of :mod:`tests.unit.display._network_comparison_run`,
whose watershed a test can narrow to a couple of columns.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.display.figures._stream_comparison import GROUND_COLOR
from hydromodpy.display.figures.simulated_active_network import (
    ACTIVE_COLOR,
    SimulatedActiveNetworkMap,
)
from hydromodpy.results.derive import views

from ._network_comparison_run import (
    CELL_M,
    NX,
    NY,
    cell,
    comparison_run,
    drawn_cells,
    legend_labels,
    legend_note,
    map_key,
)

ACTIVE_CELLS = (cell(2, 0), cell(2, 1), cell(4, 2))
"""Two cells of the middle column and one on the far eastern flank."""


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


@pytest.fixture
def masked(monkeypatch):
    """Drive the figure with a mask that is known before it is drawn."""

    def install(
        values: np.ndarray,
        *,
        mode: str = "last",
        label: str = "steady active cells",
    ) -> None:
        monkeypatch.setattr(views, "cell_field_active_mask", lambda *_a, **_k: values)
        monkeypatch.setattr(views, "resolve_cell_field_active_mode", lambda *_a, **_k: mode)
        monkeypatch.setattr(views, "cell_field_active_mode_label", lambda *_a, **_k: label)

    return install


def _binary_mask(active=ACTIVE_CELLS) -> np.ndarray:
    values = np.zeros(NX * NY, dtype="float64")
    values[list(active)] = 1.0
    return values


def _layer(ax, label: str):
    return next(item for item in ax.collections if str(item.get_label()) == label)


# --------------------------------------------------------------------------- #
# the network, and the ground it is drawn over
# --------------------------------------------------------------------------- #


def test_the_map_draws_the_cells_the_mask_calls_active(mpl, masked) -> None:
    masked(_binary_mask())
    fig, ax = mpl.subplots()

    SimulatedActiveNetworkMap().render(comparison_run(), ax)

    try:
        assert drawn_cells(_layer(ax, "active network")) == sorted(ACTIVE_CELLS)
        assert len(_layer(ax, "modelled, not active").get_paths()) == NX * NY - len(ACTIVE_CELLS)
        assert legend_labels(ax) == [
            "active network (3 cells)",
            "modelled, not active (12 cells)",
        ]
    finally:
        mpl.close(fig)


def test_a_thresholded_network_carries_no_continuous_scale(mpl, masked) -> None:
    # The mask is one or zero. A colorbar running from 0 to 1 over two values
    # spends a tenth of the page saying nothing, and reads as a field.
    masked(_binary_mask())
    fig, ax = mpl.subplots()

    SimulatedActiveNetworkMap().render(comparison_run(), ax)

    try:
        assert not fig.axes[1:], "a two-valued mask is a class, not a scale"
    finally:
        mpl.close(fig)


def test_the_active_cells_are_drawn_wider_than_one_cell(mpl, masked) -> None:
    from matplotlib.colors import to_rgba

    masked(_binary_mask())
    fig, ax = mpl.subplots()

    SimulatedActiveNetworkMap().render(comparison_run(), ax)

    try:
        active = _layer(ax, "active network")
        assert float(active.get_linewidth()[0]) > 0.0
        edge = tuple(np.asarray(active.get_edgecolor()).reshape(-1))
        assert edge == pytest.approx(to_rgba(ACTIVE_COLOR))
        ground = _layer(ax, "modelled, not active")
        assert float(ground.get_linewidth()[0]) == 0.0
        assert tuple(np.asarray(ground.get_facecolor()).reshape(-1)) == pytest.approx(
            to_rgba(GROUND_COLOR)
        )
    finally:
        mpl.close(fig)


def test_the_persistence_mode_keeps_its_scale(mpl, masked) -> None:
    # A per-cell fraction of active timesteps is a continuous field, and the
    # colorbar is the only thing that says what a middling cell means.
    masked(
        np.linspace(0.0, 1.0, NX * NY),
        mode="persistence",
        label="persistence >= 0.5",
    )
    fig, ax = mpl.subplots()

    SimulatedActiveNetworkMap().render(comparison_run(), ax)

    try:
        assert fig.axes[1:], "a fraction needs its scale"
        assert "active persistence" in ax.get_title()
    finally:
        mpl.close(fig)


def test_the_persistence_mode_says_the_reduction_it_performs(mpl, masked) -> None:
    # ``cell_field_active_mode_label`` names this mode after a cut, and the
    # map applies none: it draws the whole 0-1 ramp. Printed as it comes, the
    # page claimed a threshold no cell had been through.
    masked(
        np.linspace(0.0, 1.0, NX * NY),
        mode="persistence",
        label="persistence >= 0.5",
    )
    fig, ax = mpl.subplots()

    SimulatedActiveNetworkMap().render(comparison_run(), ax)

    try:
        assert "persistence >= 0.5" not in legend_note(ax)
        assert "persistence >= 0.5" not in ax.get_title()
        assert "the share of the timesteps each cell is active, drawn uncut" in legend_note(ax)
    finally:
        mpl.close(fig)


def test_a_cell_active_at_no_step_is_ground_and_not_the_foot_of_the_ramp(mpl, masked) -> None:
    # A sequential ramp is darkest at zero, so cells that never carried water
    # covered the page and the network vanished into its own background. The
    # ground is its own collection under the ramp rather than a colour of it,
    # because a mapped collection carries one weight for all its cells and the
    # weight the network needs would widen the ground over the network.
    from matplotlib.colors import to_rgba

    fraction = np.zeros(NX * NY, dtype="float64")
    fraction[list(ACTIVE_CELLS)] = 0.75
    masked(fraction, mode="persistence", label="persistence >= 0.5")
    fig, ax = mpl.subplots()

    SimulatedActiveNetworkMap().render(comparison_run(), ax)

    try:
        field = next(item for item in ax.collections if item.get_array() is not None)
        drawn = np.asarray(field.get_array(), dtype="float64")
        assert np.isnan(drawn[cell(0, 0)]), "a cell active at no step carries no value"
        assert drawn[cell(2, 0)] == pytest.approx(0.75)
        assert field.get_cmap()(np.nan)[3] == 0.0, (
            "the ramp leaves the ground to the collection under it"
        )
        assert float(field.get_linewidth()[0]) > 0.0

        ground = _layer(ax, "never active")
        assert ground.get_zorder() < field.get_zorder()
        assert float(ground.get_linewidth()[0]) == 0.0, (
            "the ground may not widen over the network it exists to set off"
        )
        assert tuple(np.asarray(ground.get_facecolor()).reshape(-1)) == pytest.approx(
            to_rgba(GROUND_COLOR)
        )
        assert drawn_cells(ground) == sorted(
            index for index in range(NX * NY) if index not in ACTIVE_CELLS
        )
        assert f"never active ({NX * NY - len(ACTIVE_CELLS)} cells)" in legend_labels(ax)
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the cut that produced the network is on the page
# --------------------------------------------------------------------------- #


def test_the_note_names_the_cut_that_produced_the_network(mpl, masked) -> None:
    # Without it a reader cannot tell a model that drains half its catchment
    # from a threshold set too low, and the two are the same picture.
    masked(_binary_mask())
    fig, ax = mpl.subplots()

    SimulatedActiveNetworkMap().render(comparison_run(), ax, threshold=0.25)

    try:
        note = legend_note(ax)
        assert "active where accumulation_flux > 0.25 m3 s-1" in note
        assert "reduced over time as: steady active cells" in note
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the frame
# --------------------------------------------------------------------------- #


def test_the_map_opens_on_the_catchment(mpl, masked) -> None:
    masked(_binary_mask())
    fig, ax = mpl.subplots()

    SimulatedActiveNetworkMap().render(comparison_run(catchment_columns=[0, 1]), ax)

    try:
        assert ax.get_xlim()[1] < 3 * CELL_M
        assert "frame: the delineated catchment" in legend_note(ax)
    finally:
        mpl.close(fig)


def test_a_caller_may_ask_for_the_whole_mesh(mpl, masked) -> None:
    masked(_binary_mask())
    fig, ax = mpl.subplots()

    SimulatedActiveNetworkMap().render(comparison_run(catchment_columns=[0, 1]), ax, extent="mesh")

    try:
        assert ax.get_xlim()[1] >= NX * CELL_M
        assert "frame: the whole mesh" in legend_note(ax)
    finally:
        mpl.close(fig)


def test_a_frame_that_leaves_active_cells_off_the_page_says_how_many(mpl, masked) -> None:
    # This network is not bounded by the catchment: the routed flux keeps
    # cells active outside it. A crop that drops some has to name them, or
    # the count in the legend contradicts what the reader can see.
    masked(_binary_mask())
    fig, ax = mpl.subplots()

    SimulatedActiveNetworkMap().render(comparison_run(catchment_columns=[0, 1]), ax)

    try:
        assert "outside this frame: 3 cells of the active network" in legend_note(ax)
        assert "active network (3 cells)" in legend_labels(ax)
    finally:
        mpl.close(fig)


def test_the_whole_mesh_hides_nothing_and_says_nothing(mpl, masked) -> None:
    masked(_binary_mask())
    fig, ax = mpl.subplots()

    SimulatedActiveNetworkMap().render(comparison_run(catchment_columns=[0, 1]), ax, extent="mesh")

    try:
        assert "outside this frame" not in legend_note(ax)
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the gallery
# --------------------------------------------------------------------------- #


def test_the_key_and_the_note_sit_outside_the_map(mpl, masked) -> None:
    masked(_binary_mask())
    fig, ax = mpl.subplots()

    SimulatedActiveNetworkMap().render(comparison_run(), ax)

    try:
        fig.canvas.draw()
        assert map_key(ax).get_window_extent().y1 <= ax.get_window_extent().y0 + 1.0
        assert not ax.texts
    finally:
        mpl.close(fig)
