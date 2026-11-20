"""The data step binds loaded data to the model: structural updates, soil forcings, SFR network.

In soil mode the binder feeds MODFLOW from the soil reservoir (recharge and unmet ETP in
mm/day, runoff to the SFR and lake binders), and a run that cannot start from a full soil
is refused. The SFR binder delineates reaches once, caches them on the setup and attaches
them to the flow. Dates are daily and lengths are in m.
"""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from shapely.geometry import LineString, box

from hydromodpy.catchment.algorithms.derived_features import (
    GeographicBoundaryFeatures,
    GeographicDerivedFeatures,
)
from hydromodpy.catchment.algorithms.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
    HydrographicNetwork,
    HydrographicNetworks,
)
from hydromodpy.catchment.preprocess.store_ingestion import persist_geographic_to_store
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.run_state import (
    ExecutionRegistry,
    LoadedDataContext,
    SetupContext,
    WorkflowContext,
)
from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.model.boundaries.streams import apply_sfr_network_to_flow
from hydromodpy.model.forcing.soil_config import (
    SoilReservoirConfig,
    spinup_refusal,
    steady_start_refusal,
)
from hydromodpy.model.sinks_sources.sfr import FlowReachNetworkConfig
from hydromodpy.results.products.store import products_root
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


def window(end: str) -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2015-01-01"),
        end=pd.Timestamp(end),
        step_value=1,
        step_unit="day",
        coverage_policy="ignore",
    )


# The binder repeats at run time the two guards of the config layer, with the same text,
# because a calibration phase can flip first_period_steady or shorten the time window
# after loading. A soil run started from a drained aquifer, or on a window under a year
# with the first year repeated, is refused before compute_soil_forcings runs.
def soil_state(end: str, *, first_period_steady: bool) -> SimpleNamespace:
    flow_cfg = SimpleNamespace(
        sinks_sources=SimpleNamespace(recharge=SimpleNamespace(soil=SoilReservoirConfig(ru=150.0))),
        flow_regime="transient",
        first_period_steady=first_period_steady,
    )
    setup = SetupContext(
        flow=SimpleNamespace(active_bc=[], sinks_sources={}),
        domain=object(),
        geographic=SimpleNamespace(crs_proj="EPSG:2154", catch_area=10.0),
        time_grid=SimpleNamespace(window=window(end)),
    )
    return SimpleNamespace(
        setup=setup,
        loaded_data=LoadedDataContext(precipitation=object(), etp=object()),
        cfg=SimpleNamespace(flow=flow_cfg),
    )


def test_binder_refuses_a_steady_start(monkeypatch) -> None:
    run_state = soil_state("2015-01-02", first_period_steady=True)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.compute_soil_forcings",
        lambda **kwargs: pytest.fail("compute_soil_forcings must not run after a refusal"),
    )
    expected = steady_start_refusal(run_state.cfg.flow, window("2015-01-02"))
    assert expected is not None

    with pytest.raises(ConfigError, match=r"drained aquifer"):
        apply_structural_updates_from_data(run_state)


# A spatialized source is averaged over the one cell of a lumped mesh, so the binder
# gives the forcing a catchment polygon (in the CRS of the model) only there.


def test_polygon_only_on_a_lumped_mesh(monkeypatch, tmp_path: Path) -> None:
    watershed = write_watershed(tmp_path / "watershed.shp")
    calls: dict[str, dict] = {}
    _patch_capture(monkeypatch, calls)
    setup = SetupContext(
        flow=SimpleNamespace(active_bc=[], sinks_sources={}),
        domain=object(),
        geographic=SimpleNamespace(crs_proj="EPSG:2154", watershed_shp=str(watershed)),
        time_grid=SimpleNamespace(window=window("2015-01-03")),
    )
    for engine, expected in (("catchment", True), ("regular", False)):
        run_state = SimpleNamespace(
            setup=setup,
            loaded_data=LoadedDataContext(recharge=object(), etp=object()),
            cfg=SimpleNamespace(
                flow=_flow_cfg(with_soil=False), mesh=SimpleNamespace(engine=engine)
            ),
        )

        data_step._bind_soil_recharge_etp(run_state, window("2015-01-03"))

        polygon = calls["recharge"]["cell_polygon"]
        if expected:
            assert polygon is not None
            assert polygon.bounds == (0.0, -500.0, 1000.0, 500.0)
        else:
            assert polygon is None


