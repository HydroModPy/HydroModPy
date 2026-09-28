"""The facts the console recap of a calibration reads off the run.

The CLI cannot reach the configuration, so the runner records the unit of each
parameter, the metric the cost is and the session folder, and writes the
methods paragraph to a file the recap names.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.runners import staged_runner
from hydromodpy.calibration.runners.recap import (
    METHODS_FILENAME,
    cost_metric_label,
    parameter_units,
    session_directory,
    write_methods,
)
from hydromodpy.results.session_journal import session_dir_name, sessions_dir_for

_PARAMETERS = {
    "K": {
        "bounds": [1e-7, 1e-3],
        "transform": "log",
        "prior": "log_uniform",
        "path": "flow.param.K.field.value",
        "units": "m/s",
    },
    "Sy": {
        "bounds": [0.005, 0.35],
        "transform": "log",
        "prior": "log_uniform",
        "path": "flow.param.Sy.field.value",
    },
}


def _cfg(**updates) -> CalibrationConfig:
    payload = {"method": "grid", "max_iter": 3, "parameters": _PARAMETERS}
    payload.update(updates)
    return CalibrationConfig.model_validate(payload)


def test_a_score_that_rises_with_agreement_reads_as_one_minus_it() -> None:
    assert cost_metric_label(_cfg(objective="nse")) == "1 - nse"
    assert cost_metric_label(_cfg(objective="rmse")) == "rmse"


def test_each_parameter_carries_its_declared_unit() -> None:
    assert parameter_units(_cfg()) == {"K": "m/s", "Sy": "-"}


def test_the_session_folder_is_found_by_its_short_id(tmp_path) -> None:
    session_id = "099012a076844fd1bd4801166063392c"
    folder = sessions_dir_for(tmp_path) / session_dir_name(
        session_id, "bisection", datetime(2026, 9, 28, 3, 38, 25, tzinfo=UTC)
    )
    folder.mkdir(parents=True)
    (folder / "session.json").write_text("{}", encoding="utf-8")

    assert session_directory(tmp_path, session_id) == folder
    assert session_directory(tmp_path, "ffffffff") is None


def test_the_methods_paragraph_is_written_beside_the_root_session(tmp_path) -> None:
    session_id = "099012a076844fd1bd4801166063392c"
    folder = sessions_dir_for(tmp_path) / f"20260928-033825-bisection-{session_id[:8]}"
    folder.mkdir(parents=True)
    (folder / "session.json").write_text("{}", encoding="utf-8")
    runs = [SimpleNamespace(report=SimpleNamespace(workspace=tmp_path))]

    path = staged_runner._write_methods_beside_the_root(runs, session_id, "Hydraulic ...")

    assert path == folder / METHODS_FILENAME
    assert path.read_text(encoding="utf-8") == "# Methods\n\nHydraulic ...\n"
    assert staged_runner._write_methods_beside_the_root(runs, session_id, None) is None


def test_write_methods_returns_the_file_it_wrote(tmp_path) -> None:
    path = write_methods(tmp_path, "  text  ")

    assert path.read_text(encoding="utf-8") == "# Methods\n\ntext\n"
