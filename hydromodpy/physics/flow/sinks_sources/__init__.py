"""
Flow sink/source schemas for the ``[flow.sinks_sources]`` TOML section.

Sub-modules:

- :mod:`.wells`     -- :class:`FlowWellConfig` and forcing payloads,
- :mod:`.recharge`  -- :class:`FlowRechargeConfig`,
- :mod:`.etp`       -- :class:`FlowEtpConfig` (the unique EVT entry point),
- :mod:`.container` -- :class:`FlowSinksSourcesConfig` aggregating the three.
"""

from __future__ import annotations

from hydromodpy.physics.flow.sinks_sources.container import FlowSinksSourcesConfig
from hydromodpy.physics.flow.sinks_sources.etp import FlowEtpConfig
from hydromodpy.physics.flow.sinks_sources.lake import (
    FlowLakeConfig,
    FlowLakeOutletConfig,
    FlowLakeOutletManning,
    FlowLakeOutletMover,
    FlowLakeOutletSpecified,
    FlowLakeOutletWeir,
)
from hydromodpy.physics.flow.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.physics.flow.sinks_sources.sfr import (
    FlowReachConfig,
    FlowReachDiversionConfig,
    FlowReachNetworkConfig,
    FlowReachWidthByOrder,
    FlowReachWidthConfig,
    FlowReachWidthConstant,
    FlowReachWidthPowerLaw,
)
from hydromodpy.physics.flow.sinks_sources.wells import (
    FlowWellConfig,
    FlowWellForcingConfig,
    FlowWellForcingConstantConfig,
    FlowWellForcingCsvConfig,
    FlowWellForcingPiecewiseConfig,
    FlowWellForcingSeasonalConfig,
    FlowWellForcingSegment,
    FlowWellLocation,
    FlowWellLocationAbsoluteXY,
    FlowWellLocationCell,
    FlowWellLocationRelativeXY,
)

__all__ = [
    "FlowEtpConfig",
    "FlowLakeConfig",
    "FlowLakeOutletConfig",
    "FlowLakeOutletManning",
    "FlowLakeOutletMover",
    "FlowLakeOutletSpecified",
    "FlowLakeOutletWeir",
    "FlowReachConfig",
    "FlowReachDiversionConfig",
    "FlowReachNetworkConfig",
    "FlowReachWidthByOrder",
    "FlowReachWidthConfig",
    "FlowReachWidthConstant",
    "FlowReachWidthPowerLaw",
    "FlowRechargeConfig",
    "FlowSinksSourcesConfig",
    "FlowWellConfig",
    "FlowWellForcingConfig",
    "FlowWellForcingConstantConfig",
    "FlowWellForcingCsvConfig",
    "FlowWellForcingPiecewiseConfig",
    "FlowWellForcingSeasonalConfig",
    "FlowWellForcingSegment",
    "FlowWellLocation",
    "FlowWellLocationAbsoluteXY",
    "FlowWellLocationCell",
    "FlowWellLocationRelativeXY",
]