def test_binder_refuses_a_short_spinup(monkeypatch) -> None:
    run_state = soil_state("2015-01-10", first_period_steady=False)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.compute_soil_forcings",
        lambda **kwargs: pytest.fail("compute_soil_forcings must not run after a refusal"),
    )
    expected = spinup_refusal(run_state.cfg.flow.sinks_sources.recharge.soil, 9)
    assert expected is not None

    with pytest.raises(ConfigError, match=r"start from a full soil"):
        apply_structural_updates_from_data(run_state)


# In soil mode the binder feeds MODFLOW from the soil reservoir, not the loader. The ETP
# the soil left unmet is marked from_soil_reservoir. Outside soil mode nothing changes
# and setup.soil_forcings stays None.

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
        "hydromodpy.workflow.steps.data._soil_input_digests",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.ask",
        lambda ctx, kind, *, key, build, read: build(),
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


# The soil water budget prints once per step_data_loading, after the binder has run,
# never from the binder alone. A lightweight context stays silent either way.


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
        time_grid=SimpleNamespace(window=window("2015-01-02")),
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
        bounds=None,
    )


def _patch_binder_internals(monkeypatch) -> None:
    monkeypatch.setattr(
        data_step, "compute_soil_forcings", lambda **kwargs: _printed_soil_forcings()
    )
    monkeypatch.setattr(data_step, "_soil_input_digests", lambda *args, **kwargs: {})
    monkeypatch.setattr(data_step, "ask", lambda ctx, kind, *, key, build, read: build())
    monkeypatch.setattr(data_step, "apply_recharge_load_result_to_flow", lambda **kwargs: False)
    monkeypatch.setattr(data_step, "apply_etp_load_result_to_flow", lambda **kwargs: False)
    monkeypatch.setattr(data_step, "apply_runoff_to_sfr_networks", lambda **kwargs: False)
    monkeypatch.setattr(data_step, "apply_lake_meteo_forcings_to_flow", lambda **kwargs: False)
    monkeypatch.setattr(data_step, "ru_ladder", lambda soil: ())
    monkeypatch.setattr(data_step, "gauged_discharge_line", lambda *args, **kwargs: "line")
    monkeypatch.setattr(data_step, "soil_budget_lines", lambda soil, **kwargs: ("line",))


def test_soil_budget_printed_once(monkeypatch) -> None:
    run_state = _printed_state(lightweight=False, with_soil=True)
    _patch_binder_internals(monkeypatch)
    fake_loader = SimpleNamespace(load_all=lambda run_state: None)
    monkeypatch.setattr(data_step, "_build_data_runtime_loader", lambda **kwargs: fake_loader)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(data_step, "_log_soil_budget", lambda lines: calls.append(lines))

    data_step.step_data_loading(run_state)

    assert calls == [("line",)]


def test_binder_alone_prints_nothing(monkeypatch) -> None:
    run_state = _printed_state(lightweight=False, with_soil=True)
    _patch_binder_internals(monkeypatch)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(data_step, "_log_soil_budget", lambda lines: calls.append(lines))

    data_step.apply_structural_updates_from_data(run_state)

    assert calls == []
    assert run_state.setup.soil_forcings is not None


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


def test_sfr_traces_attach_and_cache(tmp_path: Path) -> None:
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


def test_sfr_traces_need_the_link_raster(tmp_path: Path) -> None:
    run_state = _sfr_state(tmp_path, _network_config())
    run_state.setup.geographic._river_network_products.stream_link_id_full_tif = None
    with pytest.raises(ConfigError, match="compute_stream_links"):
        bind_sfr_network_traces(run_state)


def test_explicit_reach_tables_are_skipped(tmp_path: Path) -> None:
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


def test_no_traces_is_a_noop() -> None:
    flow = _flow_double(_network_config())
    assert apply_sfr_network_to_flow(flow=flow, reach_traces=None) is False
    assert apply_sfr_network_to_flow(flow=flow, reach_traces={}) is False


def test_reach_bed_is_read_on_the_model_top(tmp_path: Path) -> None:
    # The geographic double trenches its routing surface by 10 m. Binding must
    # ignore it: a reach top read there would come out one trench depth low.
    run_state = _sfr_state(tmp_path, _network_config())
    bind_sfr_network_traces(run_state)
    tops = [reach.rtp for reach in run_state.setup.sfr_reach_traces["net0"].reaches]
    assert tops
    assert min(tops) > 0.0


