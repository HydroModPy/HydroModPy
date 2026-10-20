"""The facts the console recap of a calibration reads off the run.

The CLI cannot reach the configuration, so the runner records the unit of each
parameter and the metric the cost is, and writes the methods paragraph to a
file of the session the recap names.
"""

from __future__ import annotations

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.runners.recap import (
    cost_metric_label,
    parameter_units,
    write_methods,
)
from hydromodpy.results.storage.contract import SESSION_METHODS_FILENAME

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
