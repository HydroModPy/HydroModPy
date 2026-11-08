"""Adapter for the ``transport/modflow6_prt`` solver pair."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel

from hydromodpy.core.exceptions import SolverDivergedError
from hydromodpy.model.transport.transport_config import TransportModflow6PrtConfig
from hydromodpy.results.storage.kept import Retention
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.base.plan import ProcessRun, RunContext, RunSlot, SolverRun
from hydromodpy.solver.base.registry import extractors
from hydromodpy.solver.base.transport_runs import required_flow_model
from hydromodpy.solver.modflow6.prt import Modflow6Prt


def _prt_output_suffix(runs: list[ProcessRun], run: ProcessRun) -> str:
    prt_runs = [
        planned
        for planned in runs
        if planned.process_type == "transport" and planned.solver == "modflow6_prt"
    ]
    for index, planned in enumerate(prt_runs, start=1):
        if planned.id == run.id:
            return "_prt" if index == 1 else f"_prt_s{index}"
    return "_prt"


class Modflow6PrtTransportAdapter:
    """Adapter for ``transport/modflow6_prt`` particle tracking runs."""

    name: ClassVar[str] = "modflow6_prt"
    process_type: ClassVar[str] = "transport"
    accepted_meshes: ClassVar[frozenset[str]] = frozenset()
    geometry: ClassVar[str] = "cells"
    writes: ClassVar[tuple[str, ...]] = (
        "particles/x",
        "particles/y",
        "particles/z",
        "particles/time",
        "particles/status",
        "particles/reason",
    )
    reads: ClassVar[tuple[str, ...]] = ("face_flow",)
    supports: ClassVar[frozenset[str]] = frozenset()
    options: ClassVar[type[BaseModel] | None] = TransportModflow6PrtConfig
    category: ClassVar[str] = "distributed"
    native_step: ClassVar[str | None] = None
    mutable: ClassVar[frozenset[str]] = frozenset()
    requires: ClassVar[tuple[tuple[str, str], ...]] = (("flow", "modflow6"),)
    produces_particles: bool = True

    def validate(self, model: Any, options: BaseModel | None, slot: RunSlot) -> None:
        """No precondition checks beyond the declared MODFLOW 6 flow dependency."""

    def build(
        self, model: Any, options: BaseModel | None, slot: RunSlot, ctx: RunContext
    ) -> SolverRun:
        """Build the PRT model of the flow run it follows, in memory, under ``slot``.

        The particles are tracked beside the flow model, in the folder of the
        slot and under the name of the flow model. The adapter reads its setup
        and its upstream run on the run context until the transport port takes
        the ``Model``.
        """
        state = ctx.state
        flow_model = required_flow_model(ctx)
        solver_model = Modflow6Prt(
            state.setup.domain,
            state.setup.transport,
            flow_model,
            model_folder=slot.folder,
            model_name=flow_model.model_name,
            suffix_name=_prt_output_suffix(ctx.plan.runs, ctx.run),
        )
        solver_model.pre_processing()
        return SolverRun(slot=slot, model=model, options=options, solver_model=solver_model)

    def run(self, solver_run: SolverRun) -> SolverRun:
        """Write the PRT input files unless they are written, track, and return the solved run."""
        solver_model = solver_run.solver_model
        success = solver_model.processing(
            write_model=not solver_run.written, run_model=True, verbose=True
        )
        if not success:
            raise SolverDivergedError(
                f"[HMPY.E401] Particle transport solver '{self.name}' failed for run "
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
        """Write the particle tracks through the registered extractor."""
        extractors.create(self.process_type, self.name).extract(solver_run, store, retention)

    def cleanup(self, solver_run: SolverRun) -> None:
        """Remove the scratch directory written by this run, if any."""
        if solver_run.output_dir is not None:
            cleanup_solver_files(solver_run.output_dir)
