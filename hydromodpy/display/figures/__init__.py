"""Figure implementations.

Importing this package triggers registration of every figure class. Add a new
figure by dropping a file in this directory that imports
:func:`hydromodpy.display.register` and decorates a :class:`BaseFigure`
subclass.
"""

from __future__ import annotations

from hydromodpy.display.figures import (  # noqa: F401
    calibration_convergence,
    calibration_landscape,
    calibration_objective_surface,
    calibration_pairplot,
    calibration_posterior,
    calibration_trace,
    concentration_map,
    cross_section,
    difference_map,
    duration_curve,
    ensemble_band,
    hydrograph,
    particle_tracks,
    piezometric_map,
    piper_diagram,
    recession,
    recharge_map,
    schoeller_diagram,
    seasonal_boxplot,
    seepage_map,
    side_by_side_map,
    stiff_diagram,
    water_budget,
    watershed_id_card,
)

__all__: list[str] = []
