"""Factories shared by the scoring tests (metrics, observations, protocols)."""

from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from shapely.geometry import LineString

from hydromodpy.calibration.config import CalibObjectiveBlockDecl, validate_calib_output
from hydromodpy.calibration.metrics import solver_extract as _solver_extract
from hydromodpy.calibration.metrics.series import add_runoff_to_discharge
from hydromodpy.calibration.metrics.solver_extract import extract_outputs
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.simulation.soil.recharge import compute_soil_forcings
from tests._helpers.ugrid_meshes import quad_mesh
from tests._helpers.v_valley import (
    AXIS_COL,
    CELL_SIZE,
    FIRST_OBSERVED_ROW,
    N_CELLS,
    N_COLS,
    N_ROWS,
    simulated_network,
)

CRS = "EPSG:2154"
WINDOW = (pd.Timestamp("2001-01-01"), pd.Timestamp("2002-12-31"))


def axis_line(first_row: int = FIRST_OBSERVED_ROW) -> LineString:
    """The valley axis from `first_row` down to the outlet, in map coordinates."""
    return LineString(
        [
            ((AXIS_COL + 0.5) * CELL_SIZE, (row + 0.5) * CELL_SIZE)
            for row in range(first_row, N_ROWS)
        ]
    )


def axis_file(directory, name: str, first_row: int = FIRST_OBSERVED_ROW, *, extra_col=None):
    """Write the valley axis, and optionally a stray reach, as a stream network."""
    lines = [axis_line(first_row)]
    if extra_col is not None:
        rows = (50, 55)
        lines.append(
            LineString([((extra_col + 0.5) * CELL_SIZE, (r + 0.5) * CELL_SIZE) for r in rows])
        )
    path = directory / name
    gpd.GeoDataFrame(geometry=lines, crs=CRS).to_file(path, driver="GPKG")
    return path


@pytest.fixture(scope="module", name="stream_file")
def stream_file_fixture(tmp_path_factory):
    return axis_file(tmp_path_factory.mktemp("network"), "streams.gpkg")


def make_trial_ctx(
    bench, *, bounds=None, lake_cells=(), networks=None, geographic=None, dam_foot_cells=None
):
    """A trial context exposing exactly what the network criterion reads.

    `networks` holds the hydrographic networks the run carries (reference, generated, ...),
    `geographic` adds fields to the geographic setup.
    """
    vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
    rows, cols = np.divmod(np.arange(N_CELLS), N_COLS)
    centroids = np.column_stack([(cols + 0.5) * CELL_SIZE, (rows + 0.5) * CELL_SIZE])
    solver_mesh = SimpleNamespace(
        top=bench.elevation,
        botm=np.zeros((1, N_CELLS)),
        idomain=np.ones((1, N_CELLS), dtype=int),
        planar_mesh=SimpleNamespace(
            vertices=vertices, flat_connectivity=connectivity, n_cells=N_CELLS
        ),
        n_cells=N_CELLS,
        cell_areas=lambda: np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
        # The points the top was sampled at, which the criterion routes on.
        cell_centers=lambda: centroids,
    )
    ctx = SimpleNamespace(
        run=SimpleNamespace(id="r1", solver="modflow6"),
        state=SimpleNamespace(
            setup=SimpleNamespace(geographic=SimpleNamespace(crs_project=CRS, **(geographic or {})))
        ),
        model=SimpleNamespace(
            solver_mesh=solver_mesh,
            inactive_mask=np.zeros(N_CELLS, dtype=bool),
            recharge=1.0e-8,
            lake_cell_ids_by_lake={"lac": list(lake_cells)} if lake_cells else {},
            dam_foot_cells=dam_foot_cells or {},
        ),
    )
    if networks is not None:
        features = SimpleNamespace(hydrographic_networks=SimpleNamespace(**networks))
        ctx.state.setup.geographic_features = features
    if bounds is not None:
        window = SimpleNamespace(step_value=1, step_unit="month")
        grid = SimpleNamespace(boundaries=bounds, window=window)
        ctx.setup = SimpleNamespace(time_grid=grid)
    return ctx


