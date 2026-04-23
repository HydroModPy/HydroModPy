"""Reference calibration cases ported from the legacy analysis module.

Each module under ``hydromodpy.calibration.cases`` exposes a self-contained
analytical benchmark that wires a synthetic chronicle to the calibration
engine through a simulator closure. These cases are used for regression
tests and documentation examples; they are pure Python and do not touch
the catalog or the filesystem.
"""

from __future__ import annotations

from hydromodpy.calibration.cases.groundwater_1d import (
    build_noisy_groundwater_chronicle,
    calibrate_groundwater,
    make_groundwater_simulator,
    simulate_heads,
)
from hydromodpy.calibration.cases.groundwater_1d import (
    default_parameter_space as groundwater_default_parameter_space,
)
from hydromodpy.calibration.cases.recession_brutsaert import (
    BaseflowConfig,
    build_noisy_coarse_sand_chronicle,
    calibrate_brutsaert,
    make_baseflow_simulator,
)

__all__: list[str] = [
    "BaseflowConfig",
    "build_noisy_coarse_sand_chronicle",
    "build_noisy_groundwater_chronicle",
    "calibrate_brutsaert",
    "calibrate_groundwater",
    "groundwater_default_parameter_space",
    "make_baseflow_simulator",
    "make_groundwater_simulator",
    "simulate_heads",
]
