"""Console recap of a calibration: units, cost label, methods file and the lines read off a report.

Shares of the cost are fractions of 1 and print as percent. K is in m/s, Sy has no unit.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.runners.recap import (
    cost_metric_label,
    parameter_units,
    percent,
    result_lines,
    shares_text,
    staged_result_lines,
    write_methods,
)
from hydromodpy.calibration.runners.session_scope import open_calibration_session
from hydromodpy.calibration.runners.state import space_from_config
from hydromodpy.results.session.summary import SessionSummary, session_summary, summary_rows
from hydromodpy.results.session.view import Session
from hydromodpy.results.storage.contract import SESSION_METHODS_FILENAME
from tests._helpers.session_documents import best_trial

_PARAMETERS = {
    "K": {
        "bounds": [1e-7, 1e-3],
        "search_space": "log",
        "sampling": "log_uniform",
        "path": "flow.param.K.field.value",
        "units": "m/s",
    },
    "Sy": {
        "bounds": [0.005, 0.35],
        "search_space": "log",
        "sampling": "log_uniform",
        "path": "flow.param.Sy.field.value",
    },
}


def _cfg(**updates) -> CalibrationConfig:
    payload = {"method": "grid", "max_trials": 3, "parameters": _PARAMETERS}
    payload.update(updates)
    return CalibrationConfig.model_validate(payload)


def test_parameter_units() -> None:
    assert parameter_units(_cfg()) == {"K": "m/s", "Sy": "-"}


def test_write_methods(tmp_path) -> None:
    path = write_methods(tmp_path, "  text  ")

    assert path == tmp_path / SESSION_METHODS_FILENAME
    assert path.read_text(encoding="utf-8") == "# Methods\n\ntext\n"


def _config(blocks: list[dict[str, object]], **extra: object) -> CalibrationConfig:
    payload: dict[str, object] = {
        "method": "grid",
        "max_trials": 3,
        "parameters": {"K": {"bounds": [1e-8, 1e-2], "path": "flow.param.K.field.value"}},
        "outputs": {
            "q": {
                "variable": "discharge",
                "support": "boundary",
                "boundary_id": "outlet",
                "observed_values": [1.0, 2.0],
            },
        },
        "objective_blocks": blocks,
    }
    payload.update(extra)
    return CalibrationConfig.model_validate(payload)


def _block(name: str, metric: str, **extra: object) -> dict[str, object]:
    return {"name": name, "metric": metric, "uses_outputs": ["q"], **extra}


COST_LABELS = [
    pytest.param(
        [_block("flows", "rmse", cost_transform="log")], "log10(rmse)", id="log transform"
    ),
    pytest.param(
        [_block("flows", "nse", cost_transform="inverse")], "-1 / (1 - nse)", id="inverse transform"
    ),
    pytest.param(
        [
            _block("flows", "nse_log"),
            _block("residual", "rmse", normalize_cost=True, cost_transform="log"),
        ],
        "weighted sum of flows 1 - nse_log, residual log10(rmse / sd(observed))",
        id="sum of two blocks",
    ),
]


@pytest.mark.parametrize(("blocks", "label"), COST_LABELS)
def test_cost_label(blocks, label) -> None:
    assert cost_metric_label(_config(blocks)) == label


def test_report_row_has_the_cost_label() -> None:
    summary = SessionSummary(
        name="calage",
        method="nelder_mead",
        status="completed",
        trials_by_status={"completed": 3},
        best_trial=3,
        best_cost=0.083984,
        cost_label="1 - nse_log",
        scored_on=None,
        stop=None,
        bounds_reached=(),
        calibrated_variable="discharge",
        report=None,
        profile=(),
    )

    rows = dict(summary_rows(summary))

    assert rows["best trial"] == "3, cost 0.083984 (1 - nse_log)"


def test_closed_session_shows_best_cost_and_label(tmp_path: Path) -> None:
    cfg = _config([_block("flows", "nse_log")])
    persistence, _ = open_calibration_session(
        tmp_path,
        "case",
        resume=False,
        raw={"calibration": {}},
        cfg=cfg,
        space=space_from_config(cfg),
        trial_ctx=None,
        project="p",
    )
    persistence.finalize_session(status="completed", best=best_trial(3, cost=0.083984))

    rows = dict(summary_rows(session_summary(Session(persistence.directory))))

    assert rows["best trial"] == "3, cost 0.083984 (1 - nse_log)"


def _width(parameter: str, sigma: float, tradeoff=None) -> SimpleNamespace:
    return SimpleNamespace(parameter=parameter, sigma=sigma, strongest_tradeoff=lambda: tradeoff)


def _interval(name: str, lower: float, upper: float, **flags) -> dict:
    record = {
        "name": name,
        "lower": lower,
        "upper": upper,
        "best": lower,
        "n_within": 5,
        "reaches_lower_bound": False,
        "reaches_upper_bound": False,
    }
    return {**record, **flags}


def _report(extra=None, **fields) -> SimpleNamespace:
    return SimpleNamespace(best_parameters={"K": 1e-5}, extra=extra or {}, **fields)


_BRACKET = {"parameter": "K", "low": 1e-6, "high": 4e-6, "relative_width": 0.75}
_ROOT = {"k_star": 2e-6, "low": 1e-6, "high": 3e-6, "relative_width": 0.5, "weight": 0.25}
_SHARES = {"mean": {"flows": 0.75, "network": 0.25}, "best": {"flows": 0.5, "network": 0.5}}


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (SimpleNamespace(best_parameters={}), []),
        (
            _report(
                {"parameter_units": {"K": "m/s"}}, parameter_uncertainty=[_width("K", 0.123456)]
            ),
            ["  K = 1e-05 m/s  (sigma 0.123)"],
        ),
        (
            _report(parameter_uncertainty=[_width("K", 0.1, ("Sy", -0.95))]),
            [
                "  K = 1e-05  (sigma 0.1)",
                "  caution: K and Sy trade off (r = -0.95), not identified separately.",
            ],
        ),
        (
            _report(parameter_uncertainty=[_width("K", 0.1, ("Sy", 0.5))]),
            ["  K = 1e-05  (sigma 0.1)"],
        ),
        (
            _report({"correlated_parameters": [["K", "Sy", 0.93]]}),
            [
                "  K = 1e-05",
                "  caution: K and Sy moved together (r = +0.93), not identified separately.",
            ],
        ),
        (
            _report({"parameter_intervals": [_interval("K", 1e-6, 1e-4)]}),
            ["  K = 1e-05  [1e-06, 0.0001]"],
        ),
        (
            _report({"parameter_intervals": [_interval("K", 1e-6, 1e-4, n_within=1)]}),
            ["  K = 1e-05  (no other trial within the cost margin)"],
        ),
        (
            _report(
                {"parameter_intervals": [_interval("K", 1e-6, 1e-4, reaches_lower_bound=True)]}
            ),
            ["  K = 1e-05  [1e-06, 0.0001]  -- reached the search bound"],
        ),
        (
            _report(
                {
                    "parameter_intervals": [
                        _interval("K", 2e-6, 1e-4, best=1e-5, reaches_lower_bound=True)
                    ]
                }
            ),
            ["  K = 1e-05  [2e-06, 0.0001]  -- its range reaches the search bound"],
        ),
        (
            _report(
                {"cost_metric": "1 - nse", "cost_window": "calibration"},
                best_cost=0.25,
                best_rel_dir="runs/best",
            ),
            [
                "  K = 1e-05",
                "  cost: 0.25 (1 - nse)",
                "  scored on: calibration, pairs not counted",
                "  calibrated run: runs/best",
            ],
        ),
        (
            _report({"cost_samples": {"q": {"n_paired": 12, "n_sim_nan": 2}}}, best_cost=0.5),
            [
                "  K = 1e-05",
                "  cost: 0.5",
                "  scored on: q 12 pair(s) (2 lost to a NaN simulated value), best trial",
            ],
        ),
        (_report({}, best_cost=0.5), ["  K = 1e-05", "  cost: 0.5"]),
        (
            _report({"k_over_r_note": "k_over_r is not published"}),
            ["  K = 1e-05", "  k_over_r is not published"],
        ),
        (_report({"k_over_r": 12.3456}), ["  K = 1e-05", "  k_over_r = 12.35"]),
        (
            _report({"bracket": _BRACKET}),
            [
                "  K = 1e-05",
                "  bracket on K: [1e-06, 4e-06], width 75.00% (open, the budget ran out first)",
            ],
        ),
        (
            _report({"bracket": {**_BRACKET, "closed": True}}),
            ["  K = 1e-05", "  bracket on K: [1e-06, 4e-06], width 75.00% (closed)"],
        ),
        (
            _report(
                {
                    "roots": {
                        "parameter": "K",
                        "delta_log10": 0.5,
                        "value": 3e-6,
                        "minimal": _ROOT,
                        "maximal": {**_ROOT, "closed": True, "weight": 0.75},
                    }
                }
            ),
            [
                "  K = 1e-05",
                "  K*_minimal = 2e-06, bracket [1e-06, 3e-06], width 50.00% (open, the budget ran out first)",
                "  K*_maximal = 2e-06, bracket [1e-06, 3e-06], width 50.00% (closed)",
                "  Delta = log10(K*_maximal / K*_minimal) = 0.5 decade(s)",
                "  K = 3e-06, weighted geometric mean of the two roots (0.25 / 0.75)",
            ],
        ),
        (
            _report({"roots": {"parameter": "K", "minimal": _ROOT, "maximal": _ROOT}}),
            [
                "  K = 1e-05",
                "  K*_minimal = 2e-06, bracket [1e-06, 3e-06], width 50.00% (open, the budget ran out first)",
                "  K*_maximal = 2e-06, bracket [1e-06, 3e-06], width 50.00% (open, the budget ran out first)",
                "  Delta = log10(K*_maximal / K*_minimal) = unknown decade(s)",
                "  K: not solved (weighted geometric mean, 0.25 / 0.25)",
            ],
        ),
        (
            _report(
                {
                    "search": {
                        "n_evaluations": 9,
                        "max_trials": 10,
                        "extension": 2,
                        "stop_state": "rule_met",
                        "stopping_rule": "tol",
                    }
                }
            ),
            [
                "  K = 1e-05",
                "  search: met its own rule (tol), converged, 9 evaluation(s) of 10 declared + 2 extension",
            ],
        ),
        (
            _report(cost_block_fractions={**_SHARES, "mean_n_trials": 4}),
            [
                "  K = 1e-05",
                "  cost share (mean over 4 finished trials): flows 75%, network 25%",
                "  cost share (best trial): flows 50%, network 50%",
            ],
        ),
        (
            _report(cost_block_fractions={"mean": _SHARES["mean"]}),
            ["  K = 1e-05", "  cost share (mean over the finished trials): flows 75%, network 25%"],
        ),
        (
            _report({"cost_block_fractions_absent_note": "phase reused from disk"}),
            ["  K = 1e-05", "  cost share: phase reused from disk"],
        ),
    ],
)
def test_result_lines(result, expected) -> None:
    assert result_lines(result) == expected


@pytest.mark.parametrize(
    ("verdict", "line"),
    [
        (
            {
                "validity_length_m": 500.0,
                "provenance": "grid",
                "D_optim": 120.0,
                "value": 0.24,
                "valid": True,
            },
            "r_optim (q) = 0.24, D_optim = 120 m <= 500 m (grid), Eq. 4 holds",
        ),
        (
            {"validity_length_m": 100.0, "D_optim": 120.0, "value": None, "causes": ["doptim"]},
            "r_optim (q) = not a number, D_optim = 120 m > 100 m, Eq. 4 fails: coarse agreement",
        ),
        (
            {"D_optim": 50.0, "value": 0.5, "causes": []},
            "r_optim (q) = 0.5, D_optim = 50 m <= not published, Eq. 4 fails: not qualified",
        ),
        (
            {"validity_length_m": 100.0, "D_optim": 50.0, "causes": ["empty"]},
            "r_optim (q): not a number, the simulated network is empty at the returned "
            "trial (validity length 100 m)",
        ),
        (
            {"validity_length_m": 100.0},
            "r_optim (q): not a number, the simulated network is empty at the returned "
            "trial (validity length 100 m)",
        ),
    ],
)
def test_network_verdict_line(verdict, line) -> None:
    assert result_lines(_report({"r_optim_verdict": {"q": verdict}})) == [
        "  K = 1e-05",
        f"  {line}",
    ]


def test_staged_lines_name_each_phase() -> None:
    quiet = SimpleNamespace(name="quiet", report=SimpleNamespace(best_parameters={}))
    first = SimpleNamespace(name="one", report=_report(), stop_note="stopped early")
    second = SimpleNamespace(name="two", report=_report())

    assert staged_result_lines(SimpleNamespace(phases=[quiet, first, second])) == [
        "phase one:",
        "  K = 1e-05",
        "  stopped early",
        "phase two:",
        "  K = 1e-05",
    ]


# Below 1 % a share keeps one significant digit, above 99 % its complement's.
@pytest.mark.parametrize(
    ("share", "printed"),
    [
        (1.0, "100%"),
        (0.5, "50%"),
        (0.25, "25%"),
        (0.0, "0%"),
        (1 / 101, "1%"),
        (100 / 101, "99%"),
        (1 / 1001, "0.1%"),
        (1000 / 1001, "99.9%"),
        (0.00004, "0.004%"),
        (0.00096, "0.1%"),
    ],
)
def test_percent(share: float, printed: str) -> None:
    assert percent(share) == printed


def test_a_small_share_is_not_printed_as_zero() -> None:
    assert shares_text({"hydrograph": 1000 / 1001, "network": 1 / 1001}) == (
        "hydrograph 99.9%, network 0.1%"
    )
