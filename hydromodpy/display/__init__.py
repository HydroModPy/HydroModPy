"""Public entry points for HydroModPy display and post-processing helpers.

This package is the small facade that external code is expected to import.
It exposes:
- configuration objects that describe how figures should be rendered;
- orchestration functions that run the flow, particle, and transport display
  suites for a completed simulation.

Callers do not need to know the internal module layout of ``hydromodpy.display``:
they can import the normalized options and the high-level suite functions here.
"""

from hydromodpy.display.options import (
    DisplayConfig,
    DisplayOptions,
    DisplaySectionOptions,
    display_options_from_raw_toml,
)
from hydromodpy.display.suites import (
    plot_flow_suite,
    plot_particles_suite,
    plot_transport_suite,
)

__all__ = [
    "DisplayConfig",
    "DisplayOptions",
    "DisplaySectionOptions",
    "display_options_from_raw_toml",
    "plot_flow_suite",
    "plot_particles_suite",
    "plot_transport_suite",
]
