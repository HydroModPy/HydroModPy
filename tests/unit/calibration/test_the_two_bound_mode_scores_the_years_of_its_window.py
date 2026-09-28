"""The two-bound mode scores only the complete years the phase's scoring window holds.

A transient run that starts with a spin-up year scores it like the others
unless a window leaves it out. The trial context is faked and everything it
feeds is real: the V-valley mesh, a mapped network read off disk, and a
monthly release stack whose head of network moves over the year.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.config import validate_calib_output
from hydromodpy.calibration.metrics import solver_extract as _solver_extract
from hydromodpy.calibration.metrics.solver_extract import extract_outputs
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.core.exceptions import ObjectiveError
from tests._helpers.ugrid_meshes import quad_mesh
from tests._helpers.v_valley import (
    AXIS_COL,
    CELL_SIZE,
    FIRST_OBSERVED_ROW,
    N_CELLS,
    N_COLS,
    N_ROWS,
    build_bench,
    simulated_network,
)

gpd = pytest.importorskip("geopandas")
pytest.importorskip("shapely")

CRS = "EPSG:2154"


@pytest.fixture(scope="module")
def bench():
    return build_bench()


@pytest.fixture(scope="module")
def mapped(tmp_path_factory):
    from shapely.geometry import LineString

    line = LineString(
        [
            ((AXIS_COL + 0.5) * CELL_SIZE, (row + 0.5) * CELL_SIZE)
            for row in range(FIRST_OBSERVED_ROW, N_ROWS)
        ]
    )
    path = tmp_path_factory.mktemp("maps") / "complete.gpkg"
    gpd.GeoDataFrame(geometry=[line], crs=CRS).to_file(path, driver="GPKG")
    return path


def _monthly_bounds(first_year: int, n_years: int) -> list[pd.Timestamp]:
    return list(pd.date_range(f"{first_year}-01-01", periods=12 * n_years + 1, freq="MS"))


def _thresholds(n_years: int) -> np.ndarray:
    """A seasonal cut, wetter in the first year so that year weighs on the masks."""
    month = np.arange(12)
    season = 0.5 * (1.0 + np.cos(2.0 * np.pi * (month - 1) / 12.0))
    year = np.exp(np.log(900.0) + season * (np.log(8.0) - np.log(900.0)))
    stack = np.tile(year, n_years)
    stack[:12] = 3.0
    return stack


def _stack(bench, thresholds) -> np.ndarray:
    return np.vstack(
        [np.where(simulated_network(bench, float(value)), 1.0e-6, 0.0) for value in thresholds]
    )


def _fake_ctx(bench, bounds):
    vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
    planar_mesh = SimpleNamespace(
        vertices=vertices, flat_connectivity=connectivity, n_cells=N_CELLS
    )
    rows, cols = np.divmod(np.arange(N_CELLS), N_COLS)
    centroids = np.column_stack([(cols + 0.5) * CELL_SIZE, (rows + 0.5) * CELL_SIZE])
    solver_mesh = SimpleNamespace(
        top=bench.elevation,
        botm=np.zeros((1, N_CELLS)),
        inactive_mask=np.zeros((1, N_CELLS), dtype=bool),
        planar_mesh=planar_mesh,
        n_cells=N_CELLS,
        cell_areas=lambda: np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
        cell_centroids=lambda: centroids,
    )
    return SimpleNamespace(
        run=SimpleNamespace(id="r1", solver="modflow6"),
        state=SimpleNamespace(setup=SimpleNamespace(geographic=SimpleNamespace(crs_project=CRS))),
        setup=SimpleNamespace(time_grid=SimpleNamespace(boundaries=bounds)),
        model=SimpleNamespace(solver_mesh=solver_mesh, recharge=1.0e-8),
    )


class _StackAdapter:
    def __init__(self, stack: np.ndarray) -> None:
        self.stack = stack

    def extract_observables(self, ctx, store, requests, *, time_index=None):
        del ctx, store
        return {
            request.id: ObservableResult(
                request_id=request.id,
                values=self.stack if request.times == "all" else self.stack[-1],
                units="m3 s-1",
                times=time_index if request.times == "all" else None,
            )
            for request in requests
        }


def _output(mapped):
    return validate_calib_output(
        {
            "support": "network",
            "stream_geometry_path": str(mapped),
            "diagonal_neighbors": True,
            "tau_specific_ratio": 0.0,
            "extent": {"visible_flow": "0 L/s"},
        }
    )


def _score(monkeypatch, bench, mapped, stack, bounds, window=None):
    ctx = _fake_ctx(bench, bounds)
    adapter = _StackAdapter(stack)
    monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, ctx))
    return extract_outputs(ctx, {"net": _output(mapped)}, scoring_window=window).diagnostics


SPIN_UP_RUN = _monthly_bounds(2000, 3)
WINDOW = (pd.Timestamp("2001-01-01"), pd.Timestamp("2002-12-31"))


def test_without_a_window_the_spin_up_year_is_scored(monkeypatch, bench, mapped) -> None:
    scored = _score(monkeypatch, bench, mapped, _stack(bench, _thresholds(3)), SPIN_UP_RUN)
    assert scored["net.n_years_scored"] == 3.0
    assert scored["net.year_scored_y2000"] == 1.0
    assert scored["net.n_years_outside_window"] == 0.0


def test_the_window_scores_the_years_it_holds_and_says_so(monkeypatch, bench, mapped) -> None:
    scored = _score(monkeypatch, bench, mapped, _stack(bench, _thresholds(3)), SPIN_UP_RUN, WINDOW)
    assert scored["net.n_years_scored"] == 2.0
    assert (scored["net.first_year_scored"], scored["net.last_year_scored"]) == (2001.0, 2002.0)
    assert scored["net.year_scored_y2000"] == 0.0
    assert scored["net.year_scored_y2001"] == scored["net.year_scored_y2002"] == 1.0
    assert scored["net.n_years_outside_window"] == 1.0
    assert "net.J_signed_maximal_y2000" not in scored
    assert "net.J_signed_maximal_y2001" in scored


def test_a_windowed_run_scores_what_the_run_without_its_spin_up_scores(
    monkeypatch, bench, mapped
) -> None:
    thresholds = _thresholds(3)
    windowed = _score(monkeypatch, bench, mapped, _stack(bench, thresholds), SPIN_UP_RUN, WINDOW)
    trimmed = _score(
        monkeypatch, bench, mapped, _stack(bench, thresholds[12:]), _monthly_bounds(2001, 2)
    )
    whole = _score(monkeypatch, bench, mapped, _stack(bench, thresholds), SPIN_UP_RUN)
    assert windowed["net.J_signed_maximal"] == pytest.approx(trimmed["net.J_signed_maximal"])
    # Left in, the wet spin-up year is a year of its own the quorum counts.
    assert whole["net.n_years_required"] == 2.0
    assert windowed["net.n_years_required"] == 1.0
    assert whole["net.n_network_sim_maximal_y2000"] > windowed["net.n_network_sim_maximal_y2001"]


def test_a_time_zone_on_the_window_is_read_in_utc(monkeypatch, bench, mapped) -> None:
    window = (pd.Timestamp("2001-01-01", tz="UTC"), pd.Timestamp("2002-12-31", tz="UTC"))
    scored = _score(monkeypatch, bench, mapped, _stack(bench, _thresholds(3)), SPIN_UP_RUN, window)
    assert scored["net.n_years_scored"] == 2.0


def test_a_window_holding_no_whole_year_is_refused_by_name(monkeypatch, bench, mapped) -> None:
    window = (pd.Timestamp("2001-02-01"), pd.Timestamp("2001-11-30"))
    with pytest.raises(ObjectiveError, match=r"scoring_window .* leaves out 2000, 2001, 2002"):
        _score(monkeypatch, bench, mapped, _stack(bench, _thresholds(3)), SPIN_UP_RUN, window)


def test_a_window_does_not_touch_one_state(monkeypatch, bench, mapped) -> None:
    ctx = _fake_ctx(bench, None)
    adapter = _StackAdapter(_stack(bench, [200.0]))
    monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, ctx))
    output = validate_calib_output(
        {
            "support": "network",
            "stream_geometry_path": str(mapped),
            "diagonal_neighbors": True,
            "tau_specific_ratio": 0.0,
        }
    )
    plain = extract_outputs(ctx, {"net": output}).diagnostics
    windowed = extract_outputs(ctx, {"net": output}, scoring_window=WINDOW).diagnostics
    assert windowed["net.J_signed"] == plain["net.J_signed"]
