"""Data Overview launcher — "watershed identity card" workflow.

This subpackage hosts the launcher that:
- delineates a watershed from outlet coordinates;
- downloads all available data for the site;
- generates an overview report (PNGs) without running any simulation.
"""

from hydromodpy.workflow.pipelines.overview import DataOverviewLauncher

__all__ = ["DataOverviewLauncher"]
