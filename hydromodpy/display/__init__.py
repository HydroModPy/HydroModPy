"""Public entry points for HydroModPy display and post-processing helpers.

This package is the small facade that external code is expected to import.
It exposes:
- configuration objects that describe how figures should be rendered;
- orchestration functions that run the flow, particle, and transport display
  suites for a completed simulation;
- adapter functions that bridge ``data_managers`` PointRecords to display inputs;
- the generic ``figures`` sub-package for standalone figure creation.

Callers do not need to know the internal module layout of ``hydromodpy.display``:
they can import the normalized options and the high-level suite functions here.
"""

from hydromodpy.display.adapters import (
    observed_discharge_series,
    observed_piezometry_series,
)
from hydromodpy.display.options import (
    DisplayConfig,
    DisplayOptions,
    DisplaySectionOptions,
    display_options_from_raw_toml,
)
from hydromodpy.display.orchestration import (
    plot_boussinesq_flow_suite,
    plot_flow_suite,
    plot_particles_suite,
    plot_transport_suite,
)

__all__ = [
    # Configuration
    "DisplayConfig",
    "DisplayOptions",
    "DisplaySectionOptions",
    "display_options_from_raw_toml",
    # Adapters
    "observed_discharge_series",
    "observed_piezometry_series",
    # Orchestration suites
    "plot_boussinesq_flow_suite",
    "plot_flow_suite",
    "plot_particles_suite",
    "plot_transport_suite",
]
