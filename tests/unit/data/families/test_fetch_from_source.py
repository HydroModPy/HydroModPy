"""A source computed from its section never reads the mask the loader injects.

The runtime loader fills ``mask_path`` on every source whose model declares it,
``constant`` and ``synthetic`` included. They need no extent, so a mask file that
is missing or not delineated yet must not stop them.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from hydromodpy.data.variables.oceanic.config import OceanicSourceConfig
from hydromodpy.data.variables.oceanic.variable import OceanicVariable
from hydromodpy.data.variables.recharge.config import RechargeSourceConfig
from hydromodpy.data.variables.recharge.variable import RechargeVariable

PERIOD = (datetime(2020, 1, 1), datetime(2020, 1, 31))
MISSING_MASK = Path("/nonexistent/watershed.shp")


def test_constant_sea_level_ignores_a_missing_mask():
    cfg = OceanicSourceConfig(source="constant", value=0.3, mask_path=MISSING_MASK)
    variable = OceanicVariable(config=None, index=None, project_period=PERIOD)

    assert len(variable._fetch_from_source(cfg)) == 1


def test_synthetic_recharge_ignores_a_missing_mask():
    cfg = RechargeSourceConfig(source="synthetic", values=[1.0], mask_path=MISSING_MASK)
    variable = RechargeVariable(config=None, index=None, project_period=PERIOD)

    assert variable._fetch_from_source(cfg)
