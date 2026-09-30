"""In soil mode, ``step_persist_forcings`` writes where a SIM2 run would."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import xarray as xr

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.physics.hydrology.soil_reservoir.kernel import (
    SoilParameters,
    full_soil,
    run_soil_balance,
)
from hydromodpy.workflow.steps.prepare_solver.prepare import step_persist_forcings
from tests._helpers.fixtures_catalog import simulation_catalog

_N_DAYS = 4
_N_COLUMNS = 2
_X = np.array([0.0, 100.0])


@dataclass
class _Loaded:
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


def _register_sim(catalog) -> str:
    sid = str(uuid4())
    reg = catalog.register_simulation(
        sid, project="test", solver="modflow6", n_cells=_N_COLUMNS, n_layers=1, n_timesteps=_N_DAYS
    )
    if reg.zarr is not None:
        reg.zarr.close()
    return sid


def test_the_gridded_recharge_lands_where_sim2_would(tmp_path):
    soil = _make_soil()
    ctx = SimpleNamespace(
        sim_id=None,
        loaded_data=_Loaded(),
        setup=SimpleNamespace(soil_forcings=soil),
    )

    with simulation_catalog(tmp_path / "ws") as catalog:
        sid = _register_sim(catalog)
        ctx.sim_id = sid
        step_persist_forcings(ctx, store=catalog)

        sz = catalog.open_zarr(sid)
        try:
            forcing = sz.root["forcing"]
            assert "recharge_recharge" in forcing
            assert "recharge" not in forcing
            assert "_watershed" in forcing["runoff"]
            assert "soil" in forcing
        finally:
            sz.close()


def test_the_soil_budget_view_has_a_row_per_column_and_year_plus_the_basin(tmp_path):
    soil = _make_soil()
    ctx = SimpleNamespace(
        sim_id=None,
        loaded_data=_Loaded(),
        setup=SimpleNamespace(soil_forcings=soil),
    )

    with simulation_catalog(tmp_path / "ws") as catalog:
        sid = _register_sim(catalog)
        ctx.sim_id = sid
        step_persist_forcings(ctx, store=catalog)

        paths = list((tmp_path / "ws" / "runs").glob("*/tables.parquet/soil_budget.parquet"))
        assert len(paths) == 1
        table = pq.read_table(paths[0])
        assert table.num_rows == 3  # 2 columns + 1 basin row, one calendar year
        assert set(table.column("column_id").to_pylist()) == {"0.0", "1.0", "_watershed"}


def test_nothing_is_written_without_a_sim_id():
    soil = _make_soil()
    ctx = SimpleNamespace(
        sim_id=None, loaded_data=_Loaded(), setup=SimpleNamespace(soil_forcings=soil)
    )
    # No store call should be reachable: step_persist_forcings returns at once.
    step_persist_forcings(ctx, store=None)
