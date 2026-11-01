"""Lake-bed reconstruction from bathymetry, reconciled to the abacus.

Pure ``spatial`` building blocks the MODFLOW 6 build uses to carve a real lake
basin into the grid instead of a flat reservoir:

* :func:`cell_bed_from_surface` - conservative (zonal) raster-to-cell bed.
* :func:`reconcile_bed_to_abacus` - area-weighted quantile map onto the abacus.
* :func:`simulate_abacus` - flood a per-cell bed into a stage-volume-area curve.
* :func:`reconstruct_lake_bed` - the regrid + reconcile pipeline for one lake.

The re-grade of a mesh column around the bed, ``regrade_column_to_bed``, lives in
``hydromodpy/solver/modflow6/builders/lake_column_regrade.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
