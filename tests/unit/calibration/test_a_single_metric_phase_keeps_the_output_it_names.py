"""A single-metric phase keeps the output its variable names.

``_phase_config`` used to empty the outputs of a phase scored on its own
``variable`` and ``objective``. A phase whose variable names a network output
then lost the declaration of that output: its maps, its extent table. The
root search read one root where the output scores two bounds.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.runners.cli_runner import _engine_kwargs
from hydromodpy.calibration.runners.staged_runner import _phase_config

NETWORK = {
    "support": "network",
    "stream_geometry_path": "streams.gpkg",
    "minimal_stream_geometry_path": "permanent.gpkg",
    "extent": {},
}
POINT = {
    "support": "point",
    "variable": "head",
    "x": 0.0,
    "y": 0.0,
    "observed_values": [1.0, 2.0],
}


def _config(phase: dict, **section) -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "method": "bisection",
            "parameters": {
                "K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"},
                "Sy": {"bounds": [1e-3, 3e-1], "path": "flow.param.Sy.field.value"},
            },
            "outputs": {"net": NETWORK, "well": POINT},
            "objective_blocks": [
                {"name": "gap", "metric": "distance_gap", "uses_outputs": ["net"]},
                {"name": "heads", "metric": "nse", "uses_outputs": ["well"]},
            ],
            "phases": [
                {"name": "k_network", "method": "bisection", "parameters": ["K"], **phase},
                {
                    "name": "sy_heads",
                    "method": "grid",
                    "parameters": ["Sy"],
                    "objective_blocks": ["heads"],
                    "depends_on": "k_network",
                },
            ],
            **section,
        }
    )


_SPACE = ParameterSpace([CalibParameter(name="K", lower=1e-7, upper=1e-3, transform="log")])


def test_the_network_output_the_variable_names_is_kept() -> None:
    cfg = _config({"variable": "net", "objective": "distance_gap"})

    phase_cfg = _phase_config(cfg, cfg.phases[0])

    assert set(phase_cfg.outputs) == {"net"}
    assert phase_cfg.outputs["net"].extent is not None
    assert phase_cfg.outputs["net"].minimal_stream_geometry_path == "permanent.gpkg"
    # The one block the whole-file (objective, variable) route builds, no other.
    [block] = phase_cfg.objective_blocks
    assert (str(block.metric), list(block.uses_outputs)) == ("distance_gap", ["net"])


def test_the_root_search_counts_both_bounds() -> None:
    cfg = _config({"variable": "net", "objective": "distance_gap"})

    phase_cfg = _phase_config(cfg, cfg.phases[0])

    assert _engine_kwargs(phase_cfg, _SPACE, start_at=None)["roots"] == 2


def test_a_variable_inherited_from_the_section_is_kept_too() -> None:
    cfg = _config({"objective": "distance_gap"}, variable="net")

    phase_cfg = _phase_config(cfg, cfg.phases[0])

    assert set(phase_cfg.outputs) == {"net"}
    assert _engine_kwargs(phase_cfg, _SPACE, start_at=None)["roots"] == 2


@pytest.mark.parametrize("variable", ["discharge", "well"])
def test_no_other_output_is_inherited(variable: str) -> None:
    cfg = _config({"variable": variable, "objective": "nse", "method": "grid"})

    phase_cfg = _phase_config(cfg, cfg.phases[0])

    # The phase keeps the output its variable names and nothing else; a raw
    # variable names none.
    assert set(phase_cfg.outputs) == ({"well"} if variable == "well" else set())
    assert "net" not in phase_cfg.outputs
