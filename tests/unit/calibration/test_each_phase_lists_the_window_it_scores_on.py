"""``--list-phases``, ``--dry-run`` and ``hmp config check`` say what each phase scores on.

They listed the metric and the station of each phase, never its window, nor
``[metrics] window``, the one the run is scored on and the default of a
transient phase. The window showed only when its author copied it into the
phase description. Each phase now prints the window it scores on, and the
check prints ``[metrics] window`` too.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.preflight import comparison_lines
from hydromodpy.calibration.runners.cli_runner import describe_dry_run, load_toml_calibration
from hydromodpy.calibration.runners.staged_runner import phase_summaries
from hydromodpy.cli.commands import calibrate as calibrate_cmd
from hydromodpy.config.metrics_config import MetricsConfig

EXAMPLE_04 = Path("examples/projects/04_streamflow_intermittence_in_transient")


def _staged() -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "parameters": {
                "K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"},
                "Sy": {"bounds": [0.01, 0.3], "path": "flow.param.Sy.field.value"},
            },
            "outputs": {
                "gauge": {"support": "point", "observes": "J0014", "variable": "discharge"},
            },
            "objective_blocks": [
                {"name": "hydrograph", "metric": "nse_log", "uses_outputs": ["gauge"]}
            ],
            "phases": [
                {"name": "first", "parameters": ["K"], "objective_blocks": ["hydrograph"]},
                {
                    "name": "second",
                    "parameters": ["Sy"],
                    "objective_blocks": ["hydrograph"],
                    "scoring_window": {"start": "2016-01-01", "end": "2020-12-31"},
                },
            ],
        }
    )


def test_each_phase_summary_carries_its_window() -> None:
    rows = phase_summaries(_staged())

    assert [row["scoring_window"] for row in rows] == [
        "no window, all of the run",
        "window 2016-01-01 to 2020-12-31",
    ]


def test_the_check_names_the_run_window_and_each_phase_s(tmp_path: Path) -> None:
    cfg = SimpleNamespace(
        calibration=_staged(),
        metrics=MetricsConfig.model_validate(
            {"window": {"start": "2016-01-01", "end": "2020-12-31"}}
        ),
    )

    lines = comparison_lines(cfg, tmp_path / "calibration.toml")

    assert lines[0] == "[metrics] window: 2016-01-01 to 2020-12-31, the window the run is scored on"
    assert "  scores on: no window, all of the run" in lines
    assert "  scores on: window 2016-01-01 to 2020-12-31" in lines


@pytest.mark.fast
def test_list_phases_prints_the_window_under_each_phase(capsys) -> None:
    calibrate_cmd.run(
        argparse.Namespace(
            config=EXAMPLE_04 / "run_calibration.toml",
            check=False,
            list_phases=True,
            expand=False,
            phase=None,
            profile=None,
        )
    )

    lines = capsys.readouterr().out.splitlines()
    assert lines[2] == "    scores on: no window, all of the run"
    assert lines[5] == "    scores on: window 2001-01-01 to 2002-12-31"


def test_the_dry_run_names_the_window_of_each_phase(tmp_path: Path, capsys) -> None:
    config = EXAMPLE_04 / "run_calibration.toml"
    plan = describe_dry_run(load_toml_calibration(config)[0], config, workspace=tmp_path)

    calibrate_cmd._print_dry_run(plan)

    err = capsys.readouterr().err
    assert "phase transient_storage: Sy, " in err
    assert "trials, scores on window 2001-01-01 to 2002-12-31" in err
