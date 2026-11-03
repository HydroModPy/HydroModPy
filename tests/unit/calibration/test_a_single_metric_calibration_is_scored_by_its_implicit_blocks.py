"""``variable`` + ``objective`` is scored by the block route, at the same cost.

Decision m10 of the audit of 2026-10-20: the one-line form becomes, once the
records are loaded, one implicit output and one implicit block per scored
station, and the block route scores them. ``PINNED`` holds the costs the old
single-metric route (``StationScorer`` and ``scalar.score``) returned on these
exact series at 4ca07e106, so a cost that moves is caught here. One station
reproduces the old cost to the bit; several are averaged by the block weights,
which may round differently in the last place.

What the old route did not publish is now there: the pairs each cost was
scored on, which ``scored`` of ``session.json`` is read from.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.metrics import composite
from hydromodpy.calibration.metrics.composite import build_metric_extractor
from hydromodpy.calibration.runners.recap import scored_samples
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.core.time.period_aggregation import period_edges

FIRST = pd.Timestamp("2000-01-01")
# A monthly run stamps each period at the first day of the next month.
STAMPS = pd.date_range("2000-02-01", periods=36, freq="MS")
BOUNDARIES = tuple(period_edges(STAMPS, start=FIRST))
WINDOW = (pd.Timestamp("2001-01-01"), None)

PINNED = {
    "discharge_nse_log_window": 0.17866174604070295,
    "discharge_kge_warmup": 0.18111555222173215,
    "discharge_followed_gauge": 0.7678948602751097,
    "head_rmse_two": 0.3228777051000766,
    "head_nse_three": 0.04659631074723684,
    "head_one_unplaced": 0.2619100296541183,
    "lake_reservoir": 19.937386769421664,
    "lake_nse_seasonal": 39.54011084560426,
}


def _daily_record(seed: float) -> pd.DataFrame:
    days = pd.date_range(FIRST, STAMPS[-1] - pd.Timedelta(1, unit="D"), freq="D")
    t = np.arange(days.size, dtype=float)
    values = 1.0 + 0.6 * np.cos(2.0 * np.pi * t / 365.25 + seed) + 0.2 * np.sin(t / 17.0)
    return pd.DataFrame({"datetime": days, "value": values})


def _state_record(seed: float) -> pd.DataFrame:
    months = np.arange(STAMPS.size, dtype=float)
    values = 50.0 + 2.0 * np.cos(2.0 * np.pi * months / 12.0 + seed) + 0.3 * np.sin(months)
    return pd.DataFrame({"datetime": STAMPS, "value": values})


def _simulated(seed: float, level: float = 1.0) -> np.ndarray:
    months = np.arange(STAMPS.size, dtype=float)
    return level * (1.0 + 0.5 * np.cos(2.0 * np.pi * months / 12.0 + seed)) + 0.1 * np.cos(
        3.0 * months + seed
    )


def _ctx(family: str, records: list[SimpleNamespace]) -> SimpleNamespace:
    loaded = {"hydrometry": None, "piezometry": None, "lake_levels": None, "runoff": None}
    loaded[family] = SimpleNamespace(points=records)
    return SimpleNamespace(
        setup=SimpleNamespace(
            time_grid=SimpleNamespace(boundaries=BOUNDARIES), geographic=None, cell_mesh=None
        ),
        loaded_data=SimpleNamespace(**loaded),
    )


def _serve(monkeypatch, answers: dict[str, np.ndarray]) -> None:
    """Answer every request the producers make from ``answers``, keyed by request id."""

    class _Adapter:
        def extract_observables(self, ctx, store, requests, *, time_index=None):
            del ctx, store, time_index
            return {
                request.id: ObservableResult(
                    request_id=request.id, values=answers[request.id], units="-", times=STAMPS
                )
                for request in requests
                if request.id in answers
            }

    monkeypatch.setattr(
        composite,
        "resolve_flow_adapter",
        lambda ctx: (
            _Adapter(),
            SimpleNamespace(run=SimpleNamespace(solver="modflow6"), model=None),
        ),
    )


def _state(seed: float) -> np.ndarray:
    months = np.arange(STAMPS.size, dtype=float)
    return 50.0 + 1.8 * np.cos(2.0 * np.pi * months / 12.0 + seed) + 0.2 * np.cos(3.0 * months)


def _gauge(station: str, seed: float) -> SimpleNamespace:
    return SimpleNamespace(station_id=station, variable="discharge", data=_daily_record(seed))


def _piezometer(station: str, seed: float, cell=(3, 4)) -> SimpleNamespace:
    return SimpleNamespace(
        station_id=station, variable="head", data=_state_record(seed), cell_ij=cell
    )


def _lake(station: str, seed: float) -> SimpleNamespace:
    return SimpleNamespace(station_id=station, variable="lake_level", data=_state_record(seed))


def _pairs(components: dict[str, float]) -> dict[str, int]:
    """Return the pairs a session would keep, by output."""
    return {item.output: item.n for item in scored_samples(components, case_id="case")}


def _score(variable: str, objective: str, ctx, **kwargs) -> tuple[float, dict[str, float]]:
    metric_fn = build_metric_extractor(variable, objective, ctx, **kwargs)
    cost, components = metric_fn(ctx, objective=objective, variable=variable)
    return float(cost), dict(components)


def test_a_gauge_on_nse_log_and_a_window_costs_what_it_cost(monkeypatch) -> None:
    _serve(monkeypatch, {"catchment": _simulated(0.3)})
    ctx = _ctx("hydrometry", [_gauge("NANCON", 0.0)])

    cost, components = _score("discharge", "nse_log", ctx, scoring_window=WINDOW)

    assert cost == PINNED["discharge_nse_log_window"]
    assert components["nse_log@NANCON.raw_cost"] == cost
    assert _pairs(components)["discharge@NANCON"] == 24


def test_a_burn_in_in_samples_still_applies(monkeypatch) -> None:
    _serve(monkeypatch, {"catchment": _simulated(0.3)})
    ctx = _ctx("hydrometry", [_gauge("NANCON", 0.0)])

    cost, components = _score("discharge", "kge", ctx, warmup_periods=3)

    assert cost == PINNED["discharge_kge_warmup"]
    # The pairs are counted before the burn-in, the values after it.
    assert components["discharge@NANCON.n_paired"] == 36.0
    assert components["kge@NANCON.n_values"] == 33.0


def test_the_followed_gauge_alone_is_scored(monkeypatch) -> None:
    _serve(monkeypatch, {"catchment": _simulated(0.3)})
    ctx = _ctx("hydrometry", [_gauge("OUTLET", 0.0), _gauge("UP", 1.0)])

    cost, components = _score("discharge", "nse", ctx, observed_station_id="UP")

    assert cost == PINNED["discharge_followed_gauge"]
    assert set(_pairs(components)) == {"discharge@UP"}


def test_two_heads_average_as_they_did(monkeypatch) -> None:
    _serve(monkeypatch, {"PZ1": _state(0.1), "PZ2": _state(0.9)})
    ctx = _ctx("piezometry", [_piezometer("PZ1", 0.0), _piezometer("PZ2", 1.0)])

    cost, components = _score("head", "rmse", ctx)

    assert cost == PINNED["head_rmse_two"]
    assert cost == pytest.approx(
        0.5 * (components["rmse@PZ1.raw_cost"] + components["rmse@PZ2.raw_cost"]), rel=1e-15
    )


def test_three_heads_average_to_the_last_place(monkeypatch) -> None:
    _serve(
        monkeypatch,
        {
            "PZ1": _state(0.1),
            "PZ2": _state(0.9),
            "PZ3": _state(2.0),
        },
    )
    ctx = _ctx(
        "piezometry",
        [_piezometer("PZ1", 0.0), _piezometer("PZ2", 1.0), _piezometer("PZ3", 2.0)],
    )

    cost, _ = _score("head", "nse", ctx)

    assert cost == pytest.approx(PINNED["head_nse_three"], rel=1e-15, abs=0.0)


def test_a_piezometer_the_mesh_cannot_place_is_left_out(monkeypatch) -> None:
    _serve(monkeypatch, {"PZ1": _state(0.1)})
    ctx = _ctx("piezometry", [_piezometer("PZ1", 0.0), _piezometer("NOWHERE", 1.0, cell=None)])

    cost, components = _score("head", "mae", ctx)

    assert cost == PINNED["head_one_unplaced"]
    assert set(_pairs(components)) == {"head@PZ1"}


@pytest.mark.parametrize(
    ("metric", "pin"), [("reservoir", "lake_reservoir"), ("nse_seasonal", "lake_nse_seasonal")]
)
def test_a_lake_on_a_seasonal_kernel_costs_what_it_cost(monkeypatch, metric, pin) -> None:
    _serve(monkeypatch, {"lac0": _state(0.4)})
    ctx = _ctx("lake_levels", [_lake("lac0", 0.0)])

    cost, components = _score("lake_level", metric, ctx)

    assert np.isfinite(cost)
    assert cost == PINNED[pin]
    assert _pairs(components)["lake_level@lac0"] == 36
