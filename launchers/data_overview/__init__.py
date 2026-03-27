"""Data Overview launcher — "watershed identity card" workflow.

This subpackage hosts the launcher that:
- delineates a watershed from outlet coordinates;
- downloads all available data for the site;
- generates an overview report (PNGs) without running any simulation.
"""

from launchers.data_overview.launcher import DataOverviewLauncher

__all__ = ["DataOverviewLauncher"]
