"""Runtime SFR binding: delineate once, cache on setup, attach onto the flow."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import box

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.physics.flow.sinks_sources.sfr import FlowReachNetworkConfig
from hydromodpy.physics.flow.structure_binders import apply_sfr_network_to_flow
from hydromodpy.workflow.steps.data import bind_sfr_network_traces

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
    payload = {"stream_threshold_cells": 50, "outflow_to_lake": 1}
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


def _run_state(tmp_path: Path, network: FlowReachNetworkConfig, **geo_kwargs) -> SimpleNamespace:
    return SimpleNamespace(
        setup=SimpleNamespace(
            flow=_flow_double(network),
            geographic=_geographic_double(tmp_path, **geo_kwargs),
            sfr_reach_traces=None,
        )
    )


def test_bind_sfr_network_traces_attaches_and_caches(tmp_path: Path) -> None:
    run_state = _run_state(tmp_path, _network_config())
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
    run_state = _run_state(tmp_path, _network_config())
    run_state.setup.flow.active_bc = ["lake"]
    bind_sfr_network_traces(run_state)
    assert run_state.setup.sfr_reach_traces is None


def test_bind_sfr_network_traces_rejects_threshold_mismatch(tmp_path: Path) -> None:
    run_state = _run_state(tmp_path, _network_config(stream_threshold_cells=80))
    with pytest.raises(ConfigError, match="threshold"):
        bind_sfr_network_traces(run_state)


def test_bind_sfr_network_traces_requires_link_raster(tmp_path: Path) -> None:
    run_state = _run_state(tmp_path, _network_config())
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
    run_state = _run_state(tmp_path, _network_config())
    bind_sfr_network_traces(run_state)
    tops = [reach.rtp for reach in run_state.setup.sfr_reach_traces["net0"].reaches]
    assert tops
    assert min(tops) > 0.0


def test_bind_sfr_network_traces_names_a_missing_model_top(tmp_path: Path) -> None:
    run_state = _run_state(tmp_path, _network_config())
    run_state.setup.geographic._top_dem_path = None
    with pytest.raises(ConfigError, match="model-top DEM"):
        bind_sfr_network_traces(run_state)
