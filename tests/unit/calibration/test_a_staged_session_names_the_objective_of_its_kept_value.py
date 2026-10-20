"""A staged session names the objective its kept value is a cost of.

``session.json`` of a two-stage calibration wrote ``objective_name =
"distance_gap + nse_log"``, every block of every stage joined, while its value
and its window are those of the last stage, scored on ``nse_log`` alone. The
promoted run inherits the name. It now names what the last stage scores.
"""

from __future__ import annotations

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.runners.cli_runner import session_objective_name

_PARAMETERS = {
    "K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"},
    "Sy": {"bounds": [0.01, 0.3], "path": "flow.param.Sy.field.value"},
}
_OUTPUTS = {
    "net": {"support": "network", "stream_geometry_path": "streams.gpkg"},
    "gauge": {"support": "point", "observes": "J0014", "variable": "discharge"},
}
_BLOCKS = [
    {"name": "network", "metric": "distance_gap", "uses_outputs": ["net"]},
    {"name": "hydrograph", "metric": "nse_log", "uses_outputs": ["gauge"]},
]


def _staged(last: dict) -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "parameters": _PARAMETERS,
            "outputs": _OUTPUTS,
            "objective_blocks": _BLOCKS,
            "phases": [
                {"name": "steady", "parameters": ["K"], "objective_blocks": ["network"]},
                {"name": "transient", "parameters": ["Sy"], **last},
            ],
        }
    )


def test_the_name_is_the_last_stage_s_metric() -> None:
    cfg = _staged({"objective_blocks": ["hydrograph"]})

    assert session_objective_name(cfg) == "nse_log"


def test_a_last_stage_on_the_single_metric_route_names_its_objective() -> None:
    cfg = _staged({"variable": "gauge", "objective": "kge"})

    assert session_objective_name(cfg) == "kge"
