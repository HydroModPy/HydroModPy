"""Adapter for the ``flow/modflow_nwt`` solver pair.

This module contains only the MODFLOW-NWT-specific construction step. The
shared execution lifecycle lives in
``hydromodpy.solver.modflow_common.flow_adapter_helpers``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

import pandas as pd

from hydromodpy.core.contracts.observables import ObservableRequest, ObservableResult
from hydromodpy.core.exceptions import ObservableNotAvailableError
from hydromodpy.core.logging import get_logger
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.base.observables import (
    ObservableSupport,
    servable,
    unavailable,
)
from hydromodpy.solver.base.plan import RunContext, RunExecutionResult
from hydromodpy.solver.modflow_common.flow_adapter_helpers import (
    build_preprocess_options,
    nwt_safe_name,
    resolve_run_model_name,
    run_flow_model,
)
from hydromodpy.solver.modflow_common.observable_extraction import (
    extract_common_modflow_observables,
    resolve_run_output,
)
from hydromodpy.solver.modflow_nwt.nwt.nwt_solver import ModflowNwt

logger = get_logger(__name__)


class ModflowNwtFlowAdapter:
    """Bridge one planned ``flow/modflow_nwt`` run to the ``ModflowNwt`` API."""

    process_type = "flow"
    solver_name = "modflow_nwt"
    requires: tuple[tuple[str, str], ...] = ()
    accepted_meshes: ClassVar[frozenset[str]] = frozenset({"regular"})

    def validate(self, ctx: RunContext) -> None:
        """No precondition checks for MODFLOW-NWT flow runs."""

    def declared_observables(self, config: object) -> tuple[ObservableSupport, ...]:
        """Say what this run can serve, and what this backend never will.

        MODFLOW-NWT builds no LAK and no SFR package, so a lake stage and a routed
        reach discharge are not one declaration away: no configuration reaches
        them. Saying so here, rather than at the first extraction, is the point.
        """
        del config  # nothing here depends on it: the answer is the backend's
        return (
            servable("head", "read at any cell from the head file"),
            servable("discharge", "integrated over the domain from the budget file"),
            servable("release_flux", "per-cell surface release, from the budget file"),
            servable("water_budget_percent_discrepancy", "reported by the listing file"),
            unavailable(
                "stage",
                "MODFLOW-NWT builds no LAK package, so there is no lake state to read. "
                "Use the modflow6 backend for a lake.",
            ),
            unavailable(
                "routed_discharge",
                "MODFLOW-NWT builds no SFR package, so no reach outflow exists. The "
                "discharge at a cell is the upstream accumulation of the release flux.",
            ),
        )

    def locate_cell(self, ctx: RunContext, x: float, y: float) -> tuple[int, int, int] | None:
        """Return the nearest ``(0, row, col)`` on this run's structured grid.

        MODFLOW-NWT keeps its grid on the flopy model it built, so this is the
        one backend that reads ``mf.modelgrid``. Reading it here rather than in
        the layer that asks is the whole point: a caller that serves every solver
        must not know which one owns what. A point farther than one cell size,
        the square root of the cell area, from the cell of the nearest center
        gets ``None`` and a warning that names it, like on the other backends.
        """
        import numpy as np

        model = ctx.model
        if model is None:
            return None
        grid = getattr(getattr(model, "mf", None), "modelgrid", None)
        if grid is None:
            return None
        try:
            xc = np.asarray(getattr(grid, "xcellcenters", None), dtype=float)
            yc = np.asarray(getattr(grid, "ycellcenters", None), dtype=float)
        except (TypeError, ValueError):
            return None
        if xc.shape != yc.shape or xc.ndim != 2:
            return None
        flat = int(np.argmin((xc - x) ** 2 + (yc - y) ** 2))
        row, col = flat // xc.shape[1], flat % xc.shape[1]
        width = float(np.asarray(grid.delr, dtype=float).reshape(-1)[col])
        height = float(np.asarray(grid.delc, dtype=float).reshape(-1)[row])
        gap_x = max(abs(x - float(xc[row, col])) - 0.5 * width, 0.0)
        gap_y = max(abs(y - float(yc[row, col])) - 0.5 * height, 0.0)
        distance = float(np.hypot(gap_x, gap_y))
        size = float(np.sqrt(width * height))
        if distance > size:
            logger.warning(
                "Point (%.2f, %.2f) lies %.1f m outside the grid, farther than the size "
                "%.1f m of the nearest cell (%d, %d); it is not located on any cell.",
                x,
                y,
                distance,
                size,
                row,
                col,
            )
            return None
        return (0, row, col)

    def top_active_layer(self, ctx: RunContext, row: int, col: int) -> int | None:
        """Return the top active layer of the column at ``(row, col)``, from the run's idomain."""
        from hydromodpy.solver.base.cell_lookup import top_active_layer_on_solver_mesh

        return top_active_layer_on_solver_mesh(ctx, row, col)

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
        """Read observables from the scratch CBC and HDS files.

        Lightweight calibration trials never go through the ``store``: they
        read ``ctx.output_dir`` directly. ``store``
        is accepted for Protocol uniformity but unused here. MODFLOW-NWT has no
        lake package on this path, so anything the shared helper leaves unserved
        is refused by name.
        """
        del store
        if not requests:
            return {}
        output_dir, model, model_name = resolve_run_output(
            ctx, name_attributes=("model_name", "name")
        )
        served, unserved = extract_common_modflow_observables(
            output_dir,
            model_name,
            model,
            requests,
            time_index=time_index,
        )
        for request in unserved:
            raise ObservableNotAvailableError(
                f"MODFLOW-NWT does not produce observable {request.name!r} on support "
                f"{request.support!r}."
            )
        return served

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one MODFLOW-NWT flow run.

        The method is intentionally thin:

        - resolve the shared preprocessing options from the ``Model`` of the run,
        - derive the stable model folder name for this run,
        - build the concrete ``ModflowNwt`` object,
        - delegate the rest of the lifecycle, which hands the ``Model`` to
          ``ModflowNwt.pre_processing``, to ``run_flow_model``.
        """

        state = ctx.state
        preprocess_options = build_preprocess_options(state.setup.model)
        # MODFLOW-NWT truncates a NAME-file path at the first space, so collapse
        # whitespace before the name reaches the solver files (mirrors MF6).
        model_name = nwt_safe_name(resolve_run_model_name(ctx))
        # This is the only MODFLOW-NWT-specific part of the adapter: wiring
        # the correct config section into the concrete solver class.
        model_modflow = ModflowNwt(
            model_folder=state.setup.workspace.solver_scratch_folder,
            model_name=model_name,
            bin_path=state.setup.workspace.bin_path,
            modflow_config=state.cfg.modflownwt,
            preprocess_options=preprocess_options,
        )
        return run_flow_model(ctx, model_modflow, preprocess_options)
