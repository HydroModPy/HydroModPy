"""Persisting the forcings of the run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
import xarray as xr
from pydantic import BaseModel, ConfigDict
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
from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME
from hydromodpy.core.state.run_state import LoadedDataContext
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.model.forcing.soil_config import SoilReservoirConfig
from hydromodpy.model.soil.kernel import SoilParameters, full_soil, run_soil_balance
from hydromodpy.results.catalog.registration import reserve_version_dirname
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.storage.attempt import claim_run_directory
from hydromodpy.schema.lineage import Lineage
from hydromodpy.workflow.steps.data import apply_structural_updates_from_data
from hydromodpy.workflow.steps.prepare_solver.dispatch import bind_run_directory, initial_facts
from hydromodpy.workflow.steps.prepare_solver.facts import collect_effective_config_snapshot
from hydromodpy.workflow.steps.prepare_solver.forcings import step_persist_forcings
from tests._helpers.run_stores import open_run_store
from tests.unit.workflow.steps._helpers import (
    hydrography_load_result,
    write_network_vector,
    write_watershed,
)

# --- test_persist_watershed_forcing ---
# step_persist_forcings: watershed-mean station series for gridded forcings.


@dataclass
class _Loaded:
    runoff: object | None = None
    precipitation: object | None = None
    recharge: object | None = None


def _runoff_field_record(
    values: np.ndarray,
    times: pd.DatetimeIndex,
    variable: str = "runoff",
) -> FieldRecord:
    ds = xr.Dataset(
        {variable: (("time", "y", "x"), np.asarray(values, dtype="float64"))},
        coords={"time": times, "y": [0.0, 1.0], "x": [0.0, 1.0]},
    )
    return FieldRecord(
        variable=variable,
        source="sim2",
        unit="mm/day",
        data=ds,
        bbox=(0.0, 0.0, 1.0, 1.0),
        crs="EPSG:2154",
        date_start=times[0].to_pydatetime(),
        date_end=times[-1].to_pydatetime(),
        frequency="D",
    )


def _ctx(sid: str, loaded: _Loaded) -> SimpleNamespace:
    return SimpleNamespace(sim_id=sid, loaded_data=loaded)


def test_gridded_runoff_persists_watershed_mean(tmp_path):
    times = pd.date_range("2020-01-01", periods=3, freq="D")
    frames = np.arange(12, dtype="float64").reshape(3, 2, 2)
    loaded = _Loaded(runoff=LoadResult(fields=[_runoff_field_record(frames, times)]))

    with open_run_store(tmp_path / "ws", n_cells=4, n_timesteps=3) as catalog:
        sid = catalog.sim_id
        step_persist_forcings(_ctx(sid, loaded), store=catalog)

        sz = catalog.open_zarr(sid)
        try:
            station = sz.root["forcing"]["runoff"]["catchment"]
            values = np.asarray(station["values"][:], dtype="float64")
            # Spatial mean of each 2x2 frame.
            np.testing.assert_allclose(values, [1.5, 5.5, 9.5])
            stamps = np.asarray(station["timestamps"][:]).view("datetime64[ns]")
            assert pd.DatetimeIndex(stamps).equals(times)
            assert station.attrs["unit"] == "mm/day"
        finally:
            sz.close()


def test_station_backed_runoff_skips_watershed_mean(tmp_path):
    # Point records already persist per station; no _watershed duplicate.
    times = pd.date_range("2020-01-01", periods=3, freq="D")
    df = pd.DataFrame({"datetime": times, "value": [1.0, 2.0, 3.0]})
    point = PointRecord(
        station_id="sta1",
        variable="runoff",
        source="file",
        unit="mm/day",
        frequency="D",
        data=df,
        date_start=times[0].to_pydatetime(),
        date_end=times[-1].to_pydatetime(),
    )
    loaded = _Loaded(runoff=LoadResult(points=[point]))

    with open_run_store(tmp_path / "ws", n_cells=4, n_timesteps=3) as catalog:
        sid = catalog.sim_id
        step_persist_forcings(_ctx(sid, loaded), store=catalog)

        sz = catalog.open_zarr(sid)
        try:
            runoff_grp = sz.root["forcing"]["runoff"]
            assert "sta1" in runoff_grp
            assert "catchment" not in runoff_grp
        finally:
            sz.close()


def test_a_refused_reduction_stops_the_persist_step(tmp_path):
    # A runoff day without any valid pixel has no watershed mean: the step
    # refuses it by name instead of persisting the run without it.
    times = pd.date_range("2020-01-01", periods=2, freq="D")
    frames = np.ones((2, 2, 2), dtype="float64")
    frames[1] = np.nan
    loaded = _Loaded(runoff=LoadResult(fields=[_runoff_field_record(frames, times)]))

    with open_run_store(tmp_path / "ws", n_cells=4, n_timesteps=3) as catalog:
        with pytest.raises(DataContractViolation, match="no valid pixel in time step 1"):
            step_persist_forcings(_ctx(catalog.sim_id, loaded), store=catalog)


@pytest.mark.parametrize(("factor", "means"), [(1.0, [1.5, 5.5, 9.5]), (2.0, [3.0, 11.0, 19.0])])
def test_the_run_keeps_the_recharge_it_solved(tmp_path, factor, means):
    times = pd.date_range("2020-01-01", periods=3, freq="D")
    frames = np.arange(12, dtype="float64").reshape(3, 2, 2)
    record = _runoff_field_record(frames, times, variable="recharge")
    loaded = _Loaded(recharge=LoadResult(fields=[record]))
    declared = SimpleNamespace(recharge=SimpleNamespace(factor=factor))
    cfg = SimpleNamespace(flow=SimpleNamespace(sinks_sources=declared))

    with open_run_store(tmp_path / "ws", n_cells=4, n_timesteps=3) as catalog:
        sid = catalog.sim_id
        ctx = SimpleNamespace(sim_id=sid, loaded_data=loaded, cfg=cfg)
        step_persist_forcings(ctx, store=catalog)

        sz = catalog.open_zarr(sid)
        try:
            station = sz.root["forcing"]["recharge"]["catchment"]
            np.testing.assert_allclose(station["values"][:], means)
        finally:
            sz.close()


# --- test_a_soil_run_persists_its_recharge_where_sim2_would ---
# In soil mode, ``step_persist_forcings`` writes where a SIM2 run would.

_N_DAYS = 4


_N_COLUMNS = 2


_X = np.array([0.0, 100.0])


@dataclass
class _SoilLoaded:
    recharge: object | None = None
    runoff: object | None = None
    precipitation: object | None = None


def _field_record(variable: str, values: np.ndarray, days: np.ndarray) -> LoadResult:
    ds = xr.Dataset(
        {variable: (("time", "y", "x"), values.reshape(_N_DAYS, 1, _N_COLUMNS))},
        coords={"time": days, "y": [0.0], "x": _X},
    )
    return LoadResult(
        fields=[
            FieldRecord(
                variable=variable,
                source="soil_reservoir",
                unit="mm/day",
                data=ds,
                bbox=(0.0, 0.0, 100.0, 0.0),
                crs="EPSG:2154",
                date_start=pd.Timestamp(days[0]).to_pydatetime(),
                date_end=pd.Timestamp(days[-1]).to_pydatetime(),
                frequency="D",
            )
        ]
    )


def _make_soil() -> SimpleNamespace:
    rng = np.random.default_rng(0)
    precipitation = rng.uniform(0.0, 10.0, size=(_N_DAYS, _N_COLUMNS))
    etp = np.full((_N_DAYS, _N_COLUMNS), 2.0)
    params = SoilParameters(
        ru_mm=np.array([120.0, 150.0]),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
    )
    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))
    days = pd.date_range("2020-01-01", periods=_N_DAYS, freq="D").values.astype("datetime64[ns]")
    years = days.astype("datetime64[Y]").astype(int) + 1970

    columns = SimpleNamespace(
        cell_index=np.array([0, 1], dtype="int32"),
        class_index=np.zeros(_N_COLUMNS, dtype="int32"),
        x=_X,
        y=np.zeros(_N_COLUMNS),
        cell_fraction=np.ones(_N_COLUMNS),
        basin_weight=np.full(_N_COLUMNS, 1.0 / _N_COLUMNS),
    )
    return SimpleNamespace(
        recharge=_field_record("recharge", fluxes.recharge, days),
        residual_etp=_field_record("etp", fluxes.residual_etp, days),
        runoff=_field_record("runoff", fluxes.runoff, days),
        days=days,
        years=years,
        precipitation=precipitation,
        etp=etp,
        fluxes=fluxes,
        columns=columns,
        config=SoilReservoirConfig(ru=120.0),
        parameters=params,
        spinup_cycles=0,
        never_full_columns=0,
        crs="EPSG:2154",
    )


def test_the_gridded_recharge_lands_where_sim2_would(tmp_path):
    soil = _make_soil()
    ctx = SimpleNamespace(
        sim_id=None,
        loaded_data=_SoilLoaded(),
        setup=SimpleNamespace(soil_forcings=soil),
    )

    with open_run_store(tmp_path / "ws", n_cells=_N_COLUMNS, n_timesteps=_N_DAYS) as catalog:
        sid = catalog.sim_id
        ctx.sim_id = sid
        step_persist_forcings(ctx, store=catalog)

        sz = catalog.open_zarr(sid)
        try:
            forcing = sz.root["forcing"]
            assert "recharge_recharge" in forcing
            assert "catchment" in forcing["recharge"]
            assert "catchment" in forcing["runoff"]
            assert "soil" in forcing
        finally:
            sz.close()


def test_the_soil_budget_view_has_a_row_per_column_and_year_plus_the_basin(tmp_path):
    soil = _make_soil()
    ctx = SimpleNamespace(
        sim_id=None,
        loaded_data=_SoilLoaded(),
        setup=SimpleNamespace(soil_forcings=soil),
    )

    with open_run_store(tmp_path / "ws", n_cells=_N_COLUMNS, n_timesteps=_N_DAYS) as catalog:
        sid = catalog.sim_id
        ctx.sim_id = sid
        step_persist_forcings(ctx, store=catalog)

        paths = list((tmp_path / "ws" / "runs").glob("*/tables.parquet/soil_budget.parquet"))
        assert len(paths) == 1
        table = pq.read_table(paths[0])
        assert table.num_rows == 3  # 2 columns + 1 basin row, one calendar year
        assert set(table.column("column_id").to_pylist()) == {"0.0", "1.0", "catchment"}


def test_nothing_is_written_without_a_sim_id():
    soil = _make_soil()
    ctx = SimpleNamespace(
        sim_id=None, loaded_data=_SoilLoaded(), setup=SimpleNamespace(soil_forcings=soil)
    )
    # No store call should be reachable: step_persist_forcings returns at once.
    step_persist_forcings(ctx, store=None)


class _FakeZarr:
    def __init__(self) -> None:
        self.fields: list[str] = []

    def write_forcing_field(self, name, data, *, unit, source) -> None:
        _ = data, unit, source
        self.fields.append(str(name))

    def close(self) -> None:
        pass


class _FakeStore:
    def __init__(self) -> None:
        self.zarr = _FakeZarr()
        self.feature_names: list[str] = []
        self.feature_crs: dict[str, str | None] = {}
        self.metadata: dict[str, object] = {}

    def open_zarr(self, sim_id: str):
        _ = sim_id
        return self.zarr

    def write_geographic_feature(self, sim_id: str, feature_name: str, gdf) -> None:
        _ = sim_id, gdf
        self.feature_names.append(str(feature_name))
        self.feature_crs[str(feature_name)] = None if gdf.crs is None else str(gdf.crs)

    def write_geographic_metadata(self, sim_id: str, metadata: dict[str, object]) -> None:
        _ = sim_id
        self.metadata.update(metadata)


def test_step_persist_forcings_writes_reference_network_feature(tmp_path: Path):
    streams_path = write_network_vector(tmp_path / "streams.shp")
    watershed_path = write_watershed(tmp_path / "watershed.shp")
    reference = HydrographicNetwork(
        role="reference",
        source_kind="hydrography_loaded",
        vector_path=str(streams_path),
        watershed_shp=str(watershed_path),
    )
    features = GeographicDerivedFeatures(
        surface_topo=object(),
        boundaries=GeographicBoundaryFeatures(
            watershed_shp=str(watershed_path),
            watershed_box_shp=None,
            box_buff_shp="box_buff.shp",
        ),
        hydrographic_networks=HydrographicNetworks(reference=reference),
    )
    store = _FakeStore()
    ctx = SimpleNamespace(
        sim_id="sim-1",
        loaded_data=LoadedDataContext(
            hydrography=hydrography_load_result(
                vector_path=streams_path,
                raster_path=tmp_path / "streams.tif",
                array=np.asarray([[1.0, 0.0]], dtype=float),
            )
        ),
        setup=SimpleNamespace(geographic_features=features),
    )

    step_persist_forcings(ctx, store=store)

    assert "hydrography_streams" in store.zarr.fields
    assert HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME in store.feature_names


def test_persist_geographic_to_store_writes_generated_network_canonical_name(tmp_path: Path):
    network_path = write_network_vector(tmp_path / "river_network.shp")
    watershed_path = write_watershed(tmp_path / "watershed.shp")
    generated = HydrographicNetwork(
        role="generated",
        source_kind="geographic_generated",
        vector_path=str(network_path),
        watershed_shp=str(watershed_path),
    )
    geographic = SimpleNamespace(
        watershed_dem=None,
        watershed_fill=None,
        watershed_shp=None,
        box_buff=None,
        watershed_contour_shp=None,
        get_geographic_derived_features=lambda: GeographicDerivedFeatures(
            surface_topo=object(),
            boundaries=GeographicBoundaryFeatures(
                watershed_shp=str(watershed_path),
                watershed_box_shp=None,
                box_buff_shp="box_buff.shp",
            ),
            hydrographic_networks=HydrographicNetworks(generated=generated),
        ),
    )
    store = _FakeStore()

    persist_geographic_to_store(geographic, store, sim_id="sim-2")

    assert HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME in store.feature_names
    assert "river_network" not in store.feature_names


# --- test_store_handle_lifecycle ---
# The run directory is bound once, by the step that opens the run.
#
# ``bind_run_directory`` reads the identity of the attempt off the outcome of
# the directory it is handed, or claims the directory of the case when it is
# handed none; the facts of the attempt are built from the context, written by
# the store that opens on them, and no handle survives the step.


@dataclass
class _LoadedForcings:
    recharge: object | None = None


class _ClosableZarr:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def test_step_persist_forcings_closes_zarr_when_no_forcings() -> None:
    from hydromodpy.workflow.steps.prepare_solver.forcings import step_persist_forcings

    fake_zarr = _ClosableZarr()
    ctx = SimpleNamespace(sim_id="sim-123", loaded_data=_LoadedForcings())

    step_persist_forcings(ctx, store=SimpleNamespace(open_zarr=lambda _sim_id: fake_zarr))

    assert fake_zarr.close_calls == 1
