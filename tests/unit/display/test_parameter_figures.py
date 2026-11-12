"""Parameter map and section: aquifer properties (K in m/s, Sy, angles in degrees) per layer.

A run is a row of four square cells over three layers 10 m thick. The figures
draw only what the run was given. K is shared on one log scale with K22 and K33,
and the tensor angles use their own linear or cyclic scale.
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
# One decade lost per layer, two decades in all, so a log ramp.
K_PER_LAYER = (1.0e-4, 1.0e-5, 1.0e-6)
# One uniform value, no decade to span, so a linear ramp.
SY_VALUE = 0.05

K22 = "hydraulic_conductivity_k22"
K33 = "hydraulic_conductivity_k33"
ANGLE1 = "conductivity_tensor_angle1"
ANGLE2 = "conductivity_tensor_angle2"
ANGLE3 = "conductivity_tensor_angle3"
# A turn read from east towards north, stored with the sign the user wrote.
ANGLE1_STORED = (-90.0, 0.0, 90.0, 180.0)
ANGLE2_PER_LAYER = (0.0, 10.0, 20.0)


class Run:
    """A row of square cells over three layers of uniform thickness."""

    sim_id = "sim-parameter"
    name = "canut"
    n_timesteps = 1

    def __init__(self, *, with_storage: bool = True, with_tensor: bool = False) -> None:
        self._fields = {
            "topography": np.full(N_CELLS, 100.0),
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


def norm_name(artist) -> str:
    return type(artist.norm).__name__


def panel_norms(fig, count: int) -> list:
    """The color scale of the first ``count`` panels, before their color bars."""
    return [ax.collections[0].norm for ax in fig.axes[:count]]


def test_quad_corners() -> None:
    distance = np.asarray([0.5, 1.5, 2.5, 3.5])
    interfaces = np.vstack([np.full(N_CELLS, 100.0 - 10.0 * k) for k in range(N_LAYERS + 1)])

    x_edges, y_edges = _quad_edges(distance, interfaces)

    assert x_edges.shape == (N_LAYERS + 1, N_CELLS + 1)
    assert y_edges.shape == (N_LAYERS + 1, N_CELLS + 1)
    assert x_edges[0, 0] == pytest.approx(0.0)
    assert x_edges[0, -1] == pytest.approx(4.0)
    assert y_edges[0, 0] == pytest.approx(100.0)
    assert y_edges[-1, 0] == pytest.approx(70.0)


def test_section_layer_values(mpl) -> None:
    ax = mpl.subplots()[1]

    ParameterSection().render(Run(), ax)

    drawn = np.asarray(ax.collections[0].get_array())
    assert drawn.shape[0] == N_LAYERS
    for layer, expected in enumerate(K_PER_LAYER):
        assert np.nanmax(drawn[layer]) == pytest.approx(expected)
        assert np.nanmin(drawn[layer]) == pytest.approx(expected)


def test_uniform_property_in_title(mpl) -> None:
    ax = mpl.subplots()[1]

    ParameterSection().render(Run(), ax, variable="specific_yield")

    assert norm_name(ax.collections[0]) != "LogNorm"
    assert "uniform" in ax.get_title()
    assert f"{SY_VALUE:.3g}" in ax.get_title()
    assert ax.figure.axes == [ax]


def test_map_layer(mpl) -> None:
    ax = mpl.subplots()[1]

    ParameterMap().render(Run(), ax, layer=2, overlays=())

    drawn = np.asarray(ax.collections[0].get_array())
    assert drawn == pytest.approx(np.full(N_CELLS, K_PER_LAYER[2]))


def test_default_section_variables() -> None:
    assert _resolve_variables(Run(with_tensor=True), None) == [
        "hydraulic_conductivity",
        K22,
        K33,
        "specific_yield",
        ANGLE1,
        ANGLE2,
    ]


def test_k33_equal_to_k() -> None:
    run = Run(with_tensor=True)
    run._fields[K33] = run._fields["hydraulic_conductivity"].copy()

    assert K33 not in _resolve_variables(run, None)
    assert _resolve_variables(run, [K33]) == [K33]


def test_three_conductivities_share_one_log_scale(mpl) -> None:
    fig = ParameterSection().plot(
        Run(with_tensor=True), variables=["hydraulic_conductivity", K22, K33]
    )

    norms = panel_norms(fig, 3)

    assert {type(norm).__name__ for norm in norms} == {"LogNorm"}
    for norm in norms:
        assert norm.vmin == pytest.approx(K_PER_LAYER[2] / 10.0)
        assert norm.vmax == pytest.approx(K_PER_LAYER[0])


def test_conductivity_range_beside_storage(mpl) -> None:
    fig = ParameterSection().plot(Run(with_tensor=True), variables=[K33, "specific_yield"])

    k33_norm, sy_norm = panel_norms(fig, 2)

    assert type(k33_norm).__name__ == "LogNorm"
    assert k33_norm.vmin == pytest.approx(K_PER_LAYER[2] / 10.0)
    assert type(sy_norm).__name__ != "LogNorm"


def test_map_draws_k33_on_a_log_scale(mpl) -> None:
    ax = mpl.subplots()[1]
    run = Run(with_tensor=True)
    across = np.logspace(-4.0, -7.0, N_CELLS)
    run._fields[K33] = np.tile(across, (N_LAYERS, 1))

    ParameterMap().render(run, ax, variable=K33, layer=1, overlays=())

    collection = ax.collections[0]
    assert norm_name(collection) == "LogNorm"
    assert np.asarray(collection.get_array()) == pytest.approx(across)
    assert "K33" in ax.get_title()
    assert "(m s-1)" in ax.figure.axes[1].get_ylabel()


@pytest.mark.parametrize(
    ("figure", "kwargs"),
    [
        pytest.param(ParameterMap, {"layer": 0, "overlays": ()}, id="map"),
        pytest.param(ParameterSection, {}, id="section"),
    ],
)
def test_first_angle_cyclic_scale(mpl, figure, kwargs) -> None:
    ax = mpl.subplots()[1]

    figure().render(Run(with_tensor=True), ax, variable=ANGLE1, **kwargs)

    collection = ax.collections[0]
    assert collection.cmap.name == "twilight"
    assert norm_name(collection) == "Normalize"
    assert (collection.norm.vmin, collection.norm.vmax) == (0.0, 360.0)
    drawn = np.asarray(collection.get_array()).ravel()
    assert set(np.round(drawn[np.isfinite(drawn)], 6)) == {a % 360.0 for a in ANGLE1_STORED}
    colorbar = ax.figure.axes[1]
    assert "from east towards north" in colorbar.get_ylabel()
    assert "(degree)" in colorbar.get_ylabel()
    assert list(colorbar.get_yticks()) == [0.0, 90.0, 180.0, 270.0, 360.0]


@pytest.mark.parametrize("force_log", [None, True])
def test_second_angle_linear(mpl, force_log) -> None:
    ax = mpl.subplots()[1]

    ParameterSection().render(Run(with_tensor=True), ax, variable=ANGLE2, log=force_log)

    collection = ax.collections[0]
    assert norm_name(collection) == "Normalize"
    assert collection.cmap.name == "viridis"
    assert np.nanmax(np.asarray(collection.get_array())) == pytest.approx(max(ANGLE2_PER_LAYER))
    label = ax.figure.axes[1].get_ylabel()
    assert "above the horizontal" in label
    assert "(degree)" in label


def test_explicit_colormap_wins(mpl) -> None:
    ax = mpl.subplots()[1]

    ParameterMap().render(
        Run(with_tensor=True), ax, variable=ANGLE1, layer=0, cmap="cividis", overlays=()
    )

    assert ax.collections[0].cmap.name == "cividis"


@pytest.mark.parametrize("variable", [K22, K33, ANGLE1, ANGLE2, ANGLE3])
def test_missing_field_not_drawn(mpl, variable) -> None:
    run = Run()
    message = f"{variable!r} is not in this run"
    before = len(mpl.get_fignums())

    with pytest.raises(FigureNotApplicable, match=message):
        ParameterMap().render(run, mpl.subplots()[1], variable=variable, overlays=())
    with pytest.raises(FigureNotApplicable, match=message):
        ParameterSection().render(run, mpl.subplots()[1], variable=variable)
    with pytest.raises(FigureNotApplicable, match=message):
        ParameterSection().plot(run, variables=["hydraulic_conductivity", variable])

    # Only the two figures the test opened itself stay open.
    assert len(mpl.get_fignums()) == before + 2


def test_batch_skips_missing_tensor(tmp_path) -> None:
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

    report = runs.render_figures_for_run(Run(), config, output_dir=tmp_path)

    assert report.rendered == ()
    assert [skipped.name for skipped in report.skipped] == ["parameter_map"]
    assert f"{K22!r} is not in this run" in report.skipped[0].reason


# Each row is the keywords of ParameterMap.render and the start of the message.
MAP_REFUSALS = [
    pytest.param({"layer": 9}, "outside the 3 layer", id="layer the mesh lacks"),
    pytest.param({"variable": "head"}, "not an aquifer property", id="not an aquifer property"),
]


@pytest.mark.parametrize(("kwargs", "message"), MAP_REFUSALS)
def test_map_refusals(mpl, kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        ParameterMap().render(Run(), mpl.subplots()[1], overlays=(), **kwargs)


def test_section_refuses_non_property() -> None:
    with pytest.raises(ValueError, match="not an aquifer property"):
        ParameterSection().plot(Run(), variables=["head"])


def test_run_without_property_refused() -> None:
    with pytest.raises(ValueError, match="is set in this run"):
        _resolve_variables(Run(with_storage=False), ["specific_yield"])
