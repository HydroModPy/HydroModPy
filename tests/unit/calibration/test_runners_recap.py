"""Tests of `runners.recap`."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.report import load_session_report_data
from hydromodpy.calibration.runners.cli_runner import open_calibration_session
from hydromodpy.calibration.runners.recap import cost_metric_label, parameter_units, write_methods
from hydromodpy.calibration.runners.state import space_from_config
from hydromodpy.reporting.calibration_report import _render_html
from hydromodpy.results.storage.contract import SESSION_METHODS_FILENAME
from tests._helpers.session_documents import best_trial

# From test_calibration_recap_facts.py
# The facts the console recap of a calibration reads off the run.
#
# The CLI cannot reach the configuration, so the runner records the unit of each
# parameter and the metric the cost is, and writes the methods paragraph to a
# file of the session the recap names.


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


def test_a_score_that_rises_with_agreement_reads_as_one_minus_it() -> None:
    assert cost_metric_label(_cfg(objective="nse")) == "1 - nse"
    assert cost_metric_label(_cfg(objective="rmse")) == "rmse"


def test_each_parameter_carries_its_declared_unit() -> None:
    assert parameter_units(_cfg()) == {"K": "m/s", "Sy": "-"}


def test_write_methods_returns_the_file_it_wrote(tmp_path) -> None:
    path = write_methods(tmp_path, "  text  ")

    assert path == tmp_path / SESSION_METHODS_FILENAME
    assert path.read_text(encoding="utf-8") == "# Methods\n\ntext\n"


# From test_the_cost_label_says_the_transform_and_the_scale.py
# The label of a cost says what the number is: metric, cost transform and scale.
#
# ``cost_metric_label`` named the metric alone. A block with ``cost_transform = "log"``
# minimizes ``log10(rmse)`` and one with ``normalize_cost`` minimizes the RMSE over
# the spread of the record, yet both were labeled ``rmse``. The HTML report of a
# session listed ``best_cost`` with no label at all, beside an
# ``cost_name`` that reads as a score. The session now records the label and
# the report prints it beside the cost.


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


def test_a_log_transform_is_named() -> None:
    cfg = _config([_block("flows", "rmse", cost_transform="log")])

    assert cost_metric_label(cfg) == "log10(rmse)"


def test_an_inverse_transform_is_named() -> None:
    cfg = _config([_block("flows", "nse", cost_transform="inverse")])

    assert cost_metric_label(cfg) == "-1 / (1 - nse)"


def test_a_normalised_residual_names_its_scale() -> None:
    cfg = _config([_block("flows", "rmse", normalize_cost=True)])

    assert cost_metric_label(cfg) == "rmse / sd(observed)"


def test_each_block_of_a_sum_carries_its_own_reading() -> None:
    cfg = _config(
        [
            _block("flows", "nse_log"),
            _block("residual", "rmse", normalize_cost=True, cost_transform="log"),
        ]
    )

    assert cost_metric_label(cfg) == (
        "weighted sum of flows 1 - nse_log, residual log10(rmse / sd(observed))"
    )


def test_a_phase_is_labelled_by_the_blocks_it_scores() -> None:
    cfg = _config(
        [_block("flows", "nse_log"), _block("residual", "rmse", normalize_cost=True)],
        phases=[
            {"name": "one", "parameters": ["K"], "objective_blocks": ["residual"]},
            {"name": "two", "parameters": ["K"], "objective_blocks": ["flows"]},
        ],
    )

    assert cost_metric_label(cfg, cfg.phases[0]) == "rmse / sd(observed)"
    assert cost_metric_label(cfg, cfg.phases[1]) == "1 - nse_log"


def test_the_session_records_the_label_of_its_cost(tmp_path: Path) -> None:
    cfg = _config([_block("flows", "rmse", cost_transform="log")])

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

    assert persistence.descriptor.cost_label == "log10(rmse)"


def test_the_html_report_prints_the_label_beside_the_cost() -> None:
    session = {
        "session_id": "abc",
        "cost_name": "nse_log",
        "cost_label": "1 - nse_log",
        "best_cost": 0.083984,
    }

    page = _render_html(session, [], [])

    assert "<th>best_cost</th><td>0.083984 (1 - nse_log)</td>" in page


def test_the_report_of_a_closed_session_shows_its_best_cost_and_label(tmp_path: Path) -> None:
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

    page = _render_html(load_session_report_data(persistence.directory).session, [], [])

    assert "<th>best_cost</th><td>0.083984 (1 - nse_log)</td>" in page
