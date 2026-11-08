"""Adapter for the ``transport/modflow6`` solver pair."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd
from pydantic import BaseModel

from hydromodpy.core.contracts.observables import ObservableRequest, ObservableResult
from hydromodpy.core.exceptions import ObservableNotAvailableError, SolverDivergedError
from hydromodpy.model.transport.transport_config import TransportModflow6GwtConfig
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.base.plan import RunContext, RunExecutionResult
from hydromodpy.solver.base.transport_runs import required_flow_model, transport_output_suffix
from hydromodpy.solver.modflow6.transport import Modflow6Transport


class Modflow6GwtTransportAdapter:
    """Adapter for ``transport/modflow6`` runs."""

    name: ClassVar[str] = "modflow6"
    process_type: ClassVar[str] = "transport"
    accepted_meshes: ClassVar[frozenset[str]] = frozenset()
    geometry: ClassVar[str] = "cells"
    writes: ClassVar[tuple[str, ...]] = (
        "concentration",
        "mass_balance",
    )
    reads: ClassVar[tuple[str, ...]] = ("face_flow",)
    supports: ClassVar[frozenset[str]] = frozenset()
    options: ClassVar[type[BaseModel] | None] = TransportModflow6GwtConfig
    category: ClassVar[str] = "distributed"
    native_step: ClassVar[str | None] = None
    mutable: ClassVar[frozenset[str]] = frozenset()
    requires: ClassVar[tuple[tuple[str, str], ...]] = (("flow", "modflow6"),)
    produces_concentration: bool = True

    def validate(self, ctx: RunContext) -> None:
        """No precondition checks for MODFLOW 6 GWT transport runs."""

    def cleanup(self, ctx: RunContext) -> None:
        """Remove the scratch directory written by this run, if any."""
        solver_output_dir = ctx.output_dir
        if solver_output_dir is not None:
            cleanup_solver_files(solver_output_dir)

    def extract_observables(
        self,
        ctx: RunContext,
        store: Any,
        requests: Sequence[ObservableRequest],
        *,
        time_index: pd.DatetimeIndex | None = None,
    ) -> dict[str, ObservableResult]:
        """Fail explicitly because transport calibration is not implemented."""
        del ctx, store, time_index
        if not requests:
            return {}
        names = sorted({request.name for request in requests})
        raise ObservableNotAvailableError(
            f"MODFLOW 6 GWT produces no calibration observable; asked for {names}."
        )

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one MODFLOW 6 GWT concentration run."""

        state = ctx.state
        flow_model = required_flow_model(ctx)
        model_transport = Modflow6Transport(
            state.setup.domain,
            state.setup.transport,
            flow_model,
            model_folder=state.setup.workspace.solver_scratch_folder,
            model_name=flow_model.model_name,
            suffix_name=transport_output_suffix(ctx.plan, ctx.run),
        )
        model_transport.pre_processing()
        success = model_transport.processing(write_model=True, run_model=True, verbose=True)
        if not success:
            raise SolverDivergedError(
                f"[HMPY.E401] Transport solver '{ctx.run.solver}' failed for run '{ctx.run.id}'. "
                f"See {getattr(model_transport, 'full_path', '<unknown>')} for diagnostics.",
                run_id=ctx.run.id,
            )
        return RunExecutionResult(
            primary_model=model_transport,
            solver_output_dir=Path(model_transport.full_path)
            if hasattr(model_transport, "full_path")
            else None,
        )
