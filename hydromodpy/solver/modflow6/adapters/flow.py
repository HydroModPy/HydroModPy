"""Adapter for the ``flow/modflow6`` solver pair.

This module contains only the MODFLOW 6-specific construction step. The
shared flow execution lifecycle lives in
``hydromodpy.solver.modflow_common.flow_adapter_helpers``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.modflow6.modflow6 import Modflow6
from hydromodpy.solver.modflow_common.calibration_extractors import (
    extract_discharge_from_cbc,
    extract_head_from_hds,
)
from hydromodpy.solver.modflow_common.flow_adapter_helpers import (
    build_preprocess_options,
    resolve_run_model_name,
    run_flow_model,
)


class Modflow6FlowAdapter:
    """Bridge one planned ``flow/modflow6`` run to the ``Modflow6`` API."""

    process_type = "flow"
    solver_name = "modflow6"
    requires: tuple[tuple[str, str], ...] = ()

    def validate(self, ctx: RunContext) -> None:
        """No precondition checks for MODFLOW 6 flow runs."""

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

        MF6 binaries share the FloPy-readable format used by MODFLOW-NWT, so
        the same helpers in ``modflow_common.calibration_extractors`` apply.
        ``store`` is accepted for Protocol uniformity but unused on this path.
        """
        del store
        output_dir = ctx.state.execution.output_dirs_by_run_id.get(ctx.run.id)
        model = ctx.state.execution.models_by_run_id.get(ctx.run.id)
        if output_dir is None or model is None:
            return pd.Series(dtype=float, name=variable)
        model_name = getattr(model, "model_name", None) or getattr(model, "name", None)
        if model_name is None:
            return pd.Series(dtype=float, name=variable)
        output_dir = Path(output_dir)

        if variable == "discharge":
            return extract_discharge_from_cbc(output_dir, model_name, time_index)
        if variable == "head":
            if not station_cells:
                return pd.Series(dtype=float, name=variable)
            series_by_station = extract_head_from_hds(
                output_dir,
                model_name,
                station_cells=station_cells,
                time_index=time_index,
            )
            if len(station_cells) == 1:
                station_id = next(iter(station_cells))
                return series_by_station.get(station_id, pd.Series(dtype=float, name=variable))
            raise ValueError(
                "extract_calibration_series returns one series; pass station_cells "
                "with a single entry per call for head calibration."
            )
        return pd.Series(dtype=float, name=variable)

    @staticmethod
    def _solver_runtime_cache(state) -> dict[tuple[str, str, str], Modflow6]:
        cache = getattr(state.setup, "_flow_solver_runtime_cache", None)
        if isinstance(cache, dict):
            return cache
        cache = {}
        state.setup._flow_solver_runtime_cache = cache
        return cache

    @staticmethod
    def _reuse_solver_model_enabled(state) -> bool:
        overrides = getattr(state.setup, "flow_runtime_overrides", None)
        return bool(isinstance(overrides, Mapping) and overrides.get("reuse_solver_model", False))

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one MODFLOW 6 flow run.

        The method is intentionally narrow in scope:

        - resolve the shared preprocessing options,
        - derive the stable model folder name for this run,
        - build the concrete ``Modflow6`` object,
        - delegate the common run lifecycle to ``run_flow_model``.
        """

        state = ctx.state
        preprocess_options = build_preprocess_options(state)
        model_name = resolve_run_model_name(ctx)
        model_modflow = None
        if self._reuse_solver_model_enabled(state):
            cache = self._solver_runtime_cache(state)
            cache_key = (self.solver_name, str(ctx.run.id), str(model_name))
            model_modflow = cache.get(cache_key)
            if model_modflow is None:
                model_modflow = Modflow6(
                    state.setup.geographic,
                    model_folder=state.setup.workspace.simulations_folder,
                    model_name=model_name,
                    bin_path=state.setup.workspace.bin_path,
                    modflow_config=state.cfg.modflow6,
                    preprocess_options=preprocess_options,
                )
                cache[cache_key] = model_modflow
        # This is the only MODFLOW 6-specific part of the adapter: wiring the
        # MF6 config block into the concrete solver implementation.
        if model_modflow is None:
            model_modflow = Modflow6(
                state.setup.geographic,
                model_folder=state.setup.workspace.solver_scratch_folder,
                model_name=model_name,
                bin_path=state.setup.workspace.bin_path,
                modflow_config=state.cfg.modflow6,
                preprocess_options=preprocess_options,
            )
        return run_flow_model(ctx, model_modflow, preprocess_options)
