"""A phase that sets no ``parallel`` takes the one of ``[calibration]``.

The phases a protocol writes declare none, so ``[calibration] parallel = 4``
used to reach none of them: every stage of the protocol ran its trials one by
one whatever the section said.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.runners.staged_runner import _phase_config

pytestmark = pytest.mark.unit


def _config(*, parallel: int, batch_size: int, phases: list[dict]) -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "method": "grid",
            "parallel": parallel,
            "batch_size": batch_size,
            "parameters": {
                "K": {"bounds": [1e-9, 1e-3], "path": "flow.param.K.field.value"},
                "Sy": {"bounds": [1e-3, 3e-1], "path": "flow.param.Sy.field.value"},
            },
            "variable": "discharge",
            "objective": "nse_log",
            "phases": phases,
        }
    )


def test_a_phase_without_its_own_takes_the_section_value() -> None:
    cfg = _config(parallel=4, batch_size=6, phases=[{"name": "k", "parameters": ["K"]}])

    phase_cfg = _phase_config(cfg, cfg.phases[0])

    assert phase_cfg.parallel == 4
    assert phase_cfg.batch_size == 6
    assert cfg.parallel_for(cfg.phases[0]) == 4


def test_a_phase_value_wins_over_the_section() -> None:
    cfg = _config(
        parallel=4,
        batch_size=1,
        phases=[{"name": "sy", "parameters": ["Sy"], "parallel": 2, "batch_size": 3}],
    )

    phase_cfg = _phase_config(cfg, cfg.phases[0])

    assert phase_cfg.parallel == 2
    assert phase_cfg.batch_size == 3
    assert cfg.parallel_for() == 4
