"""Extract step - solver result extraction, observation ingestion, modpath helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import numpy as np
import rasterio

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.io.raster_io import export_tif
from hydromodpy.core.logging import get_logger
from hydromodpy.core.workspace.resolve import locate_workspace_root
from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.workflow.internals.state import ExtractedState, PipelineState, SolverRanState

if TYPE_CHECKING:
    from hydromodpy.workflow.context import WorkflowContext

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Observation ingestion
# ---------------------------------------------------------------------------


def step_ingest_observations(ctx: WorkflowContext, sim_id: str) -> None:
    """Ingest observation timeseries associated with this simulation.

    Observation ingestion is part of the scientific record. Failures abort
    the run instead of leaving the catalog half populated.
    """
    from hydromodpy.simulation.extraction.extractors.observation_ingest import (
        ingest_observations,
    )

    try:
        ingest_observations(sim_id, ctx.store, ctx.loaded_data)
    except Exception as exc:
        logger.exception("Failed to ingest observations for sim %s", sim_id)
        raise RuntimeError(f"Failed to ingest observations for sim {sim_id}") from exc


# ---------------------------------------------------------------------------
# Modpath ingestion helper
# ---------------------------------------------------------------------------


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
            arr = catalog.query_field(sim_id, "seepage_mask", 0)
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


# ---------------------------------------------------------------------------
# Pipeline step
# ---------------------------------------------------------------------------


class ExtractStep:
    """Finalize extraction (currently a pass-through after run-time ingestion)."""

    name = "extract"
    tin: ClassVar[type] = SolverRanState
    tout: ClassVar[type] = ExtractedState
    config_sections: ClassVar[tuple[str, ...]] = ()

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("ExtractStep requires 'ctx' in state.data")
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )
