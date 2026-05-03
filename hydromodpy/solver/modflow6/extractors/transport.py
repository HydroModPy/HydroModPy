"""Output adapter for MODFLOW 6 GWT transport results.

The concentration binary format (``.ucn``) is identical to what MT3DMS
produces, so this adapter derives from ``Mt3dmsExtractorBase`` and only
redeclares its ``solver_name``.
"""

from __future__ import annotations

from hydromodpy.solver.modflow_common.mt3dms_extractor_base import Mt3dmsExtractorBase


class Modflow6GwtOutputAdapter(Mt3dmsExtractorBase):
    """Ingest MODFLOW 6 GWT concentration outputs into a SimulationCatalog."""

    solver_name = "modflow6gwt"
