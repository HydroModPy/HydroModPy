"""Which cell the boundary-package map attributes to which package.

The mesh is one row of unit cells and the budget of each package is written
here cell by cell, so the map the figure draws is known before it is drawn.
Reading a drawn collection back to a cell index only needs the left edge of
its polygons, which is the cell index itself.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.display.figures.boundary_package_map import (
    BOUNDARY_PACKAGES,
    GROUND_COLOR,
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


def _run(budgets: dict[str, np.ndarray], *, n_timesteps: int = 1) -> SimpleNamespace:
    """Return a run whose ``budgets`` are ``(n_timesteps, ...)`` per component."""
    vertices = np.asarray(
        [[x, y, 0.0] for y in (0.0, 1.0) for x in range(N_CELLS + 1)],
        dtype=float,
    )
    faces = np.asarray(
        [[i, i + 1, N_CELLS + 2 + i, N_CELLS + 1 + i] for i in range(N_CELLS)],
        dtype=int,
    )
    stacks = {name: np.asarray(values, dtype=float) for name, values in budgets.items()}
    opened: list[_Store] = []

    def open_zarr(_sim_id):
        opened.append(_Store(stacks))
        return opened[-1]

    return SimpleNamespace(
        sim_id="sim-boundary",
        name="nancon",
        n_timesteps=n_timesteps,
        mesh=SimpleNamespace(vertices=vertices, face_node_connectivity=faces),
        has_field=lambda variable, **_: variable in stacks,
        field=lambda variable, timestep=-1, **_: stacks[variable][timestep],
        opened_stores=opened,
        _catalog=SimpleNamespace(open_zarr=open_zarr),
    )


def _flux_on(cells, *, n_timesteps: int = 1, rate: float = -1.5e-3) -> np.ndarray:
    """Return a one-component budget stack carrying ``rate`` on ``cells``."""
    stack = np.zeros((n_timesteps, N_CELLS), dtype=float)
    stack[:, list(cells)] = rate
    return stack


def _idle_after_first_step(cells, *, n_timesteps: int = 3) -> np.ndarray:
    """Return a component that acts on ``cells`` at the first step only."""
    stack = np.zeros((n_timesteps, N_CELLS), dtype=float)
    stack[0, list(cells)] = -4.0e-4
    return stack


def _axes():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt.subplots()


def _cells_by_color(ax) -> dict[str, list[int]]:
    """Return the cells each flat colour covers, keyed by its hex code."""
    from matplotlib.colors import to_hex

    painted: dict[str, list[int]] = {}
    for collection in ax.collections:
        color = to_hex(collection.get_facecolor()[0]).upper()
        cells = [int(round(path.vertices[:, 0].min())) for path in collection.get_paths()]
        painted[color] = sorted(cells)
    return painted


def _labels(ax) -> list[str]:
    return [text.get_text() for text in ax.get_legend().get_texts()]


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
        assert any("any of the 3 persisted steps" in text.get_text() for text in ax.texts)
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
        assert any("at step 3" in text.get_text() for text in ax.texts)
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
