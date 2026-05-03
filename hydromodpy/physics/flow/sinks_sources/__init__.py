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
from hydromodpy.physics.flow.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.physics.flow.sinks_sources.wells import (
    FlowWellConfig,
    FlowWellForcingConfig,
    FlowWellForcingConstantConfig,
    FlowWellForcingCsvConfig,
)

__all__ = [
    "FlowEtpConfig",
    "FlowRechargeConfig",
    "FlowSinksSourcesConfig",
    "FlowWellConfig",
    "FlowWellForcingConfig",
    "FlowWellForcingConstantConfig",
    "FlowWellForcingCsvConfig",
]
