"""Output adapter for MODFLOW 6 GWT transport results.

The concentration binary format (``.ucn``) is identical to what MT3DMS
produces, so this adapter derives from ``Mt3dmsOutputAdapter`` and only
redeclares its ``solver_name``.
"""

from __future__ import annotations

from hydromodpy.solver.modflow_nwt.extractors.mt3dms import Mt3dmsOutputAdapter


class Modflow6GwtOutputAdapter(Mt3dmsOutputAdapter):
    """Ingest MODFLOW 6 GWT concentration outputs into a SimulationCatalog."""

    solver_name = "modflow6gwt"
