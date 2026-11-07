"""The data step: structural updates, the soil binder, the SFR network."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from shapely.geometry import LineString, box

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.run_state import ExecutionRegistry, LoadedDataContext, SetupContext
from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.model.boundaries.streams import apply_sfr_network_to_flow
from hydromodpy.model.sinks_sources.sfr import FlowReachNetworkConfig
from hydromodpy.model.soil.config import SoilReservoirConfig, spinup_refusal, steady_start_refusal
from hydromodpy.spatial.geographic.core.derived_features import (
    GeographicBoundaryFeatures,
    GeographicDerivedFeatures,
)
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
    HydrographicNetwork,
    HydrographicNetworks,
)
from hydromodpy.spatial.geographic.store_ingestion import persist_geographic_to_store
from hydromodpy.workflow.steps import data as data_step
from hydromodpy.workflow.steps.data import (
    apply_structural_updates_from_data,
    bind_sfr_network_traces,
)
from hydromodpy.workflow.steps.prepare_solver.forcings import step_persist_forcings
from tests.unit.workflow.steps._helpers import (
    hydrography_load_result,
    write_network_vector,
    write_watershed,
)

# --- test_a_soil_run_refuses_a_one_period_steady_start_at_run_time ---
# A phase override that reopens a soil run on a steady first period is caught.
#
# ``steady_start_refusal`` is checked at load time (config layer), but a
# calibration phase can flip ``flow.first_period_steady`` or the time window
# after loading (``calibration/runners/phase_regime.py``). The binder repeats the
# same guard, with the same text, so a soil run started from a drained aquifer
# is refused at run time too, before ``compute_soil_forcings`` ever runs.


def _window() -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2015-01-01"),
        end=pd.Timestamp("2015-01-02"),
        step_value=1,
        step_unit="day",
        coverage_policy="ignore",
    )


def _steady_start_state(*, with_soil: bool, first_period_steady: bool) -> SimpleNamespace:
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
    run_state = _steady_start_state(with_soil=True, first_period_steady=True)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.compute_soil_forcings",
        lambda **kwargs: pytest.fail("compute_soil_forcings must not run after a refusal"),
    )
    expected = steady_start_refusal(run_state.cfg.flow, _window())
    assert expected is not None

    with pytest.raises(ConfigError, match=r"drained aquifer"):
        apply_structural_updates_from_data(run_state)


def test_the_binder_does_not_check_the_steady_start_without_soil(monkeypatch) -> None:
    run_state = _steady_start_state(with_soil=False, first_period_steady=True)
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


# --- test_a_soil_run_refuses_a_spinup_shorter_than_a_year_at_run_time ---
# A phase override that shortens the window below a year is caught.
#
# ``spinup_refusal`` is checked at load time (config layer), but a calibration
# phase can shorten ``[simulation.time]`` after loading
# (``calibration/runners/phase_regime.py``, ``regime_overrides``). The binder
# repeats the same guard, with the same text, so a run that repeats the first
# year on a window under 365 days is refused at run time too, before
# ``compute_soil_forcings`` ever runs.


def _short_window() -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2015-01-01"),
        end=pd.Timestamp("2015-01-10"),
        step_value=1,
        step_unit="day",
        coverage_policy="ignore",
    )


def _spinup_state(*, with_soil: bool) -> SimpleNamespace:
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
    run_state = _spinup_state(with_soil=True)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.compute_soil_forcings",
        lambda **kwargs: pytest.fail("compute_soil_forcings must not run after a refusal"),
    )
    expected = spinup_refusal(run_state.cfg.flow.sinks_sources.recharge.soil, 9)
    assert expected is not None

    with pytest.raises(ConfigError, match=r"start from a full soil"):
        apply_structural_updates_from_data(run_state)


def test_the_binder_does_not_check_the_spinup_without_soil(monkeypatch) -> None:
    run_state = _spinup_state(with_soil=False)
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


# --- test_the_binder_sends_the_soil_recharge_etp_and_runoff ---
# In soil mode the binder feeds MODFLOW from the soil reservoir, not the loader.
#
# ``apply_structural_updates_from_data`` reads ``[flow.sinks_sources.recharge.soil]``
# from ``run_state.cfg.flow``, calls ``compute_soil_forcings`` once, and sends its
# outputs everywhere the loaded data would otherwise have gone: recharge, the ETP
# the soil left unmet (marked ``from_soil_reservoir``), and the runoff (to both the
# SFR binder and the lake meteo binder). The lake still receives the raw
# precipitation and ETP for its own surface. Outside soil mode nothing changes and
# ``setup.soil_forcings`` stays ``None``.


def _binder_window() -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2015-01-01"),
        end=pd.Timestamp("2015-01-03"),
        step_value=1,
        step_unit="day",
        coverage_policy="ignore",
    )


_SOIL_RECHARGE = object()


_SOIL_RESIDUAL_ETP = object()


_SOIL_RUNOFF = object()


def _soil_forcings() -> SimpleNamespace:
    return SimpleNamespace(
        recharge=_SOIL_RECHARGE,
        residual_etp=_SOIL_RESIDUAL_ETP,
        runoff=_SOIL_RUNOFF,
    )


def _flow_cfg(*, with_soil: bool) -> SimpleNamespace:
    soil = SoilReservoirConfig(ru=150.0, spinup="none") if with_soil else None
    return SimpleNamespace(
        sinks_sources=SimpleNamespace(recharge=SimpleNamespace(soil=soil)),
        flow_regime="transient",
        first_period_steady=False,
    )


def _binder_state(*, with_soil: bool) -> tuple[SimpleNamespace, dict[str, dict]]:
    calls: dict[str, dict] = {}
    setup = SetupContext(
        flow=SimpleNamespace(active_bc=[], sinks_sources={}),
        domain=object(),
        geographic=SimpleNamespace(crs_proj="EPSG:2154", catch_area=10.0),
        time_grid=SimpleNamespace(window=_binder_window()),
    )
    loaded_data = LoadedDataContext(
        precipitation=object(),
        etp=object(),
        runoff=object(),
        recharge=object(),
    )
    run_state = SimpleNamespace(
        setup=setup,
        loaded_data=loaded_data,
        cfg=SimpleNamespace(flow=_flow_cfg(with_soil=with_soil)),
    )
    return run_state, calls


def _patch_capture(monkeypatch, calls: dict[str, dict]) -> None:
    def _capture(name):
        def _fn(**kwargs):
            calls[name] = kwargs
            return False

        return _fn

    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.compute_soil_forcings",
        lambda **kwargs: _soil_forcings(),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.apply_recharge_load_result_to_flow",
        _capture("recharge"),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.apply_etp_load_result_to_flow",
        _capture("etp"),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.apply_runoff_to_sfr_networks",
        _capture("sfr_runoff"),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.apply_lake_meteo_forcings_to_flow",
        _capture("lake_meteo"),
    )


def test_the_binder_sends_the_soil_recharge_to_modflow(monkeypatch) -> None:
    run_state, calls = _binder_state(with_soil=True)
    _patch_capture(monkeypatch, calls)

    apply_structural_updates_from_data(run_state)

    assert calls["recharge"]["recharge_result"] is _SOIL_RECHARGE


def test_the_binder_sends_the_soil_residual_etp_marked_from_soil_reservoir(
    monkeypatch,
) -> None:
    run_state, calls = _binder_state(with_soil=True)
    _patch_capture(monkeypatch, calls)

    apply_structural_updates_from_data(run_state)

    assert calls["etp"]["etp_result"] is _SOIL_RESIDUAL_ETP
    assert calls["etp"]["from_soil_reservoir"] is True


def test_the_binder_sends_the_soil_runoff_to_the_sfr_network(monkeypatch) -> None:
    run_state, calls = _binder_state(with_soil=True)
    _patch_capture(monkeypatch, calls)

    apply_structural_updates_from_data(run_state)

    assert calls["sfr_runoff"]["runoff"] is _SOIL_RUNOFF


def test_the_binder_sends_the_soil_runoff_to_the_lake_and_keeps_its_raw_meteo(
    monkeypatch,
) -> None:
    run_state, calls = _binder_state(with_soil=True)
    _patch_capture(monkeypatch, calls)

    apply_structural_updates_from_data(run_state)

    assert calls["lake_meteo"]["runoff"] is _SOIL_RUNOFF
    assert calls["lake_meteo"]["precipitation"] is run_state.loaded_data.precipitation
    assert calls["lake_meteo"]["etp"] is run_state.loaded_data.etp


def test_the_binder_stores_the_soil_forcings_on_setup(monkeypatch) -> None:
    run_state, calls = _binder_state(with_soil=True)
    _patch_capture(monkeypatch, calls)

    apply_structural_updates_from_data(run_state)

    assert run_state.setup.soil_forcings.recharge is _SOIL_RECHARGE


def test_the_binder_leaves_soil_forcings_none_without_a_soil_section(
    monkeypatch,
) -> None:
    run_state, calls = _binder_state(with_soil=False)
    _patch_capture(monkeypatch, calls)

    apply_structural_updates_from_data(run_state)

    assert run_state.setup.soil_forcings is None
    assert calls["recharge"]["recharge_result"] is run_state.loaded_data.recharge
    assert calls["etp"]["etp_result"] is run_state.loaded_data.etp
    assert calls["etp"]["from_soil_reservoir"] is False
    assert calls["sfr_runoff"]["runoff"] is run_state.loaded_data.runoff


def test_the_binder_never_mutates_loaded_data(monkeypatch) -> None:
    run_state, calls = _binder_state(with_soil=True)
    _patch_capture(monkeypatch, calls)
    loaded_data = run_state.loaded_data
    precipitation, etp, runoff, recharge = (
        loaded_data.precipitation,
        loaded_data.etp,
        loaded_data.runoff,
        loaded_data.recharge,
    )

    apply_structural_updates_from_data(run_state)

    assert run_state.loaded_data is loaded_data
    assert loaded_data.precipitation is precipitation
    assert loaded_data.etp is etp
    assert loaded_data.runoff is runoff
    assert loaded_data.recharge is recharge


# --- test_the_soil_budget_is_printed_once_by_the_data_step ---
# The soil water budget prints once per ``step_data_loading``, never from the binder alone.
#
# ``step_data_loading`` prints the block after the binder has run, through
# ``progress.after_phase`` so it lands after the phase's own checkmark. The
# binder itself (``apply_structural_updates_from_data``) only computes and
# stores ``setup.soil_forcings``; it never prints. A lightweight context (a
# calibration trial replaying ``load_data``) stays silent either way.


def _printed_soil_forcings() -> SimpleNamespace:
    return SimpleNamespace(
        recharge=object(),
        residual_etp=object(),
        runoff=object(),
        days=["2015-01-01", "2015-01-02"],
    )


def _printed_state(*, lightweight: bool, with_soil: bool) -> SimpleNamespace:
    soil = SoilReservoirConfig(ru=150.0, spinup="none") if with_soil else None
    setup = SetupContext(
        flow=SimpleNamespace(active_bc=[], sinks_sources={}),
        domain=object(),
        geographic=SimpleNamespace(crs_proj="EPSG:2154", catch_area=10.0),
        time_grid=SimpleNamespace(window=_window()),
    )
    return SimpleNamespace(
        setup=setup,
        loaded_data=LoadedDataContext(hydrometry=None, precipitation=object(), etp=object()),
        cfg=SimpleNamespace(
            flow=SimpleNamespace(
                sinks_sources=SimpleNamespace(recharge=SimpleNamespace(soil=soil)),
                flow_regime="transient",
                first_period_steady=False,
                active_sinks_sources=["recharge", "etp"],
            )
        ),
        execution=ExecutionRegistry(lightweight=lightweight),
        config_path="config.toml",
        data_plan=SimpleNamespace(types=()),
    )


def _patch_binder_internals(monkeypatch) -> None:
    monkeypatch.setattr(
        data_step, "compute_soil_forcings", lambda **kwargs: _printed_soil_forcings()
    )
    monkeypatch.setattr(data_step, "apply_recharge_load_result_to_flow", lambda **kwargs: False)
    monkeypatch.setattr(data_step, "apply_etp_load_result_to_flow", lambda **kwargs: False)
    monkeypatch.setattr(data_step, "apply_runoff_to_sfr_networks", lambda **kwargs: False)
    monkeypatch.setattr(data_step, "apply_lake_meteo_forcings_to_flow", lambda **kwargs: False)
    monkeypatch.setattr(data_step, "ru_ladder", lambda soil: ())
    monkeypatch.setattr(data_step, "gauged_discharge_line", lambda *args, **kwargs: "line")
    monkeypatch.setattr(data_step, "soil_budget_lines", lambda soil, **kwargs: ("line",))


def test_step_data_loading_prints_the_soil_budget_exactly_once(monkeypatch) -> None:
    run_state = _printed_state(lightweight=False, with_soil=True)
    _patch_binder_internals(monkeypatch)
    fake_loader = SimpleNamespace(load_all=lambda run_state: None)
    monkeypatch.setattr(data_step, "_build_data_runtime_loader", lambda **kwargs: fake_loader)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(data_step, "_log_soil_budget", lambda lines: calls.append(lines))

    data_step.step_data_loading(run_state)

    assert calls == [("line",)]


def test_the_binder_alone_never_prints_the_soil_budget(monkeypatch) -> None:
    run_state = _printed_state(lightweight=False, with_soil=True)
    _patch_binder_internals(monkeypatch)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(data_step, "_log_soil_budget", lambda lines: calls.append(lines))

    data_step.apply_structural_updates_from_data(run_state)

    assert calls == []
    assert run_state.setup.soil_forcings is not None


def test_a_lightweight_context_stays_silent(monkeypatch) -> None:
    run_state = _printed_state(lightweight=True, with_soil=True)
    _patch_binder_internals(monkeypatch)
    fake_loader = SimpleNamespace(load_all=lambda run_state: None)
    monkeypatch.setattr(data_step, "_build_data_runtime_loader", lambda **kwargs: fake_loader)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(data_step, "_log_soil_budget", lambda lines: calls.append(lines))

    data_step.step_data_loading(run_state)

    assert calls == []


# --- test_sfr_network_binding ---
# Runtime SFR binding: delineate once, cache on setup, attach onto the flow.

_RES = 10.0


_N = 8


def _write_raster(path: Path, data: np.ndarray) -> str:
    import rasterio
    from rasterio.transform import from_origin

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float64",
        crs="EPSG:32630",
        transform=from_origin(0.0, 80.0, _RES, _RES),
    ) as dataset:
        dataset.write(np.asarray(data, dtype="float64"), 1)
    return str(path)


def _geographic_double(tmp_path: Path, *, threshold_cells: float = 50.0) -> SimpleNamespace:
    dem = np.zeros((_N, _N))
    for row in range(_N):
        dem[row, :] = 100.0 - row
    d8 = np.full((_N, _N), 4.0)
    link = np.zeros((_N, _N))
    link[1:4, 3] = 1.0
    link[4:7, 3] = 2.0
    acc = np.ones((_N, _N))
    for row in range(_N):
        acc[row, 3] = 5.0 * (row + 1)
    products = SimpleNamespace(
        enabled=True,
        threshold_cells=threshold_cells,
        flow_acc_cells_tif=_write_raster(tmp_path / "acc_cells.tif", acc),
        stream_link_id_full_tif=_write_raster(tmp_path / "link_full.tif", link),
        stream_order_strahler_full_tif=None,
    )
    flow_products = SimpleNamespace(
        direc=_write_raster(tmp_path / "d8.tif", d8),
        correc=_write_raster(tmp_path / "dem_correc.tif", dem - 10.0),
    )
    return SimpleNamespace(
        _river_network_products=products,
        _flow_products=flow_products,
        # The routing surface above is trenched by 10 m; the bed must come from
        # this one, so a reach top that reads 10 m low proves the wrong source.
        _top_dem_path=_write_raster(tmp_path / "dem_top.tif", dem),
        dem_res=_RES,
    )


def _network_config(**overrides) -> FlowReachNetworkConfig:
    payload = {"outflow_to_lake": 1}
    payload.update(overrides)
    return FlowReachNetworkConfig(**payload)


def _flow_double(network: FlowReachNetworkConfig) -> SimpleNamespace:
    return SimpleNamespace(
        active_bc=["sfr", "lake"],
        sinks_sources={
            "sfr": {"net0": network},
            "lakes": {"lac0": {"polygon": box(20.0, 0.0, 60.0, 12.0)}},
        },
    )


def _sfr_state(tmp_path: Path, network: FlowReachNetworkConfig, **geo_kwargs) -> SimpleNamespace:
    return SimpleNamespace(
        setup=SimpleNamespace(
            flow=_flow_double(network),
            geographic=_geographic_double(tmp_path, **geo_kwargs),
            sfr_reach_traces=None,
        )
    )


def test_bind_sfr_network_traces_attaches_and_caches(tmp_path: Path) -> None:
    run_state = _sfr_state(tmp_path, _network_config())
    bind_sfr_network_traces(run_state)

    traces = run_state.setup.sfr_reach_traces
    assert traces is not None and "net0" in traces
    assert traces["net0"].reach_count == 2
    assert traces["net0"].reaches[-1].is_terminal_to_lake

    payload = run_state.setup.flow.sinks_sources["sfr"]["net0"]
    assert isinstance(payload, dict)
    assert payload["reach_trace"] is traces["net0"]
    assert payload["outflow_to_lake"] == 1


def test_bind_sfr_network_traces_is_a_noop_when_sfr_inactive(tmp_path: Path) -> None:
    run_state = _sfr_state(tmp_path, _network_config())
    run_state.setup.flow.active_bc = ["lake"]
    bind_sfr_network_traces(run_state)
    assert run_state.setup.sfr_reach_traces is None


def test_bind_sfr_network_traces_requires_link_raster(tmp_path: Path) -> None:
    run_state = _sfr_state(tmp_path, _network_config())
    run_state.setup.geographic._river_network_products.stream_link_id_full_tif = None
    with pytest.raises(ConfigError, match="compute_stream_links"):
        bind_sfr_network_traces(run_state)


def test_apply_sfr_network_to_flow_skips_explicit_reach_tables(tmp_path: Path) -> None:
    network = _network_config()
    flow = _flow_double(network)
    flow.sinks_sources["sfr"]["explicit"] = {"reaches": [object()], "outflow_to_lake": None}
    attached = apply_sfr_network_to_flow(
        flow=flow, reach_traces={"net0": object(), "explicit": object()}
    )
    assert attached
    payloads = flow.sinks_sources["sfr"]
    assert "reach_trace" in payloads["net0"]
    assert "reach_trace" not in payloads["explicit"]


def test_apply_sfr_network_to_flow_without_traces_is_noop() -> None:
    flow = _flow_double(_network_config())
    assert apply_sfr_network_to_flow(flow=flow, reach_traces=None) is False
    assert apply_sfr_network_to_flow(flow=flow, reach_traces={}) is False


def test_bind_sfr_network_traces_reads_the_bed_on_the_model_top(tmp_path: Path) -> None:
    # The geographic double trenches its routing surface by 10 m. Binding must
    # ignore it: a reach top read there would come out one trench depth low.
    run_state = _sfr_state(tmp_path, _network_config())
    bind_sfr_network_traces(run_state)
    tops = [reach.rtp for reach in run_state.setup.sfr_reach_traces["net0"].reaches]
    assert tops
    assert min(tops) > 0.0


def test_bind_sfr_network_traces_names_a_missing_model_top(tmp_path: Path) -> None:
    run_state = _sfr_state(tmp_path, _network_config())
    run_state.setup.geographic._top_dem_path = None
    with pytest.raises(ConfigError, match="model-top DEM"):
        bind_sfr_network_traces(run_state)


def test_apply_structural_updates_from_data_attaches_reference_network(
    tmp_path: Path,
    monkeypatch,
):
    streams_path = write_network_vector(tmp_path / "streams.shp")
    watershed_path = write_watershed(tmp_path / "watershed.shp")
    features = GeographicDerivedFeatures(
        surface_topo=object(),
        boundaries=GeographicBoundaryFeatures(
            watershed_shp=str(watershed_path),
            watershed_box_shp=None,
            box_buff_shp="box_buff.shp",
        ),
        hydrographic_networks=HydrographicNetworks(),
    )
    ctx = SimpleNamespace(
        setup=SimpleNamespace(
            domain=object(),
            flow=object(),
            time_grid=None,
            geographic_features=features,
        ),
        loaded_data=LoadedDataContext(
            hydrography=hydrography_load_result(
                vector_path=streams_path,
                raster_path=tmp_path / "streams.tif",
                array=np.asarray([[1.0, 0.0]], dtype=float),
            ),
        ),
        cfg=SimpleNamespace(),
    )

    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.apply_geology_to_domain",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.ensure_flow",
        lambda run_state: None,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.apply_oceanic_to_flow",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.apply_recharge_load_result_to_flow",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.apply_etp_load_result_to_flow",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.resolve_simulation_time_window",
        lambda cfg: None,
    )

    apply_structural_updates_from_data(ctx)

    assert ctx.setup.geographic_features.reference_hydrographic_network is not None
    assert ctx.setup.geographic_features.reference_hydrographic_network.vector_path == str(
        streams_path
    )
