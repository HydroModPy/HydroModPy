"""Map of the boundary packages (drain, stream, well, lake) acting on each cell.

The mesh is one row of unit cells and the budget of each package (m3/s) is
written cell by cell, so the map is known before it is drawn. A drawn polygon
reads back to a cell index through its left edge. The classes are one-cell-wide
features over a large background, so their size is also measured on the
rendered canvas, in pixels.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from matplotlib.collections import PolyCollection
from matplotlib.colors import to_hex, to_rgb

from hydromodpy.display.figures.boundary_package_map import (
    BOUNDARY_PACKAGES,
    MARK_POINTS,
    SEVERAL_COLOR,
    BoundaryPackageMap,
)

N_CELLS = 4


class BudgetGroup(dict):
    """The ``budget/`` group of a store: its arrays and the attributes it declares."""

    attrs: dict


class Store:
    """The Zarr store of one run, reduced to what the figure reads off it."""

    def __init__(self, stacks: dict[str, np.ndarray], policy: str = "all") -> None:
        group = BudgetGroup(stacks)
        group.attrs = {"policy": policy, "kept_terms": sorted(stacks) if policy == "all" else []}
        self.root = {"budget": group}

    def close(self) -> None:
        pass


def row_mesh(n_cells: int) -> tuple[np.ndarray, np.ndarray]:
    """Vertices and faces of one row of ``n_cells`` unit cells."""
    vertices = np.asarray(
        [[x, y, 0.0] for y in (0.0, 1.0) for x in range(n_cells + 1)], dtype=float
    )
    faces = np.asarray(
        [[i, i + 1, n_cells + 2 + i, n_cells + 1 + i] for i in range(n_cells)], dtype=int
    )
    return vertices, faces


def square_mesh(n_side: int) -> tuple[np.ndarray, np.ndarray]:
    """Vertices and faces of an ``n_side`` by ``n_side`` grid, cell = row * n_side + column."""
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


def package_run(
    budgets: dict[str, np.ndarray],
    *,
    n_timesteps: int = 1,
    mesh: tuple[np.ndarray, np.ndarray] | None = None,
    catchment: tuple[float, float, float, float] | None = None,
    policy: str = "all",
) -> SimpleNamespace:
    """A run whose ``budgets`` are ``(n_timesteps, ...)`` arrays per package.

    ``policy`` is what its ``budget/`` group declares it kept, ``"all"`` or
    ``"consumers"`` with no term kept. ``catchment`` is the (x0, y0, x1, y1) of
    the delineation.
    """
    vertices, faces = mesh if mesh is not None else row_mesh(N_CELLS)
    stacks = {name: np.asarray(values, dtype=float) for name, values in budgets.items()}
    opened: list[Store] = []

    def open_zarr(_sim_id):
        opened.append(Store(stacks, policy))
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
        field=lambda variable, time=-1, **_: stacks[variable][time],
        geographic=geographic,
        opened_stores=opened,
        _catalog=SimpleNamespace(open_zarr=open_zarr),
    )


def flux_on(cells, *, n_timesteps: int = 1, rate: float = -1.5e-3, n_cells: int = N_CELLS):
    """A one-package budget stack carrying ``rate`` (m3/s) on ``cells``."""
    stack = np.zeros((n_timesteps, n_cells), dtype=float)
    stack[:, list(cells)] = rate
    return stack


def idle_after_first_step(cells, *, n_timesteps: int = 3):
    """A package that acts on ``cells`` at the first step only."""
    stack = np.zeros((n_timesteps, N_CELLS), dtype=float)
    stack[0, list(cells)] = -4.0e-4
    return stack


def cells_by_color(ax) -> dict[str, list[int]]:
    """The cells each class covers, read from the polygon collections."""
    painted: dict[str, list[int]] = {}
    for collection in ax.collections:
        if isinstance(collection, PolyCollection):
            color = to_hex(collection.get_facecolor()[0]).upper()
            painted[color] = sorted(
                int(round(path.vertices[:, 0].min())) for path in collection.get_paths()
            )
    return painted


def painted_box(fig, ax, color: str, tolerance: float = 0.12) -> tuple[float, float]:
    """Width and height in pixels of the ``color`` pixels inside the map axes.

    Only the map is read, never the margins, since the legend swatch of a class
    has the very color being looked for.
    """
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
        return 0.0, 0.0
    return float(cols.max() - cols.min() + 1), float(rows.max() - rows.min() + 1)


def test_shared_cell_class(mpl) -> None:
    # No package wins an overlap: the cell leaves both and says it is shared.
    run = package_run({"drain": flux_on([0, 1]), "stream": flux_on([1, 2])})
    _, ax = mpl.subplots()

    BoundaryPackageMap().render(run, ax)

    painted = cells_by_color(ax)
    assert painted[SEVERAL_COLOR] == [1]
    assert painted[BOUNDARY_PACKAGES["drain"][1]] == [0]
    assert painted[BOUNDARY_PACKAGES["stream"][1]] == [2]
    assert "several packages (1 cell)" in [t.get_text() for t in ax.get_legend().get_texts()]


def test_over_step_reads_one_step(mpl) -> None:
    run = package_run({"drain": idle_after_first_step([0, 2])}, n_timesteps=3)
    _, ax = mpl.subplots()

    BoundaryPackageMap().render(run, ax, over="step", timestep=0)

    assert cells_by_color(ax)[BOUNDARY_PACKAGES["drain"][1]] == [0, 2]
    assert run.opened_stores == [], "a single step is read without opening the store"


def test_layered_budget_collapses(mpl) -> None:
    # A WEL rate on any layer puts the package on that cell, once.
    well = np.zeros((1, 3, N_CELLS), dtype=float)
    well[0, 2, 1] = -8.0e-3
    _, ax = mpl.subplots()

    BoundaryPackageMap().render(package_run({"well": well}), ax)

    assert cells_by_color(ax)[BOUNDARY_PACKAGES["well"][1]] == [1]


def test_no_package_offers_no_option() -> None:
    # The model produced no package, so no setting would have stored one.
    reason = BoundaryPackageMap().unavailable_reason(package_run({"head": np.zeros((1, N_CELLS))}))

    assert isinstance(reason, str)
    assert "keep_per_cell_budget" not in reason


def test_one_stored_package_is_enough() -> None:
    assert BoundaryPackageMap().unavailable_reason(package_run({"lake": flux_on([0])})) is None


def test_render_raises_reported_reason(mpl) -> None:
    run = package_run({"head": np.zeros((1, N_CELLS))}, policy="consumers")
    figure = BoundaryPackageMap()
    _, ax = mpl.subplots()

    with pytest.raises(ValueError) as excinfo:
        figure.render(run, ax)

    assert str(excinfo.value) == figure.unavailable_reason(run)


def test_packages_are_budget_fields() -> None:
    from hydromodpy.core.budget.terms import budget_terms_for
    from hydromodpy.results.field_registry import get

    for name in BOUNDARY_PACKAGES:
        descriptor = get(name)
        assert descriptor.zarr_path == f"budget/{name}"
        assert descriptor.units == "m3 s-1"
        assert budget_terms_for(name)


def test_planner_keeps_package_terms() -> None:
    # Without this a run that keeps only what its consumers read drops the
    # per-cell budget, and the map is reported unavailable on its own output.
    from hydromodpy.core.budget.terms import budget_terms_for_fields
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.solver.base.results_config import ResultsConfig
    from hydromodpy.workflow.steps.planning import step_configure_results

    keep = step_configure_results(
        ResultsConfig(keep_per_cell_budget=False),
        SimpleNamespace(runs=()),
        DisplayConfig(figures=["boundary_package_map"]),
        display_active=True,
        export_requests=(),
        calibration=None,
        observation=None,
    )

    assert keep.terms == frozenset(budget_terms_for_fields(BOUNDARY_PACKAGES))


def test_no_package_is_required() -> None:
    # Required would report the figure unavailable on a run carrying one package.
    spec = BoundaryPackageMap().spec

    assert spec.required_fields == ()
    assert spec.optional_fields == tuple(BOUNDARY_PACKAGES)


def test_view_is_the_catchment(mpl) -> None:
    # Half the mesh of the reference run is outside the basin. Spending it on
    # background makes a 1 % class unreadable.
    run = package_run(
        {"drain": flux_on([6, 7], n_cells=20)},
        mesh=row_mesh(20),
        catchment=(5.0, 0.0, 10.0, 1.0),
    )
    _, ax = mpl.subplots()

    BoundaryPackageMap().render(run, ax)

    x0, x1 = ax.get_xlim()
    assert 4.0 <= x0 <= 5.0
    assert 10.0 <= x1 <= 11.0


def test_crop_survives_other_page_shape(mpl) -> None:
    # style_relative_km_axes leaves the aspect adjustable on the data limits. A
    # 2:1 crop on a square page would widen back to the page shape at draw time
    # unless the axes box is locked after the crop.
    run = package_run(
        {"drain": flux_on([5 * 20 + 10], n_cells=400)},
        mesh=square_mesh(20),
        catchment=(0.0, 0.0, 20.0, 10.0),
    )
    fig, ax = mpl.subplots(figsize=(4.0, 4.0))

    BoundaryPackageMap().render(run, ax)
    fig.canvas.draw()

    assert ax.get_xlim() == pytest.approx((-0.4, 20.4))
    assert ax.get_ylim() == pytest.approx((-0.4, 10.4))


@pytest.mark.parametrize("figsize", [(3.0, 3.0), (6.0, 6.0)], ids=["small page", "doubled page"])
def test_mark_is_a_page_unit(mpl, figsize) -> None:
    # One drain cell on a 120 x 120 mesh. The mark must not scale with the map,
    # or it shrinks under a pixel on reports laid out smaller than the gallery.
    n_side = 120
    run = package_run(
        {"drain": flux_on([n_side * (n_side // 2) + n_side // 2], n_cells=n_side * n_side)},
        mesh=square_mesh(n_side),
    )
    fig, ax = mpl.subplots(figsize=figsize, dpi=100.0)

    BoundaryPackageMap().render(run, ax)

    width, height = painted_box(fig, ax, BOUNDARY_PACKAGES["drain"][1])
    expected = MARK_POINTS * fig.dpi / 72.0
    assert abs(width - expected) <= 1.0
    assert abs(height - expected) <= 1.0


REFUSALS = [
    pytest.param({"drain": flux_on([0])}, {"over": "year"}, "'run' or 'step'", id="unknown extent"),
    pytest.param(
        {"drain": np.zeros((1, N_CELLS + 1))},
        {},
        "'drain' budget holds 5 values",
        id="budget not fitting the mesh",
    ),
]


@pytest.mark.parametrize(("budgets", "kwargs", "message"), REFUSALS)
def test_refusals(mpl, budgets, kwargs, message) -> None:
    _, ax = mpl.subplots()

    with pytest.raises(ValueError, match=message):
        BoundaryPackageMap().render(package_run(budgets), ax, **kwargs)
