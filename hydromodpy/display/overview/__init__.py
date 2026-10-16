"""Overview report - watershed identity-card panel rendering.

Consumes a :class:`DataOverviewState` (pre-simulation: geographic + loaded
data only) and produces one PNG per enabled panel in
``[overview.panels]``. Unlike the ``display.figures`` registry (which
binds to :class:`hydromodpy.results.run.Run`), overview panels run
without any simulation result. :func:`overview_name` is the directory name
an overview claims under ``runs/``.
"""

from __future__ import annotations

from hydromodpy.display.overview.location import overview_name
from hydromodpy.display.overview.report import generate_overview_report
from hydromodpy.display.overview.web import overview_web_report_path

__all__ = ["generate_overview_report", "overview_name", "overview_web_report_path"]
