"""Which cell the boundary-package map attributes to which package, and how it
puts a 1 % class on a page.

The mesh is one row of unit cells and the budget of each package is written
here cell by cell, so the map the figure draws is known before it is drawn.
Reading a drawn collection back to a cell index only needs the left edge of
its polygons, which is the cell index itself.

Two families of assertion live here. The first is what the map says: which
cell belongs to which package, and what the legend and the note report about
it. The second is whether the map can be read at all, which on this figure is
not a matter of taste: the classes are one-cell-wide features drawn over tens
of thousands of background cells, and a class that rounds away below a pixel
is a class the reader never sees. Those are measured on the rendered canvas,
in pixels, which is the only place the question has an answer.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.display.figures.boundary_package_map import (
    BOUNDARY_PACKAGES,
    GROUND_COLOR,
    MARK_POINTS,
    SEVERAL_COLOR,
    BoundaryPackageMap,
)

N_CELLS = 4


class _Store:
    """The Zarr store of one run, reduced to what a figure reads off it.

    ``root`` is walked with the same ``group[name]`` lookup the real reader
    uses, so a component the figure asks for by its registry path is found
    here exactly as it would be on disk.
    """

    def __init__(self, stacks: dict[str, np.ndarray]) -> None:
        self.root = {"budget": dict(stacks)}
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _row_mesh(n_cells: int) -> tuple[np.ndarray, np.ndarray]:
    """Return the vertices and faces of one row of ``n_cells`` unit cells."""
    vertices = np.asarray(
        [[x, y, 0.0] for y in (0.0, 1.0) for x in range(n_cells + 1)],
        dtype=float,
    )
    faces = np.asarray(
        [[i, i + 1, n_cells + 2 + i, n_cells + 1 + i] for i in range(n_cells)],
        dtype=int,
    )
    return vertices, faces


def _square_mesh(n_side: int) -> tuple[np.ndarray, np.ndarray]:
    """Return the vertices and faces of an ``n_side`` by ``n_side`` grid.

    Cell ``row * n_side + column``, so a cell index names a position the test
    can put a package on and find again on the canvas.
    """
    nodes = n_side + 1
    vertices = np.asarray(
        [[x, y, 0.0] for y in range(nodes) for x in range(nodes)],
        dtype=float,
    )
    faces = np.asarray(
        [
            [
                row * nodes + col,
                row * nodes + col + 1,
                (row + 1) * nodes + col + 1,
                (row + 1) * nodes + col,
            ]
            for row in range(n_side)
            for col in range(n_side)
        ],
        dtype=int,
    )
    return vertices, faces


def _run(
    budgets: dict[str, np.ndarray],
    *,
    n_timesteps: int = 1,
    mesh: tuple[np.ndarray, np.ndarray] | None = None,
    catchment: tuple[float, float, float, float] | None = None,
) -> SimpleNamespace:
    """Return a run whose ``budgets`` are ``(n_timesteps, ...)`` per component.

    ``catchment`` is the ``(x0, y0, x1, y1)`` of the delineation, under the
    only two members the figure reads off a geographic feature.
    """
    vertices, faces = mesh if mesh is not None else _row_mesh(N_CELLS)
    stacks = {name: np.asarray(values, dtype=float) for name, values in budgets.items()}
    opened: list[_Store] = []

    def open_zarr(_sim_id):
        opened.append(_Store(stacks))
        return opened[-1]

    def geographic(feature: str):
        if feature != "watershed" or catchment is None:
            raise KeyError(feature)
        return SimpleNamespace(empty=False, total_bounds=np.asarray(catchment, dtype=float))

    return SimpleNamespace(
        sim_id="sim-boundary",
        name="nancon",
        n_timesteps=n_timesteps,
        mesh=SimpleNamespace(vertices=vertices, face_node_connectivity=faces),
        has_field=lambda variable, **_: variable in stacks,
        field=lambda variable, timestep=-1, **_: stacks[variable][timestep],
        geographic=geographic,
        opened_stores=opened,
        _catalog=SimpleNamespace(open_zarr=open_zarr),
    )


def _flux_on(
    cells,
    *,
    n_timesteps: int = 1,
    rate: float = -1.5e-3,
    n_cells: int = N_CELLS,
) -> np.ndarray:
    """Return a one-component budget stack carrying ``rate`` on ``cells``."""
    stack = np.zeros((n_timesteps, n_cells), dtype=float)
    stack[:, list(cells)] = rate
    return stack


def _idle_after_first_step(cells, *, n_timesteps: int = 3) -> np.ndarray:
    """Return a component that acts on ``cells`` at the first step only."""
    stack = np.zeros((n_timesteps, N_CELLS), dtype=float)
    stack[0, list(cells)] = -4.0e-4
    return stack


def _axes(figsize: tuple[float, float] = (6.4, 4.8), dpi: float = 100.0):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt.subplots(figsize=figsize, dpi=dpi)


def _cells_by_color(ax) -> dict[str, list[int]]:
    """Return the cells each class covers with its true footprint.

    The footprints are the polygon collections; the page-space marks drawn on
    top of them are read by :func:`_marked_cells`, which asks a different
    question.
    """
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import to_hex

    painted: dict[str, list[int]] = {}
    for collection in ax.collections:
        if not isinstance(collection, PolyCollection):
            continue
        color = to_hex(collection.get_facecolor()[0]).upper()
        cells = [int(round(path.vertices[:, 0].min())) for path in collection.get_paths()]
        painted[color] = sorted(cells)
    return painted


def _marked_cells(ax) -> dict[str, list[int]]:
    """Return the cells each class carries a page-space mark on, by colour."""
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import to_hex

    marked: dict[str, list[int]] = {}
    for collection in ax.collections:
        if isinstance(collection, PolyCollection):
            continue
        color = to_hex(collection.get_facecolor()[0]).upper()
        marked[color] = sorted(int(np.floor(x)) for x, _y in collection.get_offsets())
    return marked


def _painted_box(fig, ax, color: str, tolerance: float = 0.12) -> tuple[int, float, float]:
    """Return how many pixels of ``color`` the map covers, and their box.

    The end of the chain: whatever the figure asked matplotlib for, this is
    what a reader gets. A class that covers no pixel is a class that is not on
    the page, whatever the arrays behind it say. Only the map is read, never
    the margins, since the legend swatch of a class is painted in the very
    colour the class is being looked for in.
    """
    from matplotlib.colors import to_rgb

    fig.canvas.draw()
    canvas = np.asarray(fig.canvas.buffer_rgba(), dtype=float) / 255.0
    box = ax.get_window_extent()
    top = canvas.shape[0] - box.y1
    window = canvas[
        max(int(np.floor(top)), 0) : int(np.ceil(top + box.height)),
        max(int(np.floor(box.x0)), 0) : int(np.ceil(box.x1)),
        :3,
    ]
    hit = np.all(np.abs(window - np.asarray(to_rgb(color))) <= tolerance, axis=-1)
    rows, cols = np.nonzero(hit)
    if rows.size == 0:
        return 0, 0.0, 0.0
    return int(rows.size), float(cols.max() - cols.min() + 1), float(rows.max() - rows.min() + 1)


def _labels(ax) -> list[str]:
    return [text.get_text() for text in ax.get_legend().get_texts()]


def _notes(ax) -> str:
    return "\n".join(text.get_text() for text in ax.texts)


def _lightness(rgb) -> float:
    """Return the CIE L* of one RGB triple, which is what greyscale keeps."""
    channels = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb[:3]]
    y = 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    return 116.0 * y ** (1 / 3) - 16.0 if y > 0.008856 else 903.3 * y


def test_each_package_paints_the_cells_its_flux_reaches() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    sim = _run({"drain": _flux_on([0, 1]), "stream": _flux_on([3], rate=2.0e-2)})
    fig, ax = _axes()
    try:
        BoundaryPackageMap().render(sim, ax)
        painted = _cells_by_color(ax)
        assert painted[BOUNDARY_PACKAGES["drain"][1]] == [0, 1]
        assert painted[BOUNDARY_PACKAGES["stream"][1]] == [3]
        assert painted[GROUND_COLOR] == [2]
    finally:
        plt.close(fig)


def test_a_cell_two_packages_act_on_is_drawn_as_its_own_class() -> None:
    """No package wins an overlap: the cell leaves both and says it is shared."""
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    sim = _run({"drain": _flux_on([0, 1]), "stream": _flux_on([1, 2])})
    fig, ax = _axes()
    try:
        BoundaryPackageMap().render(sim, ax)
        painted = _cells_by_color(ax)
        assert painted[SEVERAL_COLOR] == [1]
        assert painted[BOUNDARY_PACKAGES["drain"][1]] == [0]
        assert painted[BOUNDARY_PACKAGES["stream"][1]] == [2]
        assert "several packages (1 cell)" in _labels(ax)
    finally:
        plt.close(fig)


def test_a_package_idle_at_the_last_step_still_owns_its_cells() -> None:
    """A drain above the water table on the last day is still a drain cell."""
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    sim = _run({"drain": _idle_after_first_step([0, 2])}, n_timesteps=3)
    fig, ax = _axes()
    try:
        BoundaryPackageMap().render(sim, ax)
        assert _cells_by_color(ax)[BOUNDARY_PACKAGES["drain"][1]] == [0, 2]
        assert "any of the 3 persisted steps" in _notes(ax)
    finally:
        plt.close(fig)


def test_over_step_narrows_the_map_to_the_day_it_draws() -> None:
    """The other question the same field answers: who exchanges water today."""
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    sim = _run({"drain": _idle_after_first_step([0, 2])}, n_timesteps=3)
    fig, ax = _axes()
    try:
        BoundaryPackageMap().render(sim, ax, over="step")
        assert BOUNDARY_PACKAGES["drain"][1] not in _cells_by_color(ax)
        assert "drain (DRN, 0 cells)" in _labels(ax)
        assert "at step 3" in _notes(ax)
    finally:
        plt.close(fig)


def test_over_step_reads_the_step_the_caller_names() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    sim = _run({"drain": _idle_after_first_step([0, 2])}, n_timesteps=3)
    fig, ax = _axes()
    try:
        BoundaryPackageMap().render(sim, ax, over="step", timestep=0)
        assert _cells_by_color(ax)[BOUNDARY_PACKAGES["drain"][1]] == [0, 2]
    finally:
        plt.close(fig)


def test_an_unknown_extent_is_refused_by_name() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    fig, ax = _axes()
    try:
        with pytest.raises(ValueError, match="'run' or 'step'"):
            BoundaryPackageMap().render(_run({"drain": _flux_on([0])}), ax, over="year")
    finally:
        plt.close(fig)


def test_a_package_that_never_acts_keeps_its_legend_entry() -> None:
    """Built and never applied is a result the reader must be able to see."""
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    sim = _run({"drain": _flux_on([0]), "river": np.zeros((1, N_CELLS))})
    fig, ax = _axes()
    try:
        BoundaryPackageMap().render(sim, ax)
        assert "river (RIV, 0 cells)" in _labels(ax)
        assert BOUNDARY_PACKAGES["river"][1] not in _cells_by_color(ax)
        assert BOUNDARY_PACKAGES["river"][1] not in _marked_cells(ax)
    finally:
        plt.close(fig)


def test_the_note_reads_a_zero_entry_as_the_measurement_it_is() -> None:
    """What an empty package means on the page, and what it must not claim.

    The reference run carries a ``constant_head`` array of zeros and declares
    no CHD anywhere in its configuration: MODFLOW-NWT writes the record either
    way. So the zero says no cell exchanged water on that component, which is
    measured, and says nothing about whether the package was built, which the
    store does not hold.
    """
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    sim = _run({"drain": _flux_on([0]), "constant_head": np.zeros((1, N_CELLS))})
    fig, ax = _axes()
    try:
        BoundaryPackageMap().render(sim, ax)
        note = _notes(ax)
        assert "0 cells means no cell exchanges water on that component" in note
        assert "1 of 4 mesh cells (25.0 %) exchange water" in note
        assert "declared" not in note
        assert "constant_head (CHD, 0 cells)" in _labels(ax)
    finally:
        plt.close(fig)


def test_a_layered_budget_is_collapsed_onto_the_faces() -> None:
    """A WEL rate on any layer puts the package on that cell, once."""
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    well = np.zeros((1, 3, N_CELLS), dtype=float)
    well[0, 2, 1] = -8.0e-3
    sim = _run({"well": well})
    fig, ax = _axes()
    try:
        BoundaryPackageMap().render(sim, ax)
        assert _cells_by_color(ax)[BOUNDARY_PACKAGES["well"][1]] == [1]
    finally:
        plt.close(fig)


def test_layers_that_cancel_out_still_name_the_cell() -> None:
    """Signed layer fluxes that sum to zero are not an absent package."""
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    well = np.zeros((1, 2, N_CELLS), dtype=float)
    well[0, 0, 3] = 5.0e-3
    well[0, 1, 3] = -5.0e-3
    sim = _run({"well": well})
    fig, ax = _axes()
    try:
        BoundaryPackageMap().render(sim, ax)
        assert _cells_by_color(ax)[BOUNDARY_PACKAGES["well"][1]] == [3]
    finally:
        plt.close(fig)


def test_a_budget_that_does_not_fit_the_mesh_is_refused_by_name() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    sim = _run({"drain": np.zeros((1, N_CELLS + 1))})
    fig, ax = _axes()
    try:
        with pytest.raises(ValueError, match="'drain' budget holds 5 values"):
            BoundaryPackageMap().render(sim, ax)
    finally:
        plt.close(fig)


def test_unavailable_reason_names_every_component_and_the_option() -> None:
    reason = BoundaryPackageMap().unavailable_reason(_run({"head": np.zeros((1, N_CELLS))}))
    assert isinstance(reason, str)
    for name in BOUNDARY_PACKAGES:
        assert name in reason
    assert "[simulation.results.budget] spatial_fields = true" in reason


def test_one_stored_component_is_enough_to_serve_the_figure() -> None:
    assert BoundaryPackageMap().unavailable_reason(_run({"lake": _flux_on([0])})) is None


def test_render_refuses_with_the_sentence_it_reports() -> None:
    """A reader who calls render directly gets the reason, not an empty panel."""
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    sim = _run({"head": np.zeros((1, N_CELLS))})
    figure = BoundaryPackageMap()
    fig, ax = _axes()
    try:
        with pytest.raises(ValueError) as excinfo:
            figure.render(sim, ax)
        assert str(excinfo.value) == figure.unavailable_reason(sim)
    finally:
        plt.close(fig)


def test_every_class_is_separable_in_greyscale() -> None:
    """The colours are what the map is read by, so they must survive a print."""
    pytest.importorskip("matplotlib")
    from matplotlib.colors import to_rgb

    colors = [color for _, color in BOUNDARY_PACKAGES.values()]
    colors += [SEVERAL_COLOR, GROUND_COLOR]
    levels = sorted(_lightness(to_rgb(color)) for color in colors)
    gaps = np.diff(levels)
    assert gaps.min() >= 8.0, dict(zip(colors, levels, strict=False))


def test_the_packages_climb_in_lightness_in_the_order_declared() -> None:
    """Any subset of the palette keeps the spacing the whole palette has."""
    pytest.importorskip("matplotlib")
    from matplotlib.colors import to_rgb

    levels = [_lightness(to_rgb(color)) for _, color in BOUNDARY_PACKAGES.values()]
    assert levels == sorted(levels)


def test_every_package_is_a_registered_budget_field() -> None:
    """The figure reads its components by name, like any other field."""
    from hydromodpy.results.derive.config_flags import BUDGET_SPATIAL_OPTION, config_option_for
    from hydromodpy.results.field_registry import get

    for name in BOUNDARY_PACKAGES:
        descriptor = get(name)
        assert descriptor.zarr_path == f"budget/{name}"
        assert descriptor.units == "m3 s-1"
        assert config_option_for(name) == BUDGET_SPATIAL_OPTION


def test_the_whole_run_is_read_in_one_opening_of_the_store() -> None:
    """The cost of the default question, which is what makes it affordable.

    Asked one timestep at a time, the run-wide map reopens the store once per
    step and per component: a daily decade over six packages is tens of
    thousands of openings for one figure.
    """
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    sim = _run(
        {"drain": _idle_after_first_step([0], n_timesteps=200), "river": _flux_on([2])},
        n_timesteps=200,
    )
    fig, ax = _axes()
    try:
        BoundaryPackageMap().render(sim, ax)
        assert len(sim.opened_stores) == 1
        assert sim.opened_stores[0].closed, "the store is released once the map is read"
    finally:
        plt.close(fig)


def test_reading_the_step_alone_never_opens_the_store() -> None:
    """``over='step'`` is the cheap question and stays on the single-step read."""
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    sim = _run({"drain": _idle_after_first_step([0, 2])}, n_timesteps=3)
    fig, ax = _axes()
    try:
        BoundaryPackageMap().render(sim, ax, over="step", timestep=0)
        assert sim.opened_stores == []
    finally:
        plt.close(fig)


def test_the_planner_counts_this_figure_among_the_budget_consumers() -> None:
    """Optional fields are still a request for the group the fields live in.

    Without this the figure is invisible to the reconciliation: the run drops
    the per-cell budget it was never told anyone wanted, and the map the user
    asked for is reported unavailable on its own output.
    """
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.workflow.steps.planning import _figure_budget_fields

    fields = _figure_budget_fields(
        DisplayConfig(figures=["boundary_package_map"]), display_active=True
    )

    assert set(fields) == set(BOUNDARY_PACKAGES)


def test_no_component_is_required_so_one_package_is_enough() -> None:
    """Required would report the figure unavailable on a run carrying one."""
    spec = BoundaryPackageMap().spec

    assert spec.required_fields == ()
    assert spec.optional_fields == tuple(BOUNDARY_PACKAGES)


def test_the_figure_is_requestable_from_a_toml() -> None:
    """Registered, and reachable through ``[display].figures`` with its knobs."""
    from hydromodpy.display import figure_registry
    from hydromodpy.display.config import DisplayConfig

    assert isinstance(figure_registry.get("boundary_package_map"), BoundaryPackageMap)
    config = DisplayConfig(
        figures=["boundary_package_map"],
        overrides={"boundary_package_map": {"timestep": 0}},
    )
    assert config.overrides["boundary_package_map"]["timestep"] == 0


def test_the_view_is_the_catchment_not_the_buffered_mesh() -> None:
    """Half the mesh of the reference run is outside the delineated basin.

    Spending that half on background is what makes a 1 % class unreadable, so
    the frame is the catchment, not the box the solver was given.
    """
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    mesh = _row_mesh(20)
    sim = _run(
        {"drain": _flux_on([6, 7], n_cells=20)},
        mesh=mesh,
        catchment=(5.0, 0.0, 10.0, 1.0),
    )
    fig, ax = _axes()
    try:
        BoundaryPackageMap().render(sim, ax)
        x0, x1 = ax.get_xlim()
        assert 4.0 <= x0 <= 5.0
        assert 10.0 <= x1 <= 11.0
    finally:
        plt.close(fig)


def test_the_crop_never_leaves_an_acting_cell_out() -> None:
    """A crop that hides a package answers the question with the wrong map.

    Widened on the right to hold the well, and still cropped on the left: the
    five cells before the catchment are gone. Both halves are asserted, or the
    test passes on a figure that never crops at all.
    """
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    sim = _run(
        {"well": _flux_on([19], n_cells=20)},
        mesh=_row_mesh(20),
        catchment=(5.0, 0.0, 10.0, 1.0),
    )
    fig, ax = _axes()
    try:
        BoundaryPackageMap().render(sim, ax)
        x0, x1 = ax.get_xlim()
        assert 4.0 <= x0 <= 5.0, "the background left of the catchment is not the map"
        assert x1 >= 20.0
    finally:
        plt.close(fig)


def test_the_crop_survives_a_draw_on_a_page_it_is_not_the_shape_of() -> None:
    """The crop holds only because the axes box is locked after it, not before.

    ``style_relative_km_axes`` leaves the aspect adjustable on the data
    limits, and an equal aspect satisfied that way widens the view back to the
    shape of the axes box at draw time: a 2:1 crop on a square page comes back
    as the 2:1 page-wide view the crop had just dropped, with nothing raised.
    Here the crop is 2:1 and the page is square, so a reordering shows up.
    """
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    sim = _run(
        {"drain": _flux_on([5 * 20 + 10], n_cells=400)},
        mesh=_square_mesh(20),
        catchment=(0.0, 0.0, 20.0, 10.0),
    )
    fig, ax = _axes(figsize=(4.0, 4.0))
    try:
        BoundaryPackageMap().render(sim, ax)
        fig.canvas.draw()
        assert ax.get_xlim() == pytest.approx((-0.4, 20.4))
        assert ax.get_ylim() == pytest.approx((-0.4, 10.4))
    finally:
        plt.close(fig)


def test_a_delineation_that_lands_off_the_mesh_is_not_the_frame() -> None:
    """The bounds are taken as stored, so they can be in the wrong CRS.

    A watershed that came back in degrees against a mesh in metres crops the
    map onto ground that holds no cell: an empty page, with nothing on it
    saying why. The mesh is a worse frame than the catchment and a readable
    one, so a box that misses the mesh is dropped.
    """
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    sim = _run(
        {"well": _flux_on([9], n_cells=20)},
        mesh=_row_mesh(20),
        catchment=(-1.9, 48.2, -1.5, 48.4),
    )
    fig, ax = _axes()
    try:
        BoundaryPackageMap().render(sim, ax)
        fig.canvas.draw()
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        assert x0 <= 0.0
        assert x1 >= 20.0
        assert y1 - y0 <= 2.0, "the view is 48 units of empty ground with the mesh at its foot"
    finally:
        plt.close(fig)


def test_a_run_without_a_delineation_is_drawn_whole() -> None:
    """Framing on the packages alone would zoom a one-well map onto one well."""
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    sim = _run({"well": _flux_on([9], n_cells=20)}, mesh=_row_mesh(20))
    fig, ax = _axes()
    try:
        BoundaryPackageMap().render(sim, ax)
        x0, x1 = ax.get_xlim()
        assert x0 <= 0.0
        assert x1 >= 20.0
    finally:
        plt.close(fig)


def test_every_acting_cell_carries_a_mark_and_no_other_cell_does() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    sim = _run({"drain": _flux_on([0, 3]), "stream": _flux_on([1], rate=2.0e-2)})
    fig, ax = _axes()
    try:
        BoundaryPackageMap().render(sim, ax)
        marked = _marked_cells(ax)
        assert marked[BOUNDARY_PACKAGES["drain"][1]] == [0, 3]
        assert marked[BOUNDARY_PACKAGES["stream"][1]] == [1]
        assert GROUND_COLOR not in marked, "the background is not a subject"
    finally:
        plt.close(fig)


def _full_legend_run(n_side: int) -> SimpleNamespace:
    """Return a run carrying every package, so the legend is the widest one."""
    n_cells = n_side * n_side
    return _run(
        {name: _flux_on([index], n_cells=n_cells) for index, name in enumerate(BOUNDARY_PACKAGES)},
        mesh=_square_mesh(n_side),
    )


def _page_share(fig) -> float:
    """Return the fraction of the page the map itself covers, after layout."""
    fig.canvas.draw()
    box = fig.axes[0].get_window_extent()
    page = fig.get_size_inches() * fig.dpi
    return float(box.width * box.height / (page[0] * page[1]))


@pytest.mark.parametrize(("figsize", "floor"), [((9.5, 7.5), 0.50), ((6.0, 4.5), 0.18)])
def test_the_legend_does_not_eat_the_map_it_labels(
    figsize: tuple[float, float], floor: float
) -> None:
    """The user's first complaint, on the axis the map was actually lost on.

    The legend sits outside the axes and is sized in points, so it keeps its
    width while the figure shrinks, and the axes box, locked to the aspect of
    the data, gives up both sides at once to pay for it. On this run, which
    carries every package and so the widest legend the figure can draw: at
    12.5 pt the map is 36 % of the shipped page and 10 % of a 6 x 4.5 in one;
    at 9 pt it is 63 % and 24 %. The floors sit between the two.
    """
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    fig = BoundaryPackageMap().plot(_full_legend_run(40), figsize=figsize, dpi=100)
    try:
        share = _page_share(fig)
        assert share >= floor, f"the map is {share:.1%} of the page it was given"
    finally:
        plt.close(fig)


def _one_cell_run(n_side: int) -> SimpleNamespace:
    """Return a square-mesh run one middle cell of which carries a drain."""
    return _run(
        {"drain": _flux_on([n_side * (n_side // 2) + n_side // 2], n_cells=n_side * n_side)},
        mesh=_square_mesh(n_side),
    )


def test_a_cell_finer_than_the_print_still_reaches_the_page() -> None:
    """The user's complaint, measured where it happens: on the canvas.

    A hundred and twenty cells across a page an inch and a half wide is a cell
    under one pixel. Its own footprint rounds away there, and the map is
    honest and unreadable at once: this is the map that "displays almost
    nothing". Sized in points, the class survives the print.
    """
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    n_side = 120
    fig, ax = _axes(figsize=(1.5, 1.5), dpi=100.0)
    try:
        BoundaryPackageMap().render(_one_cell_run(n_side), ax)
        cell_pixels = ax.get_window_extent().width / n_side
        assert cell_pixels < 1.0, "the case only means something below one pixel per cell"
        pixels, width, height = _painted_box(fig, ax, BOUNDARY_PACKAGES["drain"][1])
        assert pixels >= 4, "the only drain cell of the model rounded off the page"
        assert width >= 2.0
        assert height >= 2.0
    finally:
        plt.close(fig)


def test_the_mark_is_a_page_unit_and_not_a_ground_unit() -> None:
    """Doubling the page must not change the mark, or the floor is not a floor.

    A mark that scaled with the map would shrink back under a pixel on every
    figure a report lays out smaller than the gallery does, which is where the
    reader met this map in the first place.
    """
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    sim = _one_cell_run(120)
    for figsize in ((3.0, 3.0), (6.0, 6.0)):
        fig, ax = _axes(figsize=figsize, dpi=100.0)
        try:
            BoundaryPackageMap().render(sim, ax)
            _pixels, width, height = _painted_box(fig, ax, BOUNDARY_PACKAGES["drain"][1])
            expected = MARK_POINTS * fig.dpi / 72.0
            assert abs(width - expected) <= 1.0, figsize
            assert abs(height - expected) <= 1.0, figsize
        finally:
            plt.close(fig)
