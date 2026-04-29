"""Modpath ingestion helpers.

Workflow-side helpers that materialize artefacts the
``solver/modflow_nwt/modpath`` runtime expects to find on disk before it
runs. Centralising this here keeps the ``solver`` layer free of any
``results`` dependency.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import rasterio

from hydromodpy.core.io.raster_io import export_tif
from hydromodpy.core.logging import get_logger
from hydromodpy.core.workspace.resolve import locate_workspace_root
from hydromodpy.results.catalog import SimulationCatalog

logger = get_logger(__name__)


def restore_seepage_raster_from_store(
    project_root: str | Path,
    base_raster_path: str | Path,
    seepage_tif_path: str | Path,
) -> bool:
    """Rebuild the seepage GeoTIFF from the SimulationCatalog.

    Returns ``True`` when the raster has been written, ``False`` otherwise.
    """
    base_raster = Path(base_raster_path)
    if not base_raster.is_file():
        return False

    project_root = Path(project_root)
    workspace_root = locate_workspace_root(project_root) or project_root

    seepage_tif = Path(seepage_tif_path)
    try:
        catalog = SimulationCatalog(workspace_root)
        try:
            sims = catalog.list_simulations()
            if sims.empty:
                return False
            sim_id = str(sims.iloc[-1]["sim_id"])
            arr = catalog.query_field(sim_id, "seepage_areas", 0)
        finally:
            catalog.close()

        seepage_flat = np.asarray(arr, dtype=float).ravel()
        with rasterio.open(base_raster) as src:
            seepage_array = seepage_flat.reshape(src.height, src.width)

        os.makedirs(seepage_tif.parent, exist_ok=True)
        export_tif(str(base_raster), seepage_array, str(seepage_tif), -9999.0)
    except Exception as exc:
        logger.debug("Failed to rebuild seepage from SimulationCatalog: %s", exc)
        return False

    return seepage_tif.is_file()
