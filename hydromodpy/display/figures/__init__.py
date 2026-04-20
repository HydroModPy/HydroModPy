"""Figure implementations.

Importing this package triggers registration of every figure class. Add a new
figure by dropping a file in this directory that imports
:func:`hydromodpy.display.register` and decorates a :class:`BaseFigure`
subclass.
"""

from __future__ import annotations

from hydromodpy.display.figures import (  # noqa: F401
    concentration_map,
    cross_section,
    difference_map,
    hydrograph,
    particle_tracks,
    piezometric_map,
    recharge_map,
    seepage_map,
    water_budget,
)

__all__: list[str] = []
