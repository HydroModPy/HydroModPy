"""Steady Boussinesq interception benchmark on a sloping hillslope."""

from .comparison import (
    BoussinesqHillslopeInterceptionComparison,
    build_boussinesq_hillslope_interception_comparison,
    run_boussinesq_hillslope_interception_comparison,
)
from .plotting import plot_boussinesq_hillslope_interception_comparison
from .reference import (
    build_hillslope_topography_values,
    expected_hillslope_seepage_profile_at_x,
    hillslope_contact_x,
    hillslope_seepage_emergence_x,
)

__all__ = [
    "BoussinesqHillslopeInterceptionComparison",
    "build_boussinesq_hillslope_interception_comparison",
    "build_hillslope_topography_values",
    "expected_hillslope_seepage_profile_at_x",
    "hillslope_contact_x",
    "hillslope_seepage_emergence_x",
    "plot_boussinesq_hillslope_interception_comparison",
    "run_boussinesq_hillslope_interception_comparison",
]
