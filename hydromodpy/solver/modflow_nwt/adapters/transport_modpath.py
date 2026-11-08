"""Adapter for the ``transport/modpath`` solver pair."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import rasterio
from pydantic import BaseModel

from hydromodpy.core.exceptions import SolverDivergedError
from hydromodpy.core.io.raster_io import export_tif
from hydromodpy.model.transport.transport_config import TransportModpathConfig
from hydromodpy.results.storage.kept import Retention
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.base.plan import RunContext, RunSlot, SolverRun
from hydromodpy.solver.base.registry import extractors
from hydromodpy.solver.base.transport_runs import required_flow_model
from hydromodpy.solver.modflow_nwt.modpath.modpath import Modpath


class ModpathTransportAdapter:
    """Adapter for ``transport/modpath`` runs."""

    name: ClassVar[str] = "modpath"
    process_type: ClassVar[str] = "transport"
    accepted_meshes: ClassVar[frozenset[str]] = frozenset()
    geometry: ClassVar[str] = "raster"
    writes: ClassVar[tuple[str, ...]] = (
        "particles/x",
        "particles/y",
        "particles/z",
        "particles/time",
        "particles/endpoint_x",
        "particles/endpoint_y",
        "particles/endpoint_z",
        "particles/endpoint_time",
    )
    reads: ClassVar[tuple[str, ...]] = ("face_flow",)
    supports: ClassVar[frozenset[str]] = frozenset()
    options: ClassVar[type[BaseModel] | None] = TransportModpathConfig
    category: ClassVar[str] = "distributed"
    native_step: ClassVar[str | None] = None
    mutable: ClassVar[frozenset[str]] = frozenset()
    requires: ClassVar[tuple[tuple[str, str], ...]] = (("flow", "modflow_nwt"),)

    def validate(self, model: Any, options: BaseModel | None, slot: RunSlot) -> None:
        """No precondition checks for Modpath transport runs."""

    def build(
        self, model: Any, options: BaseModel | None, slot: RunSlot, ctx: RunContext
    ) -> SolverRun:
        """Build the MODPATH model of the flow run it follows, in memory, under ``slot``.

        The tracking runs beside the flow model, in the folder of the slot and
        under the name of the flow model, and reads its setup and its upstream
        run on the run context until the transport port takes the ``Model``.
        """
        state = ctx.state
        flow_model = required_flow_model(ctx)
        _restore_seepage_clip_raster(ctx, flow_model)
        solver_model = Modpath(
            state.setup.domain,
            state.setup.transport,
            flow_model,
            model_folder=slot.folder,
            model_name=flow_model.model_name,
            bin_path=slot.bin_dir,
        )
        solver_model.pre_processing()
        return SolverRun(slot=slot, model=model, options=options, solver_model=solver_model)

    def run(self, solver_run: SolverRun) -> SolverRun:
        """Write the MODPATH input files, solve, and return the solved run.

        The legacy post-processing and filtering are skipped:
        ``ModpathOutputAdapter.extract`` reads pathlines and endpoints into the
        run store, and no shapefile is written any more.
        """
        solver_model = solver_run.solver_model
        success = solver_model.processing(write_model=not solver_run.written, run_model=True)
        if not success:
            raise SolverDivergedError(
                f"[HMPY.E401] Transport solver '{self.name}' failed for run "
                f"'{solver_run.slot.name}'. "
                f"See {getattr(solver_model, 'full_path', '<unknown>')} for diagnostics."
            )
        return replace(
            solver_run,
            output_dir=Path(solver_model.full_path) if hasattr(solver_model, "full_path") else None,
            written=True,
            solved=True,
        )

    def extract(self, solver_run: SolverRun, store: Any, retention: Retention) -> None:
        """Write the pathlines and endpoints of a solved run through its registered extractor."""
        extractors.create(self.process_type, self.name).extract(solver_run, store, retention)

    def cleanup(self, solver_run: SolverRun) -> None:
        """Remove the scratch directory written by this run, if any."""
        if solver_run.output_dir is not None:
            cleanup_solver_files(solver_run.output_dir)


def _configured_zone_partic(transport: Any) -> str | None:
    modpath = getattr(transport, "modpath", None)
    parameters = getattr(modpath, "parameters", None)
    if isinstance(parameters, Mapping):
        value = parameters.get("zone_partic")
    else:
        value = getattr(parameters, "zone_partic", None)
    return None if value is None else str(value)


def _restore_seepage_clip_raster(ctx: RunContext, flow_model: Any) -> None:
    """Write the MODPATH seepage raster from the store when requested."""
    if _configured_zone_partic(ctx.state.setup.transport) != "seepage_clip":
        return

    store = ctx.store
    sim_id = getattr(ctx.state, "sim_id", None)
    base_raster = getattr(flow_model, "dem_watershed_path", None)
    full_path = getattr(flow_model, "full_path", None)
    if store is None or sim_id is None or base_raster is None or full_path is None:
        return

    base_path = Path(base_raster)
    if not base_path.is_file():
        return

    seepage_tif = Path(full_path) / "_postprocess" / "_rasters" / "seepage_areas_t(0).tif"
    if seepage_tif.is_file():
        return

    seepage = np.asarray(store.query_field(str(sim_id), "seepage_mask", 0), dtype=float).ravel()
    with rasterio.open(base_path) as src:
        seepage_array = seepage.reshape(src.height, src.width)
    seepage_tif.parent.mkdir(parents=True, exist_ok=True)
    export_tif(str(base_path), seepage_array, str(seepage_tif), -9999.0)
