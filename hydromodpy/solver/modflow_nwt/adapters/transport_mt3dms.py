"""Adapter for the ``transport/mt3dms`` solver pair."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel

from hydromodpy.core.exceptions import SolverDivergedError
from hydromodpy.model.transport.transport_config import TransportMt3dmsConfig
from hydromodpy.results.storage.kept import Retention
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.base.plan import RunContext, RunSlot, SolverRun
from hydromodpy.solver.base.registry import extractors
from hydromodpy.solver.base.transport_runs import required_flow_model, transport_output_suffix
from hydromodpy.solver.modflow_nwt.mt3dms.mt3dms import Mt3dms


class Mt3dmsTransportAdapter:
    """Adapter for ``transport/mt3dms`` runs."""

    name: ClassVar[str] = "mt3dms"
    process_type: ClassVar[str] = "transport"
    accepted_meshes: ClassVar[frozenset[str]] = frozenset()
    geometry: ClassVar[str] = "raster"
    writes: ClassVar[tuple[str, ...]] = ("concentration",)
    reads: ClassVar[tuple[str, ...]] = ("face_flow",)
    supports: ClassVar[frozenset[str]] = frozenset()
    options: ClassVar[type[BaseModel] | None] = TransportMt3dmsConfig
    category: ClassVar[str] = "distributed"
    native_step: ClassVar[str | None] = None
    mutable: ClassVar[frozenset[str]] = frozenset()
    requires: ClassVar[tuple[tuple[str, str], ...]] = (("flow", "modflow_nwt"),)
    produces_concentration: bool = True

    def validate(self, model: Any, options: BaseModel | None, slot: RunSlot) -> None:
        """No precondition checks for MT3DMS transport runs."""

    def build(
        self, model: Any, options: BaseModel | None, slot: RunSlot, ctx: RunContext
    ) -> SolverRun:
        """Build the MT3DMS model of the flow run it follows, in memory, under ``slot``.

        The transport writes beside the flow model, in the folder of the slot
        and under the name of the flow model, and reads its setup and its
        upstream run on the run context until the transport port takes the
        ``Model``.
        """
        state = ctx.state
        flow_model = required_flow_model(ctx)
        solver_model = Mt3dms(
            state.setup.domain,
            state.setup.transport,
            flow_model,
            model_folder=slot.folder,
            model_name=flow_model.model_name,
            suffix_name=transport_output_suffix(ctx.plan, ctx.run),
            bin_path=slot.bin_dir,
        )
        solver_model.pre_processing()
        return SolverRun(slot=slot, model=model, options=options, solver_model=solver_model)

    def run(self, solver_run: SolverRun) -> SolverRun:
        """Write the MT3DMS input files, solve, and return the solved run."""
        solver_model = solver_run.solver_model
        success = solver_model.processing(
            write_model=not solver_run.written, run_model=True, verbose=True
        )
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
        """Write the concentration fields of a solved run through its registered extractor."""
        extractors.create(self.process_type, self.name).extract(solver_run, store, retention)

    def cleanup(self, solver_run: SolverRun) -> None:
        """Remove the scratch directory written by this run, if any."""
        if solver_run.output_dir is not None:
            cleanup_solver_files(solver_run.output_dir)
