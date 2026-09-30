"""A phase override that shortens the window below a year is caught.

``spinup_refusal`` is checked at load time (config layer), but a calibration
phase can shorten ``[simulation.time]`` after loading
(``calibration/runners/phase_regime.py``, ``regime_overrides``). The binder
repeats the same guard, with the same text, so a run that repeats the first
year on a window under 365 days is refused at run time too, before
``compute_soil_forcings`` ever runs.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.data import LoadedDataContext
from hydromodpy.core.state.setup import SetupContext
from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.physics.hydrology.soil_reservoir.config import (
    SoilReservoirConfig,
    spinup_refusal,
)
from hydromodpy.workflow.steps.data import apply_structural_updates_from_data


def _short_window() -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2015-01-01"),
        end=pd.Timestamp("2015-01-10"),
        step_value=1,
        step_unit="day",
        coverage_policy="ignore",
    )


def _run_state(*, with_soil: bool) -> SimpleNamespace:
    soil = SoilReservoirConfig(ru=150.0) if with_soil else None
    flow_cfg = SimpleNamespace(
        sinks_sources=SimpleNamespace(recharge=SimpleNamespace(soil=soil)),
        flow_regime="transient",
        first_period_steady=False,
    )
    setup = SetupContext(
        flow=SimpleNamespace(active_bc=[], sinks_sources={}),
        domain=object(),
        geographic=SimpleNamespace(crs_proj="EPSG:2154", catch_area=10.0),
        time_grid=SimpleNamespace(window=_short_window()),
    )
    return SimpleNamespace(
        setup=setup,
        loaded_data=LoadedDataContext(precipitation=object(), etp=object()),
        cfg=SimpleNamespace(flow=flow_cfg),
    )


def test_the_binder_refuses_a_spinup_shorter_than_a_year(monkeypatch) -> None:
    run_state = _run_state(with_soil=True)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.compute_soil_forcings",
        lambda **kwargs: pytest.fail("compute_soil_forcings must not run after a refusal"),
    )
    expected = spinup_refusal(run_state.cfg.flow.sinks_sources.recharge.soil, 9)
    assert expected is not None

    with pytest.raises(ConfigError, match=r"start from a full soil"):
        apply_structural_updates_from_data(run_state)


def test_the_binder_does_not_check_the_spinup_without_soil(monkeypatch) -> None:
    run_state = _run_state(with_soil=False)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.apply_recharge_load_result_to_flow",
        lambda **kwargs: False,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.apply_etp_load_result_to_flow",
        lambda **kwargs: False,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.apply_runoff_to_sfr_networks",
        lambda **kwargs: False,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.apply_lake_meteo_forcings_to_flow",
        lambda **kwargs: False,
    )

    apply_structural_updates_from_data(run_state)

    assert run_state.setup.soil_forcings is None