class StackAdapter:
    """Serves a release stack, whole or at its last row, as the request asks."""

    def __init__(self, stack: np.ndarray) -> None:
        self.stack = stack
        self.requests: list = []

    def extract_observables(self, ctx, store, requests, *, time_index=None):
        del ctx, store
        self.requests.extend(requests)
        served = {}
        for request in requests:
            values = self.stack if request.times == "all" else self.stack[-1]
            times = time_index if request.times == "all" else None
            served[request.id] = ObservableResult(
                request_id=request.id, values=values, units="m3 s-1", times=times
            )
        return served


def network_output(
    path, *, permanent=None, calibrate_on="permanent", map=None, model=None, **fields
):
    """A validated network output reading the stream map at `path`, and `permanent` when given."""
    maps = {"complete": str(path), **(map or {})}
    if permanent is not None:
        maps |= {"permanent": str(permanent), "calibrate_on": calibrate_on}
    return validate_calib_output(
        {
            "support": "network",
            "map": maps,
            "model": {"neighbours": "D8", "seepage_threshold": 0.0, **(model or {})},
            **fields,
        }
    )


def release_stack(bench, thresholds) -> np.ndarray:
    """One release row per threshold, the network the bench draws at that cut."""
    return np.vstack(
        [np.where(simulated_network(bench, float(value)), 1.0e-6, 0.0) for value in thresholds]
    )


def seasonal_thresholds(n_years: int, *, wet_first_year: bool = False) -> np.ndarray:
    """A seasonal cut, optionally wetter in the first year so that year weighs on the masks."""
    month = np.arange(12)
    season = 0.5 * (1.0 + np.cos(2.0 * np.pi * (month - 1) / 12.0))
    year = np.exp(np.log(900.0) + season * (np.log(8.0) - np.log(900.0)))
    stack = np.tile(year, n_years)
    if wet_first_year:
        stack[:12] = 3.0
    return stack


def wire_stack(monkeypatch, bench, stack, bounds=None, *, ctx=None):
    """Make the flow adapter serve `stack`. Returns (ctx, adapter)."""
    adapter = StackAdapter(stack)
    ctx = make_trial_ctx(bench, bounds=bounds) if ctx is None else ctx
    monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, ctx))
    return ctx, adapter


def run_extraction(monkeypatch, bench, outputs, stack, bounds=None, *, ctx=None, **kwargs):
    """Extract `outputs` against a faked adapter serving `stack`. Returns (extracted, adapter)."""
    ctx, adapter = wire_stack(monkeypatch, bench, stack, bounds, ctx=ctx)
    return extract_outputs(ctx, outputs, **kwargs), adapter


def monthly_bounds(first_year: int, n_years: int) -> list[pd.Timestamp]:
    return list(pd.date_range(f"{first_year}-01-01", periods=12 * n_years + 1, freq="MS"))


SPIN_UP_RUN = monthly_bounds(2000, 3)


CATCH_AREA_KM2 = 86.4


def grid_result(variable: str, values: np.ndarray, days: pd.DatetimeIndex) -> LoadResult:
    """A one-pixel gridded field of `values`, one per day."""
    dataset = xr.Dataset(
        {variable: (("time", "y", "x"), values)},
        coords={"time": days, "y": [0.0], "x": [0.0]},
    )
    record = FieldRecord(
        variable=variable,
        source="sim2",
        unit="mm/day",
        data=dataset,
        bbox=(0.0, 0.0, 1.0, 1.0),
        crs=CRS,
        date_start=days[0],
        date_end=days[-1],
    )
    return LoadResult(fields=[record])


