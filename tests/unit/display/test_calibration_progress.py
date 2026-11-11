"""The calibration progress figure and its trial table."""

from __future__ import annotations

import warnings
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figure_registry import get, names
from hydromodpy.display.figures._calibration_session import frozen_values
from hydromodpy.display.figures._trial_diagnostics import trial_table
from hydromodpy.display.figures.calibration_progress import CalibrationProgressFigure, _with_frozen
from hydromodpy.results.session.descriptor import ParameterBound
from hydromodpy.results.session.view import Session

from ._calibration_journal import (
    K_BOUNDS,
    TWO_ROOT_CONFIG,
    TWO_ROOTS,
    journal_session,
    two_root_rows,
)

# The calibration progress slide draws any search, labeled with its metric.
#
# Three synthetic sessions stand in for the three searches example 04 runs: a
# bisection on K scored on the stream network, a Nelder-Mead simplex on Sy
# scored on NSElog, and an Optuna-like sampler on K and Sy scored on both. The
# slide must name the metric and its unit on the cost axis, never the column it
# came from, and the best reached so far must never rise.

K_ROOT = 8.0e-5


SY_BEST = 0.06


MAPPED = 500.0


def _written(project: Path, rows: list[dict], method: str, phase: str, config: dict, name: str):
    """Write the trials and the frozen configuration of one synthetic search as a session."""
    bounds = {
        key: ParameterBound(
            lower=value["bounds"][0],
            upper=value["bounds"][1],
            search_space=value["search_space"],
            units=value["units"],
        )
        for key, value in config["parameters"].items()
    }
    return journal_session(
        project, rows, method=method, phase=phase, config=config, bounds=bounds, name=name
    )


def _parameter(value: float, *, bounds: list[float], units: str) -> dict:
    return {"value": value, "bounds": bounds, "search_space": "log", "units": units}


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


def bisection_session(project: Path) -> Session:
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
        "parameters": {"K": {"bounds": [1e-7, 1e-3], "search_space": "log", "units": "m/s"}},
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
    rows = []
    for trial, k in enumerate(values, start=1):
        metrics = _network_metrics(k)
        cost = abs(metrics["seepage_network.J_signed"])
        metrics["network_extension.raw_cost"] = cost
        metrics["network_extension.normalized_cost"] = cost
        rows.append(
            {
                "trial": trial,
                "status": "completed",
                "cost": cost,
                "parameters": {"K": _parameter(k, bounds=[1e-7, 1e-3], units="m/s")},
                "components": metrics,
            }
        )
    return _written(
        project, rows, "bisection", "steady_conductivity", config, "synthetic_bisection"
    )


def _nse_log_cost(sy: float) -> float:
    return 0.08 + 0.06 * np.log10(sy / SY_BEST) ** 2


