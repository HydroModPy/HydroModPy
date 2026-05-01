"""Adapter for the ``flow/modflownwt`` solver pair.

This module contains only the MODFLOW-NWT-specific construction step. The
shared execution lifecycle lives in
``hydromodpy.solver.modflow_common.flow_adapter_helpers``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.modflow_common.calibration_extractors import (
    extract_discharge_from_cbc,
    extract_head_from_hds,
)
from hydromodpy.solver.modflow_common.flow_adapter_helpers import (
    build_preprocess_options,
    resolve_run_model_name,
    run_flow_model,
)
from hydromodpy.solver.modflow_nwt.nwt import ModflowNwt


class ModflowNwtFlowAdapter:
    """Bridge one planned ``flow/modflownwt`` run to the ``ModflowNwt`` API."""

    process_type = "flow"
    solver_name = "modflownwt"
    requires: tuple[tuple[str, str], ...] = ()

    def validate(self, ctx: RunContext) -> None:
        """No precondition checks for MODFLOW-NWT flow runs."""

    def cleanup(self, ctx: RunContext) -> None:
        """Remove the scratch directory written by this run, if any."""
        solver_output_dir = ctx.state.execution.output_dirs_by_run_id.get(ctx.run.id)
        if solver_output_dir is not None:
            cleanup_solver_files(solver_output_dir)

    def extract_calibration_series(
        self,
        ctx: RunContext,
        store: Any,
        *,
        variable: str,
        station_cells: Mapping[str, tuple[int, int, int]] | None = None,
        time_index: pd.DatetimeIndex | None = None,
    ) -> pd.Series:
        """Read the simulated calibration series from the scratch CBC/HDS files.

        Lightweight calibration trials never go through the ``store``: they read
        ``ctx.state.execution.output_dirs_by_run_id`` directly. ``store`` is
        accepted for Protocol uniformity but unused here.
        """
        del store
        output_dir = ctx.state.execution.output_dirs_by_run_id.get(ctx.run.id)
        model = ctx.state.execution.models_by_run_id.get(ctx.run.id)
        if output_dir is None or model is None:
            raise RuntimeError(f"No solver output recorded for run {ctx.run.id!r}")
        model_name = getattr(model, "model_name", None) or getattr(model, "name", None)
        if model_name is None:
            raise RuntimeError(f"Model name is missing for run {ctx.run.id!r}")
        output_dir = Path(output_dir)

        if variable == "discharge":
            return extract_discharge_from_cbc(output_dir, model_name, time_index)
        if variable == "head":
            if not station_cells:
                raise ValueError("head calibration requires station_cells")
            series_by_station = extract_head_from_hds(
                output_dir,
                model_name,
                station_cells=station_cells,
                time_index=time_index,
            )
            if len(station_cells) == 1:
                station_id = next(iter(station_cells))
                try:
                    return series_by_station[station_id]
                except KeyError as exc:
                    raise KeyError(f"No head series extracted for station {station_id!r}") from exc
            raise ValueError(
                "extract_calibration_series returns one series; pass station_cells "
                "with a single entry per call for head calibration."
            )
        raise NotImplementedError(
            f"MODFLOW-NWT calibration extraction is not implemented for variable {variable!r}."
        )

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one MODFLOW-NWT flow run.

        The method is intentionally thin:

        - resolve the shared preprocessing options,
        - derive the stable model folder name for this run,
        - build the concrete ``ModflowNwt`` object,
        - delegate the rest of the lifecycle to ``run_flow_model``.
        """

        state = ctx.state
        preprocess_options = build_preprocess_options(state)
        model_name = resolve_run_model_name(ctx)
        # This is the only MODFLOW-NWT-specific part of the adapter: wiring
        # the correct config section into the concrete solver class.
        model_modflow = ModflowNwt(
            state.setup.geographic,
            model_folder=state.setup.workspace.solver_scratch_folder,
            model_name=model_name,
            bin_path=state.setup.workspace.bin_path,
            modflow_config=state.cfg.modflownwt,
            preprocess_options=preprocess_options,
        )
        return run_flow_model(ctx, model_modflow, preprocess_options)
