"""The label of a cost says what the number is: metric, cost transform and scale.

``cost_metric_label`` named the metric alone. A block with ``cost_transform = "log"``
minimises ``log10(rmse)`` and one with ``normalize_cost`` minimises the RMSE over
the spread of the record, yet both were labelled ``rmse``. The HTML report of a
session listed ``best_objective`` with no label at all, beside an
``objective_name`` that reads as a score. The session now records the label and
the report prints it beside the cost.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.runners.cli_runner import open_calibration_session
from hydromodpy.calibration.runners.recap import cost_metric_label
from hydromodpy.calibration.runners.state import space_from_config
from hydromodpy.reporting.calibration_report import _render_html


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

    assert persistence.descriptor.objective_label == "log10(rmse)"


def test_the_html_report_prints_the_label_beside_the_cost() -> None:
    session = {
        "session_id": "abc",
        "objective_name": "nse_log",
        "objective_label": "1 - nse_log",
        "best_objective": 0.083984,
    }

    page = _render_html(session, [], [])

    assert "<th>best_objective</th><td>0.083984 (1 - nse_log)</td>" in page


def test_the_report_of_a_closed_session_shows_its_best_cost_and_label(tmp_path: Path) -> None:
    from hydromodpy.calibration.persistence import BestTrial
    from hydromodpy.calibration.report import load_session_report_data

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
    persistence.finalize_session(status="completed", best=BestTrial(trial=3, objective=0.083984))

    page = _render_html(load_session_report_data(persistence.directory).session, [], [])

    assert "<th>best_objective</th><td>0.083984 (1 - nse_log)</td>" in page
