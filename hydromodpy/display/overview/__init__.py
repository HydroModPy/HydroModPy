"""Overview report — watershed identity-card panel rendering.

Consumes a :class:`DataOverviewState` (pre-simulation: geographic + loaded
data only) and produces one PNG per enabled panel in
``[overview.panels]``. Unlike the ``display.figures`` registry (which
binds to :class:`hydromodpy.results.run.Run`), overview panels run
without any simulation result.
"""

from __future__ import annotations

from hydromodpy.display.overview.report import generate_overview_report

__all__ = ["generate_overview_report"]
