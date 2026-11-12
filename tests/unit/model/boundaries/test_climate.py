"""Binding of loaded climate data (sea level in m, recharge and ETP in m/s) to a flow model."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.model.boundaries.climate import (
    apply_etp_load_result_to_flow,
    apply_oceanic_to_flow,
    apply_recharge_load_result_to_flow,
)
from hydromodpy.model.forcing.forcing_bridge import ResolvedForcing
from hydromodpy.model.sinks_sources.etp import FlowEtpConfig

START = pd.to_datetime(["2020-01-01"])


def one_station():
    return SimpleNamespace(data=pd.DataFrame({"datetime": START, "value": [1.0]}), location=None)


def loaded(point):
    return SimpleNamespace(points=[point], fields=[], has_points=True, has_fields=False)


def test_ocean_takes_a_constant_sea_level():
    ocean = SimpleNamespace(value=None)
    flow = SimpleNamespace(boundary_conditions={"ocean": ocean}, active_bc=["ocean"])
    constant = SimpleNamespace(
        variable="mean_sea_level", is_constant=True, data=pd.DataFrame({"value": [2.5]})
    )

    apply_oceanic_to_flow(flow=flow, oceanic=SimpleNamespace(points=[constant]))

    assert ocean.value == pytest.approx(2.5)


def test_ocean_takes_the_mean_of_a_tide_gauge():
    ocean = SimpleNamespace(value=None)
    flow = SimpleNamespace(boundary_conditions={"ocean": ocean}, active_bc=["ocean"])
    tide = SimpleNamespace(
        variable="sea_level", is_constant=False, data=pd.DataFrame({"value": [1.0, 3.0]})
    )

    apply_oceanic_to_flow(flow=flow, oceanic=SimpleNamespace(points=[tide]))

    assert ocean.value == pytest.approx(2.0)


def test_recharge_keeps_its_policy_in_solver_units(monkeypatch):
    captured = {}
    source = loaded(one_station())
    resolved = ResolvedForcing(
        series=pd.Series([1.2e-8], index=START),
        heterogeneous_source=source,
        spatial_mode="heterogeneous",
        interpolation_method="linear",
    )

    def fake_resolve_forcing(*args, **kwargs):
        captured.update(kwargs)
        return resolved

    monkeypatch.setattr(
        "hydromodpy.model.forcing.forcing_bridge.resolve_forcing", fake_resolve_forcing
    )
    flow = SimpleNamespace(
        sinks_sources={
            "recharge": SimpleNamespace(
                first_clim="first",
                spatial_mode="heterogeneous",
                interpolation_method="linear",
                negative_to_evt=False,
            )
        },
        set_recharge=lambda cfg: setattr(flow, "bound_recharge", cfg),
    )

    assert apply_recharge_load_result_to_flow(flow=flow, recharge_result=source)

    assert captured["spatial_mode"] == "heterogeneous"
    assert captured["interpolation_method"] == "linear"
    assert captured["unit_conversion_factor"] < 1.0
    assert flow.bound_recharge.units == "m/s"
    assert flow.bound_recharge.first_clim == "first"
    assert flow.bound_recharge.negative_to_evt is False
    assert flow.bound_recharge.heterogeneous_source is source


def test_etp_keeps_its_surface_and_depth(monkeypatch):
    source = loaded(one_station())
    resolved = ResolvedForcing(
        series=pd.Series([2.0e-8], index=START),
        heterogeneous_source=None,
        spatial_mode="homogeneous",
        interpolation_method="idw",
    )
    monkeypatch.setattr(
        "hydromodpy.model.forcing.forcing_bridge.resolve_forcing",
        lambda *args, **kwargs: resolved,
    )
    flow = SimpleNamespace(
        sinks_sources={
            "etp": FlowEtpConfig(
                first_clim="first",
                spatial_mode="homogeneous",
                interpolation_method="idw",
                surface_offset=3.0,
                extinction_depth=4.0,
            )
        },
        set_etp=lambda cfg: setattr(flow, "bound_etp", cfg),
    )

    assert apply_etp_load_result_to_flow(flow=flow, etp_result=source)

    assert flow.bound_etp.units == "m/s"
    assert flow.bound_etp.first_clim == "first"
    assert flow.bound_etp.spatial_mode == "homogeneous"
    assert float(flow.bound_etp.surface_offset.to("m").magnitude) == pytest.approx(3.0)
    assert float(flow.bound_etp.extinction_depth) == pytest.approx(4.0)