def nelder_mead_session(project: Path, *, log_transform: bool = False) -> Session:
    """A simplex on Sy, one run failing along the way."""
    values = [0.04, 0.045, 0.05, 0.06, 0.055, 0.065, 0.059, 0.061, 0.0605, 0.0598]
    config = {
        "method": "scipy_nelder_mead",
        "parameters": {"Sy": {"bounds": [0.005, 0.35], "search_space": "log", "units": "-"}},
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
    if log_transform:
        config["objective_blocks"][0]["cost_transform"] = "log"
    rows = []
    for trial, sy in enumerate(values, start=1):
        failed = trial == 5
        cost = None if failed else _nse_log_cost(sy)
        rows.append(
            {
                "trial": trial,
                "status": "failed" if failed else "completed",
                "cost": cost,
                "parameters": {"Sy": _parameter(sy, bounds=[0.005, 0.35], units="-")},
                "components": {} if failed else {"hydrograph.raw_cost": cost},
            }
        )
    return _written(
        project, rows, "scipy_nelder_mead", "transient_storage", config, "synthetic_nelder_mead"
    )


def optuna_session(project: Path, n_runs: int = 40, seed: int = 7) -> Session:
    """A sampler on K and Sy: wide exploration, then concentration on the optimum."""
    rng = np.random.default_rng(seed)
    config = {
        "method": "optuna",
        "parameters": {
            "K": {"bounds": [1e-7, 1e-3], "search_space": "log", "units": "m/s"},
            "Sy": {"bounds": [0.005, 0.35], "search_space": "log", "units": "-"},
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
    rows = []
    for trial in range(1, n_runs + 1):
        if trial <= 12:
            # Startup: independent draws over the whole box.
            log_k = rng.uniform(-7.0, -3.0)
            log_sy = rng.uniform(-2.3, -0.456)
        else:
            # Then draws around the best so far, tighter as the runs go.
            spread = max(0.08, 1.0 - trial / n_runs)
            centre = min(rows, key=lambda row: row["cost"])["parameters"]
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
                "trial": trial,
                "status": "completed",
                "cost": 0.3 * network + 0.7 * hydrograph,
                "parameters": {
                    "K": _parameter(k, bounds=[1e-7, 1e-3], units="m/s"),
                    "Sy": _parameter(sy, bounds=[0.005, 0.35], units="-"),
                },
                "components": metrics,
            }
        )
    return _written(project, rows, "optuna", "conductivity_and_storage", config, "synthetic_optuna")


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


def test_the_figure_is_registered_and_skips_a_session_without_trials(tmp_path) -> None:
    assert "calibration_progress" in names()
    figure = get("calibration_progress")
    assert figure.spec.subject == "session"
    assert figure.spec.title == "How the search converged"
    assert "no trial recorded" in figure.unavailable_reason(journal_session(tmp_path, []))
    assert figure.unavailable_reason(bisection_session(tmp_path)) is None


def test_a_bisection_on_the_network_draws_with_the_distance_metric(mpl, tmp_path: Path) -> None:
    fig = CalibrationProgressFigure().plot(bisection_session(tmp_path))

    assert "|D_so - D_os| (m)" in _ylabels(fig)
    assert "Stream cells (-)" in _ylabels(fig)
    assert not any("cost" in label for label in _ylabels(fig))
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


def test_a_broken_bar_keeps_its_rank_and_the_cost_keeps_the_panel(mpl, tmp_path: Path) -> None:
    run = bisection_session(tmp_path)
    fig = CalibrationProgressFigure().plot(run)

    network_ax = next(ax for ax in fig.get_axes() if ax.get_ylabel() == "Stream cells (-)")
    marks = next(
        artist for artist in network_ax.collections if artist.get_label().startswith("broken bar")
    )
    tops = np.asarray(marks.get_offsets())[:, 1]
    frame = trial_table(run).frame
    totals = (frame["seepage_network.n_valid"] + frame["seepage_network.n_excess"]).to_numpy()
    cut = np.sort(totals[totals > 2.2 * MAPPED])
    assert tops.size == cut.size >= 2
    # A bar ten times taller than another stands visibly taller, not at one cap.
    assert np.all(np.diff(np.sort(tops)) > 0.05 * MAPPED)
    cost_ax = _cost_axis(fig)
    costs = trial_table(run).frame["cost"].to_numpy(dtype=float)
    assert cost_ax.get_ylim()[1] <= 10.0 * costs.max()


def test_a_nelder_mead_on_nse_log_draws_the_efficiency_rising(mpl, tmp_path: Path) -> None:
    fig = CalibrationProgressFigure().plot(nelder_mead_session(tmp_path))

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


def test_a_two_parameter_sampler_adds_the_parameter_plane(mpl, tmp_path: Path) -> None:
    fig = CalibrationProgressFigure().plot(optuna_session(tmp_path))

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


def test_render_draws_the_cost_panel_alone(mpl, tmp_path: Path) -> None:
    fig, ax = mpl.subplots()
    CalibrationProgressFigure().render(nelder_mead_session(tmp_path), ax)
    assert ax.get_ylabel() == "1 - NSElog (-)"


def test_the_slide_saves_a_png(mpl, tmp_path: Path) -> None:
    target = tmp_path / "progress.png"
    CalibrationProgressFigure().plot(optuna_session(tmp_path), save_path=target)
    assert target.stat().st_size > 0


def test_a_value_combined_from_two_roots_is_marked_and_gets_no_interval(mpl, tmp_path) -> None:
    """The slide agrees with the summary: the returned run, and no interval of runs."""
    run = journal_session(
        tmp_path,
        two_root_rows(),
        method="bisection",
        phase="transient_conductivity",
        config=TWO_ROOT_CONFIG,
        bounds=K_BOUNDS,
        best_trial=24,
        root_search=TWO_ROOTS,
    )

    fig = CalibrationProgressFigure().plot(run)

    text = _texts(fig)
    assert "Returned at run 24: K = 5.9e-06 m/s" in text
    assert "returned: 185.4 at run 24" in text
    assert "within tolerance" not in text
    assert "No interval of trials around a value combined from two roots" in " ".join(text.split())


@pytest.mark.parametrize(
    ("phases", "values", "expected"),
    [
        (["a", "b", "b"], [1.0, np.nan, np.nan], [1.0, 8e-5, 8e-5]),
        (["a", "a", "c"], [1.0, 2.0, np.nan], [1.0, 2.0, np.nan]),
    ],
)
def test_a_run_of_a_phase_that_froze_a_parameter_reads_the_frozen_value(
    phases: list[str], values: list[float], expected: list[float]
) -> None:
    table = SimpleNamespace(frame=pd.DataFrame({"phase": phases}))
    filled = _with_frozen(np.array(values), table, {"b": {"K": 8e-5}}, "K")
    np.testing.assert_array_equal(filled, np.array(expected))


def test_the_frozen_values_are_read_from_the_phase_journals(tmp_path: Path) -> None:
    rows = [
        {"trial": 1, "phase": "a", "cost": 1.0, "parameters": {"K": 1e-5}},
        {"trial": 2, "phase": "b", "cost": 0.5, "parameters": {"Sy": 0.1}},
    ]
    staged = journal_session(tmp_path / "a", rows, phases=["a", "b"], frozen={"b": {"K": 8e-5}})
    unstaged = journal_session(tmp_path / "b", rows, named_phases=False)

    assert frozen_values(staged) == {"a": {}, "b": {"K": 8e-5}}
    assert frozen_values(unstaged) == {}


# The fit panel of a transformed efficiency frames the values it draws.
#
# A block with a ``cost_transform`` draws its cost, not its efficiency. The panel used
# to take its range from the efficiency (one minus the cost) and its "higher is
# better" from the metric alone, so the points fell off the axis under a label
# that read them the wrong way up.

pytestmark = pytest.mark.unit


def test_a_transformed_efficiency_is_drawn_inside_its_range(mpl, tmp_path: Path) -> None:
    fig = CalibrationProgressFigure().plot(nelder_mead_session(tmp_path, log_transform=True))

    fit_ax = next(ax for ax in fig.get_axes() if ax.get_title().startswith("Fit to the"))
    low, high = fit_ax.get_ylim()
    drawn = np.concatenate(
        [np.asarray(line.get_ydata(), dtype=float) for line in fit_ax.get_lines()]
    )
    drawn = drawn[np.isfinite(drawn)]
    assert drawn.size
    assert low <= drawn.min() and drawn.max() <= high
    assert "1 - NSElog (-), lower is better" in _ylabels(fig)


# The trial table of a network calibration is built without fragmenting.
#
# A network criterion publishes about a hundred diagnostics per trial. Inserting
# them one column at a time fragmented the frame, and pandas printed a
# PerformanceWarning on the console of every promoted run.


def test_two_hundred_diagnostics_raise_no_performance_warning(tmp_path: Path) -> None:
    components = {f"net.diag_{index:03d}": float(index) for index in range(200)}
    rows = [
        {
            "trial": trial,
            "parameters": {"K": {"value": 10.0 ** -(trial + 3)}},
            "components": dict(components),
            "cost": float(trial),
        }
        for trial in range(1, 6)
    ]
    run = journal_session(tmp_path, rows)

    with warnings.catch_warnings():
        warnings.simplefilter("error", pd.errors.PerformanceWarning)
        table = trial_table(run)

    assert table.parameters == ("K",)
    assert table.frame["net.diag_199"].tolist() == [199.0] * 5
    assert table.frame["K"].tolist()[0] == 1e-4
