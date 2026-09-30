"""A phase override that reopens a soil run on a steady first period is caught.

``steady_start_refusal`` is checked at load time (config layer), but a
calibration phase can flip ``flow.first_period_steady`` or the time window
after loading (``calibration/runners/phase_regime.py``). The binder repeats the
same guard, with the same text, so a soil run started from a drained aquifer
is refused at run time too, before ``compute_soil_forcings`` ever runs.
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
    steady_start_refusal,
)
from hydromodpy.workflow.steps.data import apply_structural_updates_from_data


def _window() -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2015-01-01"),
        end=pd.Timestamp("2015-01-02"),
        step_value=1,
        step_unit="day",
        coverage_policy="ignore",
    )


def _run_state(*, with_soil: bool, first_period_steady: bool) -> SimpleNamespace:
    soil = SoilReservoirConfig(ru=150.0) if with_soil else None
    flow_cfg = SimpleNamespace(
        sinks_sources=SimpleNamespace(recharge=SimpleNamespace(soil=soil)),
        flow_regime="transient",
        first_period_steady=first_period_steady,
    )
    setup = SetupContext(
        flow=SimpleNamespace(active_bc=[], sinks_sources={}),
        domain=object(),
        geographic=SimpleNamespace(crs_proj="EPSG:2154", catch_area=10.0),
        time_grid=SimpleNamespace(window=_window()),
    )
    return SimpleNamespace(
        setup=setup,
        loaded_data=LoadedDataContext(precipitation=object(), etp=object()),
        cfg=SimpleNamespace(flow=flow_cfg),
    )


def test_the_binder_refuses_a_transient_one_period_steady_start(monkeypatch) -> None:
    run_state = _run_state(with_soil=True, first_period_steady=True)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.compute_soil_forcings",
        lambda **kwargs: pytest.fail("compute_soil_forcings must not run after a refusal"),
    )
    expected = steady_start_refusal(run_state.cfg.flow, _window())
    assert expected is not None

    with pytest.raises(ConfigError, match=r"drained aquifer"):
        apply_structural_updates_from_data(run_state)


def test_the_binder_does_not_check_the_steady_start_without_soil(monkeypatch) -> None:
    run_state = _run_state(with_soil=False, first_period_steady=True)
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
