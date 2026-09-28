"""The calibration progress slide draws any search, labelled with its metric.

Three synthetic sessions stand in for the three searches example 04 runs: a
bisection on K scored on the stream network, a Nelder-Mead simplex on Sy
scored on NSElog, and an Optuna-like sampler on K and Sy scored on both. The
slide must name the metric and its unit on the cost axis, never the column it
came from, and the best reached so far must never rise.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figure_registry import get, names
from hydromodpy.display.figures.calibration_progress import CalibrationProgressFigure

K_ROOT = 8.0e-5
SY_BEST = 0.06
MAPPED = 500.0


class _SessionRun:
    """A run-shaped carrier of one session: its trials and its session row."""

    def __init__(self, rows: list[dict], session: dict, *, name: str) -> None:
        self.calibration_iterations = rows
        self.calibration_sessions = pd.DataFrame([session])
        self.name = name
        self.sim_id = session["session_id"]

    def has_table(self, table: str) -> bool:
        return table == "calibration_iterations" and bool(self.calibration_iterations)


def _parameter(value: float, *, bounds: list[float], units: str) -> dict:
    return {"value": value, "bounds": bounds, "transform": "log", "units": units}


def _network_metrics(k: float, output: str = "seepage_network") -> dict:
    """Confusion counts of a network that shrinks as K grows, balanced at the root."""
    ratio = np.log10(K_ROOT / k)
    simulated = MAPPED * 10.0 ** (0.9 * ratio)
    valid = min(simulated, MAPPED) * (0.85 - 0.35 * min(abs(ratio), 1.0))
    d_so = 110.0 + 250.0 * max(ratio, 0.0) + 5.0 * ratio
    d_os = 110.0 + 250.0 * max(-ratio, 0.0) - 5.0 * ratio
    return {
        f"{output}.n_valid": valid,
        f"{output}.n_excess": simulated - valid,
        f"{output}.n_missing": MAPPED - valid,
        f"{output}.n_network_obs": MAPPED,
        f"{output}.n_observed_cells": 900.0,
        f"{output}.n_network_sim": simulated,
        f"{output}.D_so": d_so,
        f"{output}.D_os": d_os,
        f"{output}.J_signed": d_so - d_os,
        f"{output}.cell_spacing_m": 75.0,
    }


def _session(method: str, phase: str, config: dict) -> dict:
    return {
        "session_id": uuid.uuid4().hex,
        "method": method,
        "phase_name": phase,
        "started_at": datetime(2026, 9, 28, tzinfo=UTC).isoformat(),
        "config": json.dumps(config),
    }


def bisection_session() -> _SessionRun:
    """A bisection on K: walk up from the lower bound, then halve the bracket."""
    values = [1e-7, 1e-6, 1e-5, 1e-4, 1e-3]
    low, high = 1e-5, 1e-4
    for _ in range(9):
        middle = float(np.sqrt(low * high))
        values.append(middle)
        if middle < K_ROOT:
            low = middle
        else:
            high = middle
    config = {
        "method": "bisection",
        "parameters": {"K": {"bounds": [1e-7, 1e-3], "transform": "log", "units": "m/s"}},
        "outputs": {"seepage_network": {"support": "network"}},
        "objective_blocks": [
            {
                "name": "network_extension",
                "metric": "distance_gap",
                "weight": 1.0,
                "uses_outputs": ["seepage_network"],
                "normalize_cost": False,
            }
        ],
    }
    session = _session("bisection", "steady_conductivity", config)
    rows = []
    for trial, k in enumerate(values, start=1):
        metrics = _network_metrics(k)
        cost = abs(metrics["seepage_network.J_signed"])
        metrics["network_extension.raw_cost"] = cost
        metrics["network_extension.normalized_cost"] = cost
        rows.append(
            {
                "session_id": session["session_id"],
                "trial": trial,
                "status": "completed",
                "objective_value": cost,
                "parameters": {"K": _parameter(k, bounds=[1e-7, 1e-3], units="m/s")},
                "metrics": metrics,
            }
        )
    return _SessionRun(rows, session, name="synthetic_bisection")


def _nse_log_cost(sy: float) -> float:
    return 0.08 + 0.06 * np.log10(sy / SY_BEST) ** 2


def nelder_mead_session() -> _SessionRun:
    """A simplex on Sy, one run failing along the way."""
    values = [0.04, 0.045, 0.05, 0.06, 0.055, 0.065, 0.059, 0.061, 0.0605, 0.0598]
    config = {
        "method": "scipy_nelder_mead",
        "parameters": {"Sy": {"bounds": [0.005, 0.35], "transform": "log", "units": "-"}},
        "outputs": {"hydrograph": {"support": "point", "variable": "discharge"}},
        "objective_blocks": [
            {
                "name": "hydrograph",
                "metric": "nse_log",
                "weight": 1.0,
                "uses_outputs": ["hydrograph"],
                "normalize_cost": False,
            }
        ],
    }
    session = _session("scipy_nelder_mead", "transient_storage", config)
    rows = []
    for trial, sy in enumerate(values, start=1):
        failed = trial == 5
        cost = None if failed else _nse_log_cost(sy)
        rows.append(
            {
                "session_id": session["session_id"],
                "trial": trial,
                "status": "failed" if failed else "completed",
                "objective_value": cost,
                "parameters": {"Sy": _parameter(sy, bounds=[0.005, 0.35], units="-")},
                "metrics": {} if failed else {"hydrograph.raw_cost": cost},
            }
        )
    return _SessionRun(rows, session, name="synthetic_nelder_mead")


def optuna_session(n_runs: int = 40, seed: int = 7) -> _SessionRun:
    """A sampler on K and Sy: wide exploration, then concentration on the optimum."""
    rng = np.random.default_rng(seed)
    config = {
        "method": "optuna",
        "parameters": {
            "K": {"bounds": [1e-7, 1e-3], "transform": "log", "units": "m/s"},
            "Sy": {"bounds": [0.005, 0.35], "transform": "log", "units": "-"},
        },
        "outputs": {
            "seepage_network": {"support": "network"},
            "hydrograph": {"support": "point", "variable": "discharge"},
        },
        "objective_blocks": [
            {
                "name": "network",
                "metric": "distance_gap",
                "weight": 0.3,
                "uses_outputs": ["seepage_network"],
                "normalize_cost": True,
            },
            {
                "name": "hydrograph",
                "metric": "nse_log",
                "weight": 0.7,
                "uses_outputs": ["hydrograph"],
                "normalize_cost": False,
            },
        ],
    }
    session = _session("optuna", "conductivity_and_storage", config)
    rows = []
    for trial in range(1, n_runs + 1):
        if trial <= 12:
            # Startup: independent draws over the whole box.
            log_k = rng.uniform(-7.0, -3.0)
            log_sy = rng.uniform(-2.3, -0.456)
        else:
            # Then draws around the best so far, tighter as the runs go.
            spread = max(0.08, 1.0 - trial / n_runs)
            centre = min(rows, key=lambda row: row["objective_value"])["parameters"]
            log_k = np.clip(
                np.log10(centre["K"]["value"]) + rng.normal(0.0, 0.8 * spread), -7.0, -3.0
            )
            log_sy = np.clip(
                np.log10(centre["Sy"]["value"]) + rng.normal(0.0, 0.3 * spread), -2.3, -0.456
            )
        k, sy = 10.0**log_k, 10.0**log_sy
        metrics = _network_metrics(k)
        network = abs(metrics["seepage_network.J_signed"]) / 150.0
        hydrograph = _nse_log_cost(sy) + 0.02 * (log_k - np.log10(K_ROOT)) ** 2
        metrics.update(
            {
                "network.raw_cost": network,
                "network.normalized_cost": network,
                "hydrograph.raw_cost": hydrograph,
                "hydrograph.normalized_cost": hydrograph,
            }
        )
        rows.append(
            {
                "session_id": session["session_id"],
                "trial": trial,
                "status": "completed",
                "objective_value": 0.3 * network + 0.7 * hydrograph,
                "parameters": {
                    "K": _parameter(k, bounds=[1e-7, 1e-3], units="m/s"),
                    "Sy": _parameter(sy, bounds=[0.005, 0.35], units="-"),
                },
                "metrics": metrics,
            }
        )
    return _SessionRun(rows, session, name="synthetic_optuna")


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _ylabels(fig) -> list[str]:
    return [ax.get_ylabel() for ax in fig.get_axes()]


def _best_so_far_lines(fig) -> list[np.ndarray]:
    return [
        np.asarray(line.get_ydata(), dtype=float)
        for ax in fig.get_axes()
        for line in ax.get_lines()
        if line.get_label().endswith("best so far")
    ]


def _cost_axis(fig):
    return next(ax for ax in fig.get_axes() if ax.get_title().startswith("Cost of each run"))


def _texts(fig) -> str:
    found = [
        text.get_text() for text in fig.findobj(match=lambda artist: hasattr(artist, "get_text"))
    ]
    return "\n".join(str(text) for text in found)


def test_the_figure_is_registered_and_skips_a_plain_run() -> None:
    assert "calibration_progress" in names()
    figure = get("calibration_progress")
    assert figure.spec.required_tables == ("calibration_iterations",)
    assert figure.spec.title == "How the search converged"
    plain = _SessionRun([], {"session_id": "x"}, name="plain")
    assert "calibration_iterations" in figure.unavailable_reason(plain)


def test_a_bisection_on_the_network_draws_with_the_distance_metric(mpl) -> None:
    fig = CalibrationProgressFigure().plot(bisection_session())

    assert "|D_so - D_os| (m)" in _ylabels(fig)
    assert "Stream cells (-)" in _ylabels(fig)
    assert not any("objective_value" in label for label in _ylabels(fig))
    cost_ax = _cost_axis(fig)
    assert cost_ax.get_yscale() == "log"
    text = _texts(fig)
    assert "bisection on K" in text
    assert "bisection bracket" in text
    assert "mapped streams: 500 cells" in text
    assert "one mesh cell (75 m)" in text
    for line in _best_so_far_lines(fig):
        finite = line[np.isfinite(line)]
        assert np.all(np.diff(finite) <= 0.0)


def test_a_broken_bar_keeps_its_rank_and_the_cost_keeps_the_panel(mpl) -> None:
    run = bisection_session()
    fig = CalibrationProgressFigure().plot(run)

    network_ax = next(ax for ax in fig.get_axes() if ax.get_ylabel() == "Stream cells (-)")
    marks = next(
        artist for artist in network_ax.collections if artist.get_label().startswith("broken bar")
    )
    tops = np.asarray(marks.get_offsets())[:, 1]
    totals = np.array(
        [
            row["metrics"]["seepage_network.n_valid"] + row["metrics"]["seepage_network.n_excess"]
            for row in run.calibration_iterations
        ]
    )
    cut = np.sort(totals[totals > 2.2 * MAPPED])
    assert tops.size == cut.size >= 2
    # A bar ten times taller than another stands visibly taller, not at one cap.
    assert np.all(np.diff(np.sort(tops)) > 0.05 * MAPPED)
    cost_ax = _cost_axis(fig)
    costs = np.array([row["objective_value"] for row in run.calibration_iterations])
    assert cost_ax.get_ylim()[1] <= 10.0 * costs.max()


def test_a_nelder_mead_on_nse_log_draws_the_efficiency_rising(mpl) -> None:
    fig = CalibrationProgressFigure().plot(nelder_mead_session())

    labels = _ylabels(fig)
    assert "1 - NSElog (-)" in labels
    assert "NSElog (-), higher is better" in labels
    assert "Stream cells (-)" not in labels
    text = _texts(fig)
    assert "Nelder-Mead simplex on Sy, 10 runs, 1 failed" in text
    assert "a higher NSElog" in text
    cost_line = next(
        line for line in _cost_axis(fig).get_lines() if line.get_label() == "best so far"
    )
    finite = np.asarray(cost_line.get_ydata(), dtype=float)
    finite = finite[np.isfinite(finite)]
    assert np.all(np.diff(finite) <= 0.0)
    efficiency_ax = next(
        ax for ax in fig.get_axes() if ax.get_ylabel() == "NSElog (-), higher is better"
    )
    rising = next(line for line in efficiency_ax.get_lines() if line.get_label() == "best so far")
    rising = np.asarray(rising.get_ydata(), dtype=float)
    assert np.all(np.diff(rising[np.isfinite(rising)]) >= 0.0)


def test_a_two_parameter_sampler_adds_the_parameter_plane(mpl) -> None:
    fig = CalibrationProgressFigure().plot(optuna_session())

    titles = [ax.get_title() for ax in fig.get_axes()]
    assert "The search in the K - Sy plane" in titles
    plane = next(ax for ax in fig.get_axes() if ax.get_title().endswith("plane"))
    assert plane.get_xscale() == "log"
    assert plane.get_yscale() == "log"
    labels = _ylabels(fig)
    assert _cost_axis(fig).get_ylabel() == "Weighted cost (-)"
    text = _texts(fig)
    assert "0.3 x (|D_so - D_os| / reference scale)" in text
    assert "0.7 x (1 - NSElog)" in text
    assert "Stream cells (-)" in labels
    assert "NSElog (-), higher is better" in labels
    assert "Optuna sampler on K and Sy, 40 runs" in text
    cost_line = next(
        line for line in _cost_axis(fig).get_lines() if line.get_label() == "best so far"
    )
    values = np.asarray(cost_line.get_ydata(), dtype=float)
    assert np.all(np.diff(values[np.isfinite(values)]) <= 0.0)


def test_render_draws_the_cost_panel_alone(mpl) -> None:
    fig, ax = mpl.subplots()
    CalibrationProgressFigure().render(nelder_mead_session(), ax)
    assert ax.get_ylabel() == "1 - NSElog (-)"


def test_the_slide_saves_a_png(mpl, tmp_path: Path) -> None:
    target = tmp_path / "progress.png"
    CalibrationProgressFigure().plot(optuna_session(), save_path=target)
    assert target.stat().st_size > 0


def test_a_promoted_run_reads_its_latest_session_from_the_index(mpl, tmp_path: Path) -> None:
    """Read through the catalog: the phase and its metric come from the session row."""
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.results.run import Run

    carrier = bisection_session()
    session = carrier.calibration_sessions.iloc[0].to_dict()
    with Catalog(tmp_path) as catalog:
        sid = str(uuid.uuid4())
        catalog.register_simulation(sid, project="p", solver="modflow6", name="promoted")
        catalog.connection.execute(
            "INSERT INTO calibration_sessions (session_id, project, method, objective_name, "
            "config, started_at, phase_name, phase_index) VALUES (?, 'p', ?, 'nse', ?, ?, ?, 0)",
            [
                uuid.UUID(session["session_id"]),
                session["method"],
                session["config"],
                datetime(2026, 9, 28, tzinfo=UTC),
                session["phase_name"],
            ],
        )
        best = len(carrier.calibration_iterations)
        for row in carrier.calibration_iterations:
            catalog.connection.execute(
                "INSERT INTO calibration_iterations (session_id, iteration, sim_id, parameters, "
                "objective_value, metrics, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    uuid.UUID(session["session_id"]),
                    row["trial"],
                    uuid.UUID(sid) if row["trial"] == best else None,
                    json.dumps(row["parameters"]),
                    row["objective_value"],
                    json.dumps(row["metrics"]),
                    row["status"],
                ],
            )
        run = Run(sid, catalog)
        figure = CalibrationProgressFigure()
        assert figure.unavailable_reason(run) is None
        fig = figure.plot(run)

    assert "|D_so - D_os| (m)" in _ylabels(fig)
    assert "Steady conductivity phase: bisection on K, 14 runs" in _texts(fig)


def test_a_value_combined_from_two_roots_is_marked_and_gets_no_interval(mpl, tmp_path) -> None:
    """The slide agrees with the summary: the returned run, and no interval of runs."""
    from ._calibration_journal import (
        K_SPACE,
        TWO_ROOT_CONFIG,
        TWO_ROOTS,
        journal_run,
        two_root_rows,
    )

    run = journal_run(
        tmp_path,
        two_root_rows(),
        method="bisection",
        phase="transient_conductivity",
        config=TWO_ROOT_CONFIG,
        search_space=K_SPACE,
        best_trial=24,
        root_search=TWO_ROOTS,
    )

    fig = CalibrationProgressFigure().plot(run)

    text = _texts(fig)
    assert "Returned at run 24: K = 5.9e-06 m/s" in text
    assert "returned: 185.4 at run 24" in text
    assert "within tolerance" not in text
    assert "No interval of trials around a value combined from two roots" in " ".join(text.split())