def test_missing_model_top_is_named(tmp_path: Path) -> None:
    run_state = _sfr_state(tmp_path, _network_config())
    run_state.setup.geographic._top_dem_path = None
    with pytest.raises(ConfigError, match="model-top DEM"):
        bind_sfr_network_traces(run_state)


def test_reference_network_is_attached(
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


# ensure_flow builds the flow of the configuration once. A flow built from another
# configuration is rebuilt, and the model frozen from it goes with it.


def _flow_state(config, *, flow=None, model=None) -> SimpleNamespace:
    return SimpleNamespace(
        cfg=SimpleNamespace(flow=config),
        setup=SimpleNamespace(flow=flow, model=model),
        loaded_data=SimpleNamespace(loaded_plan_types=None),
    )


@pytest.mark.parametrize(
    ("same_configuration", "rebuilt"),
    [
        pytest.param(False, True, id="another configuration"),
        pytest.param(True, False, id="the same configuration"),
    ],
)
def test_stale_flow_is_rebuilt_with_its_model(same_configuration: bool, rebuilt: bool) -> None:
    from hydromodpy.model.flow import Flow
    from hydromodpy.model.flow_config import FlowConfig

    config = FlowConfig()
    flow = Flow(config=config if same_configuration else FlowConfig())
    state = _flow_state(config, flow=flow, model="the model of the old flow")

    assert data_step.rebind_flow_if_stale(state) is rebuilt

    assert (state.setup.flow is not flow) is rebuilt
    assert (state.setup.model is None) is rebuilt


# The soil is computed once. A fork that leaves the soil parameters alone reuses the
# prepared SoilForcings in memory, without running the kernel or hashing its grids again.

_SOIL_PRODUCT_CRS = "EPSG:2154"


def _soil_grid_result(variable, values, *, days, x, y):
    dataset = xr.Dataset(
        {variable: (("time", "y", "x"), values)},
        coords={"time": days, "y": y, "x": x},
    )
    record = FieldRecord(
        variable=variable,
        source="sim2",
        unit="mm/day",
        data=dataset,
        bbox=(x.min(), y.min(), x.max(), y.max()),
        crs=_SOIL_PRODUCT_CRS,
        date_start=days[0],
        date_end=days[-1],
    )
    return LoadResult(fields=[record])


def _soil_window(days):
    return ResolvedSimulationTimeWindow(
        start=days[0],
        end=days[-1],
        step_value=1,
        step_unit="day",
        coverage_policy="error",
    )


def _soil_flow_config(soil_config):
    return SimpleNamespace(
        sinks_sources=SimpleNamespace(recharge=SimpleNamespace(soil=soil_config)),
        flow_regime="transient",
        first_period_steady=False,
    )


def _soil_ctx(soil_config, *, precipitation, etp, workspace=None):
    cfg = SimpleNamespace(flow=_soil_flow_config(soil_config), mesh=None)
    ctx = WorkflowContext(cfg=cfg, config_path=Path("run.toml"), raw_toml={})
    ctx.setup = SetupContext(
        geographic=SimpleNamespace(crs_proj=_SOIL_PRODUCT_CRS),
        flow=cfg.flow,
        workspace=workspace,
    )
    ctx.setup.soil_product_inputs = None
    ctx.loaded_data = LoadedDataContext(
        precipitation=precipitation,
        etp=etp,
        recharge=None,
        runoff=None,
        soil_capacity=None,
    )
    ctx.execution.lightweight = True
    ctx.execution.resumed = False
    ctx.run_dir = None
    return ctx


def _soil_forcing_results():
    days = pd.date_range("2015-01-01", periods=400, freq="D")
    x = np.array([0.0, 100.0])
    y = np.array([100.0, 0.0])
    rng = np.random.default_rng(0)
    precipitation = rng.gamma(2.0, 2.0, size=(len(days), 2, 2))
    etp = np.full((len(days), 2, 2), 2.0)
    return (
        days,
        _soil_grid_result("precipitation", precipitation, days=days, x=x, y=y),
        _soil_grid_result("etp", etp, days=days, x=x, y=y),
    )


def test_fork_reuses_the_soil():
    days, precip, etp = _soil_forcing_results()
    parent = _soil_ctx(SoilReservoirConfig(ru=150.0, spinup="none"), precipitation=precip, etp=etp)
    with (
        patch.object(
            data_step, "compute_soil_forcings", wraps=data_step.compute_soil_forcings
        ) as compute,
        patch.object(data_step, "apply_recharge_load_result_to_flow"),
        patch.object(data_step, "apply_etp_load_result_to_flow"),
    ):
        soil = data_step._bind_soil_recharge_etp(parent, _soil_window(days))
    assert soil is not None
    assert compute.call_count == 1
    assert parent.setup.soil_forcings is soil

    fork = WorkflowContext(cfg=parent.cfg, config_path=parent.config_path, raw_toml={})
    fork.setup = copy.copy(parent.setup)
    fork.loaded_data = parent.loaded_data
    fork.execution.lightweight = True
    fork.execution.resumed = False
    fork.run_dir = None
    with (
        patch.object(
            data_step, "compute_soil_forcings", wraps=data_step.compute_soil_forcings
        ) as compute,
        patch.object(data_step, "apply_recharge_load_result_to_flow"),
        patch.object(data_step, "apply_etp_load_result_to_flow"),
    ):
        reused = data_step._bind_soil_recharge_etp(fork, _soil_window(days))
    assert compute.call_count == 0
    assert reused is soil


def test_new_precipitation_gives_a_new_soil():
    days, precip, etp = _soil_forcing_results()
    ctx = _soil_ctx(SoilReservoirConfig(ru=150.0, spinup="none"), precipitation=precip, etp=etp)
    with (
        patch.object(data_step, "apply_recharge_load_result_to_flow"),
        patch.object(data_step, "apply_etp_load_result_to_flow"),
    ):
        soil = data_step._bind_soil_recharge_etp(ctx, _soil_window(days))
        first_key = ctx.setup.products["soil"]
        values = precip.fields[0].data["precipitation"].values * 2.0
        x = precip.fields[0].data["x"].values
        y = precip.fields[0].data["y"].values
        ctx.loaded_data.precipitation = _soil_grid_result(
            "precipitation", values, days=days, x=x, y=y
        )
        with patch.object(
            data_step, "compute_soil_forcings", wraps=data_step.compute_soil_forcings
        ) as compute:
            reloaded = data_step._bind_soil_recharge_etp(ctx, _soil_window(days))
    assert compute.call_count == 1
    assert reloaded is not soil
    assert ctx.setup.products["soil"] != first_key


def test_ru_change_computes_in_memory(tmp_path):
    days, precip, etp = _soil_forcing_results()
    parent = _soil_ctx(SoilReservoirConfig(ru=150.0, spinup="none"), precipitation=precip, etp=etp)
    with (
        patch.object(
            data_step, "compute_soil_forcings", wraps=data_step.compute_soil_forcings
        ) as compute,
        patch.object(data_step, "apply_recharge_load_result_to_flow"),
        patch.object(data_step, "apply_etp_load_result_to_flow"),
    ):
        soil = data_step._bind_soil_recharge_etp(parent, _soil_window(days))
    assert compute.call_count == 1

    fork = WorkflowContext(
        cfg=SimpleNamespace(
            flow=_soil_flow_config(SoilReservoirConfig(ru=200.0, spinup="none")),
            mesh=None,
            workspace=SimpleNamespace(products_cap_mb=1, project_root=tmp_path),
        ),
        config_path=parent.config_path,
        raw_toml={},
    )
    fork.setup = copy.copy(parent.setup)
    fork.setup.workspace = SimpleNamespace()
    fork.loaded_data = parent.loaded_data
    fork.execution.lightweight = True
    fork.execution.resumed = False
    fork.run_dir = None
    with (
        patch.object(
            data_step, "compute_soil_forcings", wraps=data_step.compute_soil_forcings
        ) as compute,
        patch.object(data_step, "apply_recharge_load_result_to_flow"),
        patch.object(data_step, "apply_etp_load_result_to_flow"),
    ):
        recomputed = data_step._bind_soil_recharge_etp(fork, _soil_window(days))
    assert compute.call_count == 1
    assert recomputed is not soil
    assert parent.setup.soil_forcings is soil
    assert list(products_root(tmp_path).rglob("soil.npz")) == []
