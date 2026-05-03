"""Stream-network analysis helpers.

This package hosts metrics that compare a computed simulated active network
against persisted hydrographic-network roles, typically ``reference``.
"""

from __future__ import annotations

from hydromodpy.analysis.stream_networks.metrics import (
    simulated_active_network_distance_metrics,
)

__all__ = ["simulated_active_network_distance_metrics"]
