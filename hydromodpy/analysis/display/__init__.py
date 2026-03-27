"""Public entry points for HydroModPy display and reporting helpers."""

from hydromodpy.analysis.display.adapters import (
    observed_discharge_series,
    observed_piezometry_series,
)
from hydromodpy.analysis.display.options import (
    DisplayConfig,
    DisplayOptions,
    DisplaySectionOptions,
    display_options_from_raw_toml,
)
from hydromodpy.analysis.display.orchestration import (
    plot_boussinesq_flow_suite,
    plot_flow_suite,
    plot_particles_suite,
    plot_transport_suite,
)

__all__ = [
    "DisplayConfig",
    "DisplayOptions",
    "DisplaySectionOptions",
    "display_options_from_raw_toml",
    "observed_discharge_series",
    "observed_piezometry_series",
    "plot_boussinesq_flow_suite",
    "plot_flow_suite",
    "plot_particles_suite",
    "plot_transport_suite",
]
