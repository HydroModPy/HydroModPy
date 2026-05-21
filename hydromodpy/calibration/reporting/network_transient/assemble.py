"""Public entry points and page composition for the network/transient report.

This module re-exports the orchestration surface used by
``hydromodpy/calibration/reporting/network_transient_html.py``. Concrete
implementations live in the historical module for backward compatibility with
the heavy module-level globals mutated by ``_configure_from_args``; this slim
module documents the boundary between concerns and is the file split target
of T2 lot B (rapport 20, recommandation 4.4).
"""

from __future__ import annotations

from hydromodpy.calibration.reporting.network_transient.io import (
    NetworkTransientHtmlArtifactReport,
    inspect_network_transient_html_artifacts,
)

__all__ = [
    "NetworkTransientHtmlArtifactReport",
    "build_network_transient_html",
    "build_network_transient_html_from_args",
    "inspect_network_transient_html_artifacts",
    "main",
]


def build_network_transient_html(**kwargs):
    """Build the calibration diagnostic page from Python code (facade re-export)."""
    from hydromodpy.calibration.reporting import network_transient_html

    return network_transient_html.build_network_transient_html(**kwargs)


def build_network_transient_html_from_args(args):
    """Build the calibration diagnostic page from parsed CLI arguments."""
    from hydromodpy.calibration.reporting import network_transient_html

    return network_transient_html.build_network_transient_html_from_args(args)


def main() -> None:
    """CLI entry point for the network/transient HTML report."""
    from hydromodpy.calibration.reporting import network_transient_html

    network_transient_html.main()
