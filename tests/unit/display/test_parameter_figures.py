"""The parameter figures draw what the run was given, and only that.

A property left out of ``param_list`` still reaches the solver as zero. The
section must not open a colour scale around it, because a flat panel with a
ramp beside it reads as a measured uniformity rather than as an absence.

The K tensor fields (K22, K33 and the three angles) are drawn like the other
properties. The conductivities share one log scale, so a K33 a decade under K
is a darker panel and not a second copy of the K panel.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.display.figure import FigureNotApplicable
from hydromodpy.display.figures.parameter_map import ParameterMap
from hydromodpy.display.figures.parameter_section import (
    ParameterSection,
    _quad_edges,
    _resolve_variables,
)

N_CELLS = 4
N_LAYERS = 3

K_PER_LAYER = (1.0e-4, 1.0e-5, 1.0e-6)
"""Conductivity decaying by a decade per layer: two decades, so a log ramp."""

SY_VALUE = 0.05
"""One uniform specific yield: no decade to span, so a linear ramp."""

K22 = "hydraulic_conductivity_k22"
K33 = "hydraulic_conductivity_k33"
ANGLE1 = "conductivity_tensor_angle1"
ANGLE2 = "conductivity_tensor_angle2"
ANGLE3 = "conductivity_tensor_angle3"

ANGLE1_STORED = (-90.0, 0.0, 90.0, 180.0)
"""A turn read from east towards north, stored with the sign the user wrote."""

ANGLE2_PER_LAYER = (0.0, 10.0, 20.0)


class _Run:
    """A row of square cells over three layers of uniform thickness."""

    sim_id = "sim-parameter"
    name = "canut"
    n_timesteps = 1

    def __init__(self, *, with_storage: bool = True, with_tensor: bool = False) -> None:
        top = np.full(N_CELLS, 100.0)
        self._fields = {
            "topography": top,
            "layer_thickness": np.full((N_LAYERS, N_CELLS), 10.0),
            "hydraulic_conductivity": np.repeat(np.asarray(K_PER_LAYER)[:, None], N_CELLS, axis=1),
            "specific_yield": np.full((N_LAYERS, N_CELLS), SY_VALUE),
            "specific_storage": np.zeros((N_LAYERS, N_CELLS)),
        }
        if not with_storage:
            del self._fields["specific_yield"]
            del self._fields["specific_storage"]
        if with_tensor:
            k = self._fields["hydraulic_conductivity"]
            self._fields[K22] = k / 2.0
            self._fields[K33] = k / 10.0
            self._fields[ANGLE1] = np.tile(np.asarray(ANGLE1_STORED), (N_LAYERS, 1))
            self._fields[ANGLE2] = np.repeat(np.asarray(ANGLE2_PER_LAYER)[:, None], N_CELLS, axis=1)
            self._fields[ANGLE3] = np.zeros((N_LAYERS, N_CELLS))
        self.mesh = SimpleNamespace(
            vertices=np.asarray(
                [[float(x), y, 0.0] for y in (0.0, 1.0) for x in range(N_CELLS + 1)]
            ),
            face_node_connectivity=np.asarray(
                [[i, i + 1, N_CELLS + 2 + i, N_CELLS + 1 + i] for i in range(N_CELLS)]
            ),
        )
        self.outlet = (2.0, 0.5)

    def has_field(self, variable: str, **_) -> bool:
        return variable in self._fields

    def field(self, variable: str, time: int = -1, **_) -> np.ndarray:
        return self._fields[variable]


def _axes():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt.subplots()[1]


def test_a_property_the_run_left_at_zero_is_not_given_a_panel() -> None:
    assert _resolve_variables(_Run(), None) == ["hydraulic_conductivity", "specific_yield"]


def test_asking_for_that_property_by_name_still_draws_it() -> None:
    assert _resolve_variables(_Run(), ["specific_storage"]) == ["specific_storage"]


def test_a_run_carrying_no_property_at_all_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="is set in this run"):
        _resolve_variables(_Run(with_storage=False), ["specific_yield"])


def test_the_quad_corners_bound_every_sample_and_every_layer() -> None:
    distance = np.asarray([0.5, 1.5, 2.5, 3.5])
    interfaces = np.vstack([np.full(N_CELLS, 100.0 - 10.0 * k) for k in range(N_LAYERS + 1)])
    x_edges, y_edges = _quad_edges(distance, interfaces)
    assert x_edges.shape == (N_LAYERS + 1, N_CELLS + 1)
    assert y_edges.shape == (N_LAYERS + 1, N_CELLS + 1)
    assert x_edges[0, 0] == pytest.approx(0.0)
    assert x_edges[0, -1] == pytest.approx(4.0)
    assert y_edges[0, 0] == pytest.approx(100.0)
    assert y_edges[-1, 0] == pytest.approx(70.0)


def test_the_section_gives_each_layer_the_value_that_layer_was_given() -> None:
    ax = _axes()
    ParameterSection().render(_Run(), ax)
    drawn = np.asarray(ax.collections[0].get_array())
    assert drawn.shape[0] == N_LAYERS
    for layer, expected in enumerate(K_PER_LAYER):
        row = drawn[layer]
        assert np.nanmax(row) == pytest.approx(expected)
        assert np.nanmin(row) == pytest.approx(expected)


def test_a_property_spanning_decades_is_drawn_on_a_log_ramp() -> None:
    ax = _axes()
    ParameterSection().render(_Run(), ax, variable="hydraulic_conductivity")
    assert type(ax.collections[0].norm).__name__ == "LogNorm"


def test_a_uniform_property_gets_its_value_in_the_title_and_no_ramp() -> None:
    ax = _axes()
    ParameterSection().render(_Run(), ax, variable="specific_yield")
    assert type(ax.collections[0].norm).__name__ != "LogNorm"
    assert "uniform" in ax.get_title()
    assert f"{SY_VALUE:.3g}" in ax.get_title()
    assert ax.figure.axes == [ax]


def test_the_map_draws_the_layer_it_was_asked_for() -> None:
    ax = _axes()
    ParameterMap().render(_Run(), ax, layer=2, overlays=())
    drawn = np.asarray(ax.collections[0].get_array())
    assert drawn == pytest.approx(np.full(N_CELLS, K_PER_LAYER[2]))


def test_the_map_refuses_a_layer_the_mesh_does_not_have() -> None:
    with pytest.raises(ValueError, match="outside the 3 layer"):
        ParameterMap().render(_Run(), _axes(), layer=9, overlays=())


def test_the_map_refuses_a_variable_that_is_not_an_aquifer_property() -> None:
    with pytest.raises(ValueError, match="not an aquifer property"):
        ParameterMap().render(_Run(), _axes(), variable="head", overlays=())


def _panel_norms(fig, count: int) -> list:
    """The colour scale of the first ``count`` panels, before their colour bars."""
    return [ax.collections[0].norm for ax in fig.axes[:count]]


def test_a_default_section_adds_the_tensor_fields_the_run_set() -> None:
    assert _resolve_variables(_Run(with_tensor=True), None) == [
        "hydraulic_conductivity",
        K22,
        K33,
        "specific_yield",
        ANGLE1,
        ANGLE2,
    ]


def test_a_k33_equal_to_k_is_not_drawn_unless_it_is_asked_for() -> None:
    run = _Run(with_tensor=True)
    run._fields[K33] = run._fields["hydraulic_conductivity"].copy()
    assert K33 not in _resolve_variables(run, None)
    assert _resolve_variables(run, [K33]) == [K33]


def test_the_three_conductivities_share_one_log_scale() -> None:
    fig = ParameterSection().plot(
        _Run(with_tensor=True), variables=["hydraulic_conductivity", K22, K33]
    )
    norms = _panel_norms(fig, 3)
    assert {type(norm).__name__ for norm in norms} == {"LogNorm"}
    for norm in norms:
        assert norm.vmin == pytest.approx(K_PER_LAYER[2] / 10.0)
        assert norm.vmax == pytest.approx(K_PER_LAYER[0])


def test_a_conductivity_keeps_its_own_range_beside_a_storage_panel() -> None:
    fig = ParameterSection().plot(_Run(with_tensor=True), variables=[K33, "specific_yield"])
    k33_norm, sy_norm = _panel_norms(fig, 2)
    assert type(k33_norm).__name__ == "LogNorm"
    assert k33_norm.vmin == pytest.approx(K_PER_LAYER[2] / 10.0)
    assert type(sy_norm).__name__ != "LogNorm"


def test_the_map_draws_k33_on_a_log_scale_with_its_own_values() -> None:
    ax = _axes()
    run = _Run(with_tensor=True)
    across = np.logspace(-4.0, -7.0, N_CELLS)
    run._fields[K33] = np.tile(across, (N_LAYERS, 1))
    ParameterMap().render(run, ax, variable=K33, layer=1, overlays=())
    collection = ax.collections[0]
    assert type(collection.norm).__name__ == "LogNorm"
    assert np.asarray(collection.get_array()) == pytest.approx(across)
    assert "K33" in ax.get_title()
    assert "(m s-1)" in ax.figure.axes[1].get_ylabel()


@pytest.mark.parametrize("figure", ["map", "section"])
def test_the_first_angle_is_a_turn_on_a_cyclic_scale_said_in_its_label(figure: str) -> None:
    ax = _axes()
    run = _Run(with_tensor=True)
    if figure == "map":
        ParameterMap().render(run, ax, variable=ANGLE1, layer=0, overlays=())
    else:
        ParameterSection().render(run, ax, variable=ANGLE1)
    collection = ax.collections[0]
    assert collection.cmap.name == "twilight"
    assert type(collection.norm).__name__ == "Normalize"
    assert (collection.norm.vmin, collection.norm.vmax) == (0.0, 360.0)
    drawn = np.asarray(collection.get_array()).ravel()
    assert set(np.round(drawn[np.isfinite(drawn)], 6)) == {a % 360.0 for a in ANGLE1_STORED}
    colorbar = ax.figure.axes[1]
    assert "from east towards north" in colorbar.get_ylabel()
    assert "(degree)" in colorbar.get_ylabel()
    assert list(colorbar.get_yticks()) == [0.0, 90.0, 180.0, 270.0, 360.0]


@pytest.mark.parametrize("force", [None, True])
def test_the_second_angle_is_linear_in_degrees_even_when_a_log_is_forced(force) -> None:
    ax = _axes()
    ParameterSection().render(_Run(with_tensor=True), ax, variable=ANGLE2, log=force)
    collection = ax.collections[0]
    assert type(collection.norm).__name__ == "Normalize"
    assert collection.cmap.name == "viridis"
    assert np.nanmax(np.asarray(collection.get_array())) == pytest.approx(max(ANGLE2_PER_LAYER))
    label = ax.figure.axes[1].get_ylabel()
    assert "above the horizontal" in label
    assert "(degree)" in label


def test_an_explicit_colormap_wins_over_the_cyclic_one() -> None:
    ax = _axes()
    ParameterMap().render(
        _Run(with_tensor=True), ax, variable=ANGLE1, layer=0, cmap="cividis", overlays=()
    )
    assert ax.collections[0].cmap.name == "cividis"


@pytest.mark.parametrize("variable", [K22, K33, ANGLE1, ANGLE2, ANGLE3])
def test_a_field_the_run_does_not_hold_is_said_not_drawn(variable: str) -> None:
    import matplotlib.pyplot as plt

    run = _Run()
    before = plt.get_fignums()
    with pytest.raises(FigureNotApplicable, match=f"{variable!r} is not in this run"):
        ParameterMap().render(run, _axes(), variable=variable, overlays=())
    with pytest.raises(FigureNotApplicable, match=f"{variable!r} is not in this run"):
        ParameterSection().render(run, _axes(), variable=variable)
    with pytest.raises(FigureNotApplicable, match=f"{variable!r} is not in this run"):
        ParameterSection().plot(run, variables=["hydraulic_conductivity", variable])
    assert len(plt.get_fignums()) == len(before) + 2
    plt.close("all")


def test_a_batch_skips_a_map_of_a_tensor_field_the_run_lacks(tmp_path) -> None:
    import hydromodpy.display.runs as runs
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.results.storage.contract import RUN_FIGURES_DIRNAME

    config = DisplayConfig.model_construct(
        enabled=True,
        save=True,
        dpi=50,
        preset="default",
        backend="auto",
        show=False,
        on_error="raise",
        cmap="viridis",
        overrides={"parameter_map": {"variable": K22, "overlays": ()}},
        output_dir=RUN_FIGURES_DIRNAME,
        figures=["parameter_map"],
    )
    report = runs.render_figures_for_run(_Run(), config, output_dir=tmp_path)
    assert report.rendered == ()
    assert [skipped.name for skipped in report.skipped] == ["parameter_map"]
    assert f"{K22!r} is not in this run" in report.skipped[0].reason


def test_the_section_refuses_a_variable_that_is_not_an_aquifer_property() -> None:
    with pytest.raises(ValueError, match="not an aquifer property"):
        ParameterSection().plot(_Run(), variables=["head"])
