"""The recharge rate a search moves is read in the unit the file declares."""

from __future__ import annotations

import pytest

from hydromodpy.calibration.targets import calibration_targets
from hydromodpy.config import HydroModPyConfig
from hydromodpy.physics.flow.sinks_sources.recharge import FlowRechargeConfig


@pytest.mark.parametrize("units", ["mm/day", "m/day"])
def test_recharge_target_reads_the_unit_of_the_recharge_block(units: str) -> None:
    cfg = HydroModPyConfig.model_validate(
        {
            "workflow": {"mode": "simulation"},
            "workspace": {"project_root": "."},
            "geographic": {"catchment": {"catch_def": "dem", "dem_init_path": "dem.tif"}},
        }
    )
    cfg.flow.sinks_sources.recharge = FlowRechargeConfig(units=units, values=1.0)

    found = {target.path: target for target in calibration_targets(cfg)}

    assert found["flow.sinks_sources.recharge.values"].units == units
