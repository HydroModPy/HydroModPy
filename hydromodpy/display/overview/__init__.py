"""Overview report - watershed identity-card panel rendering.

Consumes a :class:`DataOverviewState` (pre-simulation: geographic + loaded
data only) and the rows of its data inventory, and produces one PNG per
enabled panel in ``[overview.panels]``. Unlike the ``display.figures``
registry (which binds to :class:`hydromodpy.results.run.Run`), overview
panels run without any simulation result. The page is written after the
seal by ``display.report``. :func:`overview_name` is the directory name an
overview claims under ``runs/``.
"""

from __future__ import annotations

from hydromodpy.display.overview.location import overview_name
from hydromodpy.display.overview.report import PANEL_FILES, generate_overview_report

__all__ = ["PANEL_FILES", "generate_overview_report", "overview_name"]