def soil_forcings(*, rain: float = 25.0, pulsed: bool = False, **config):
    """Soil forcings of ten days of constant rain, or of a single pulse on the first day."""
    days = pd.date_range("2020-01-01", periods=10, freq="D")
    shape = (days.size, 1, 1)
    rain_values = np.zeros(shape) if pulsed else np.full(shape, rain)
    if pulsed:
        rain_values[0, 0, 0] = rain
    window = ResolvedSimulationTimeWindow(
        start=days[0], end=days[-1], step_value=1, step_unit="day", coverage_policy="error"
    )
    return compute_soil_forcings(
        precipitation=grid_result("precipitation", rain_values, days),
        etp=grid_result("etp", np.zeros(shape), days),
        config=SoilReservoirConfig(ru=100.0, spinup="none", **config),
        window=window,
        model_crs=CRS,
    )


def scored_discharge(forcings) -> pd.Series:
    """The discharge a trial exposing `forcings` would be scored on, once.

    Drops the first day: without a `setup.time_grid` to bound it, the period-mean rule has no
    left edge for the first period and reports a gap there, not a missing wiring of the runoff.
    """
    baseflow = pd.Series(0.0, index=pd.DatetimeIndex(forcings.days[1:]), name="discharge")
    ctx = SimpleNamespace(
        loaded_data=SimpleNamespace(runoff=None),
        setup=SimpleNamespace(
            geographic=SimpleNamespace(catch_area=CATCH_AREA_KM2),
            soil_forcings=SimpleNamespace(runoff=forcings.runoff),
        ),
    )
    return add_runoff_to_discharge(baseflow, ctx)


def boundary_output(boundary_id: str = "outlet", **fields):
    """A validated discharge output on a boundary, observing a station or carrying its values."""
    return validate_calib_output(
        {"variable": "discharge", "support": "boundary", "boundary_id": boundary_id, **fields}
    )


def objective_block(
    name: str, metric: str, uses_outputs: list[str], **fields
) -> CalibObjectiveBlockDecl:
    """A validated objective block scoring `uses_outputs` with `metric`."""
    return CalibObjectiveBlockDecl(name=name, metric=metric, uses_outputs=uses_outputs, **fields)


def adapter_result(request_id: str, values, units: str, *, times=None) -> ObservableResult:
    """What a flow adapter hands back for one request."""
    return ObservableResult(request_id=request_id, values=values, units=units, times=times)


def make_document(
    start: object = "1995-01-01",
    end: object = "2020-12-31",
    *,
    step_unit: str = "day",
    stream: str = "nancon.gpkg",
    sections: dict | None = None,
    **calibration,
) -> dict:
    """A calibration document naming a protocol, one gauge, K and Sy, and one network output."""
    return {
        "simulation": {
            "time": {
                "start_datetime": start,
                "end_datetime": end,
                "step_value": 1,
                "step_unit": step_unit,
            }
        },
        **(sections or {}),
        "data": {"hydrometry": {"sources": [{"station_ids": ["NANCON"]}]}},
        "calibration": {
            "protocol": "matching_hydrographic_network",
            "parameters": {
                "K": {"bounds": [1e-8, 1e-2], "search_space": "log"},
                "Sy": {"bounds": [1e-4, 0.5], "search_space": "log"},
            },
            "outputs": {"seepage_network": {"support": "network", "map": {"complete": stream}}},
            **calibration,
        },
    }


class FakeAdapter:
    """Serves the requested ids from `served` and records what was asked."""

    def __init__(self, served: dict, *, fail_on_cell: bool = False) -> None:
        self.served = served
        self.fail_on_cell = fail_on_cell
        self.requested: list[list[str]] = []

    def extract_observables(self, run_ctx, _unused, requests, *, time_index=None):
        del run_ctx, time_index
        self.requested.append([r.id for r in requests])
        if self.fail_on_cell and any(r.support == "cell" for r in requests):
            raise RuntimeError("this backend serves no per-cell discharge")
        return {r.id: self.served[r.id] for r in requests}
