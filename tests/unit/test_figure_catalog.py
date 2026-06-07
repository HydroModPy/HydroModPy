"""Unit tests for the figure registry and Figure protocol."""

from __future__ import annotations

import pytest

from hydromodpy.display import (
    BaseFigure,
    Figure,
    FigureSpec,
    get,
    list_figures,
    names,
)

EXPECTED_FIGURES = {
    "concentration_map",
    "cross_section",
    "difference_map",
    "hydrograph",
    "hydrographic_network_comparison",
    "hydrographic_network_generated_extra_only",
    "hydrographic_network_generated",
    "hydrographic_network_reference_missing_only",
    "hydrographic_network_reference",
    "particle_tracks",
    "piezometric_map",
    "recharge_map",
    "seepage_map",
    "simulated_active_network",
    "simulated_active_network_reference_overlay",
    "water_budget",
}


def test_all_expected_figures_registered():
    assert EXPECTED_FIGURES.issubset(set(names()))


def test_list_figures_returns_specs():
    specs = list_figures()
    assert len(specs) >= len(EXPECTED_FIGURES)
    for spec in specs:
        assert isinstance(spec, FigureSpec)
        assert spec.name == spec.name.lower()


def test_get_returns_protocol_compatible_instance():
    fig = get("piezometric_map")
    assert isinstance(fig, BaseFigure)
    assert isinstance(fig, Figure)
    assert fig.spec.name == "piezometric_map"


def test_get_unknown_name_raises():
    with pytest.raises(KeyError):
        get("not_a_real_figure")


def test_every_figure_has_render_method():
    for spec in list_figures():
        fig = get(spec.name)
        assert callable(getattr(fig, "render", None))
        assert callable(getattr(fig, "plot", None))


def test_spec_kind_is_valid():
    valid = {
        "spatial",
        "section",
        "timeseries",
        "balance",
        "particles",
        "table",
        "comparison",
        "animation",
    }
    for spec in list_figures():
        assert spec.kind in valid


def test_get_returns_fresh_instances():
    a = get("hydrograph")
    b = get("hydrograph")
    assert a is not b
