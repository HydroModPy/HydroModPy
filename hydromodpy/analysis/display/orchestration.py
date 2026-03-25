"""Compatibility facade for launcher-managed display suites.

The implementation now lives in :mod:`hydromodpy.analysis.display.suites`.
This module remains as the stable import path used by the public package API.
"""
from hydromodpy.analysis.display.suites import (
    plot_boussinesq_flow_suite,
    plot_flow_suite,
    plot_particles_suite,
    plot_transport_suite,
)

__all__ = [
    "plot_boussinesq_flow_suite",
    "plot_flow_suite",
    "plot_particles_suite",
    "plot_transport_suite",
]
