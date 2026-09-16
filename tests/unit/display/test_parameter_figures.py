"""The parameter figures draw what the run was given, and only that.

A property left out of ``param_list`` still reaches the solver as zero. The
section must not open a colour scale around it, because a flat panel with a
ramp beside it reads as a measured uniformity rather than as an absence.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

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


class _Run:
    """A row of square cells over three layers of uniform thickness."""

    sim_id = "sim-parameter"
    name = "canut"
    n_timesteps = 1

    def __init__(self, *, with_storage: bool = True) -> None:
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

    def field(self, variable: str, timestep: int = -1, **_) -> np.ndarray:
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
