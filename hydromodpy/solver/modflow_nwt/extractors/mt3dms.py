"""MT3DMS concentration output adapter for the NWT toolchain."""

from __future__ import annotations

from hydromodpy.solver.modflow_common.mt3dms_extractor_base import Mt3dmsExtractorBase


class Mt3dmsOutputAdapter(Mt3dmsExtractorBase):
    """Ingest MT3DMS concentration outputs into a SimulationCatalog."""

    solver_name = "mt3dms"
