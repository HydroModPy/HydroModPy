"""Compact HTML synthesis for network-distance comparisons."""

from __future__ import annotations

from .builder import CompactNetworkSynthesisBuilder, build_compact_network_synthesis
from .io import (
    CompactNetworkSynthesisConfig,
    GroupSection,
    InfoCard,
    SimulationMeta,
    SimulationRecord,
    resolve_recorded_path,
)

__all__ = (
    "CompactNetworkSynthesisBuilder",
    "CompactNetworkSynthesisConfig",
    "GroupSection",
    "InfoCard",
    "SimulationMeta",
    "SimulationRecord",
    "build_compact_network_synthesis",
    "resolve_recorded_path",
)
