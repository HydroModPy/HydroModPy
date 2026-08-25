"""Which scoring route a phase takes, and what it must not inherit.

``build_metric_extractor`` prefers the objective blocks over the single-metric
variable whenever both reach it. A phase that declares ``variable`` and
``objective`` and inherits the blocks of another phase would therefore be
scored on that other phase's criterion, silently and with a plausible number.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.runners.staged_runner import _phase_config

NETWORK_PHASE = {
    "name": "steady_k_over_r",
    "method": "bisection",
    "parameters": ["K"],
    "objective_blocks": ["abherve_gap"],
    "freeze_on_success": True,
}
DISCHARGE_PHASE = {
    "name": "transient_sy",
    "method": "grid",
    "parameters": ["Sy"],
    "variable": "discharge",
    "objective": "nse_log",
    "depends_on": "steady_k_over_r",
}


def _config(phases: list[dict]) -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "method": "grid",
            "parameters": {
                "K": {"bounds": [1e-9, 1e-3], "path": "flow.param.K.field.value"},
                "Sy": {"bounds": [1e-3, 3e-1], "path": "flow.param.Sy.field.value"},
            },
            "outputs": {"net": {"support": "network", "stream_geometry_path": "streams.gpkg"}},
            "objective_blocks": [
                {"name": "abherve_gap", "metric": "distance_gap", "uses_outputs": ["net"]}
            ],
            "phases": phases,
        }
    )


def test_a_single_metric_phase_inherits_no_block() -> None:
    cfg = _config([NETWORK_PHASE, DISCHARGE_PHASE])
    phase_cfg = _phase_config(cfg, cfg.phases[1])

    assert phase_cfg.objective_blocks == []
    assert phase_cfg.outputs == {}
    assert phase_cfg.variable == "discharge"
    assert phase_cfg.objective == "nse_log"


def test_a_block_phase_keeps_what_it_selected() -> None:
    cfg = _config([NETWORK_PHASE, DISCHARGE_PHASE])
    phase_cfg = _phase_config(cfg, cfg.phases[0])

    assert [block.name for block in phase_cfg.objective_blocks] == ["abherve_gap"]
    assert set(phase_cfg.outputs) == {"net"}


def test_declaring_both_conventions_is_refused() -> None:
    with pytest.raises(ValueError, match="Pick one convention"):
        _config([{**DISCHARGE_PHASE, "depends_on": None, "objective_blocks": ["abherve_gap"]}])


def test_a_single_metric_phase_selecting_an_output_is_refused() -> None:
    with pytest.raises(ValueError, match="Pick one convention"):
        _config([{**DISCHARGE_PHASE, "depends_on": None, "outputs": ["net"]}])


@pytest.mark.parametrize("field", ["variable", "objective"])
def test_either_field_alone_picks_the_single_metric_route(field: str) -> None:
    cfg = _config([NETWORK_PHASE, {**DISCHARGE_PHASE, **{field: None}}])
    assert cfg.phases[1].is_single_metric is True
    assert _phase_config(cfg, cfg.phases[1]).objective_blocks == []
