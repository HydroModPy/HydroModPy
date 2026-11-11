"""Adapter for the ``flow/modflow_nwt`` solver pair.

This module contains only the MODFLOW-NWT-specific construction step. The
shared build and run lifecycle lives in
``hydromodpy.solver.modflow_common.flow_run``, and the files are
read back by ``extractors/flow.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

import pandas as pd
from pydantic import BaseModel

from hydromodpy.core.contracts.observables import ObservableRequest, ObservableResult
from hydromodpy.core.exceptions import ObservableNotAvailableError
from hydromodpy.core.logging import get_logger
from hydromodpy.results.field_registry import CONNECTION_CELLS, FACE_FLOW
from hydromodpy.results.storage.kept import Retention
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.base.observables import (
    ObservableSupport,
    servable,
    unavailable,
)
from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.solver.base.registry import backends_honoring, extractors
from hydromodpy.solver.modflow_common.flow_run import (
    build_flow_model,
    build_preprocess_options,
    nwt_safe_name,
    resolve_solver_run_output,
    run_flow_model,
)
from hydromodpy.solver.modflow_common.observable_extraction import (
    extract_common_modflow_observables,
)
from hydromodpy.solver.modflow_nwt.nwt.nwt_config import ModflowConfig
from hydromodpy.solver.modflow_nwt.nwt.nwt_solver import ModflowNwt

logger = get_logger(__name__)


class ModflowNwtFlowAdapter:
    """Bridge one planned ``flow/modflow_nwt`` run to the ``ModflowNwt`` API."""

    name: ClassVar[str] = "modflow_nwt"
    process_type: ClassVar[str] = "flow"
    accepted_meshes: ClassVar[frozenset[str]] = frozenset({"regular"})
    geometry: ClassVar[str] = "raster"
    writes: ClassVar[tuple[str, ...]] = (
        "head",
        CONNECTION_CELLS,
        FACE_FLOW,
        "budget/constant_head",
        "budget/drain",
        "budget/evapotranspiration",
        "budget/recharge",
        "budget/storage",
        "budget/well",
        "mesh/idomain",
        "mesh/layer_thickness",
        "mesh/topography",
        "budgets",
        "mass_balance",
    )
    reads: ClassVar[tuple[str, ...]] = ()
    supports: ClassVar[frozenset[str]] = frozenset(
        {
            "west_side",
            "east_side",
            "north_side",
            "south_side",
            "ocean",
            "drainage",
            "sink_fill",
            "drain_band_depth_m",
            "drain_bed_thickness_m",
            "drain_conductance_floor_m2_s",
            "head_rule",
            "steady_start",
            "recharge",
            "wells",
            "etp",
            "properties",
            "layers",
        }
    )
    options: ClassVar[type[BaseModel] | None] = ModflowConfig
    category: ClassVar[str] = "distributed"
    native_step: ClassVar[str | None] = None
    mutable: ClassVar[frozenset[str]] = frozenset()
    requires: ClassVar[tuple[tuple[str, str], ...]] = ()

    def validate(self, model: Any, options: BaseModel | None, slot: RunSlot) -> None:
        """No precondition checks for MODFLOW-NWT flow runs."""

    def build(
        self,
        model: Any,
        options: BaseModel | None,
        slot: RunSlot,
        upstream: tuple[SolverRun, ...] = (),
    ) -> SolverRun:
        """Build the MODFLOW-NWT model of ``model`` in memory, under ``slot``.

        A flow run follows no run of the plan, so ``upstream`` stays empty and
        the build reads nothing of it. The method is intentionally thin:

        - resolve the shared preprocessing options from the ``Model``,
        - build the concrete ``ModflowNwt`` object in the folder and under the
          name the slot gives, with the binary of the slot,
        - say on the solver object that a downstream transport may read the
          flow output: ``slot.hand_off`` carries ``face_flow`` when a run that
          follows the flow reads it, and the LMT package is then built with
          the run,
        - delegate the rest to ``build_flow_model``, which hands the ``Model``
          to ``ModflowNwt.pre_processing``.

        MODFLOW-NWT truncates a NAME-file path at the first space, so the name
        is made safe before it reaches the solver files (mirrors MF6).
        """
        del upstream  # a flow run follows no run of the plan
        preprocess_options = build_preprocess_options(model)
        solver_model = ModflowNwt(
            model_folder=slot.folder,
            model_name=nwt_safe_name(slot.name),
            bin_path=slot.bin_dir,
            modflow_config=options,
        )
        solver_model.link_mt3dms = FACE_FLOW in slot.hand_off
        return build_flow_model(solver_model, model, options, slot, preprocess_options)

    def run(self, solver_run: SolverRun) -> SolverRun:
        """Write the NWT input files, solve, and return the solved run.

        The wall time of the solve is ``solve_s``, set by the shared lifecycle.
        The solve runs the executable, which never reads the stop flag: a stop
        waits for it to end, and the runner of the plan reads the flag after.
        """
        return run_flow_model(solver_run, solver_name=self.name)

    def extract(self, solver_run: SolverRun, store: Any, retention: Retention) -> None:
        """Write the fields and tables of a solved run through its registered extractor."""
        extractors.create(self.process_type, self.name).extract(solver_run, store, retention)

    def declared_observables(self, active: frozenset[str]) -> tuple[ObservableSupport, ...]:
        """Say what this run can serve, and what this backend never will.

        MODFLOW-NWT builds no LAK and no SFR package, so a lake stage and a routed
        reach discharge are not one declaration away: no active condition reaches
        them. Saying so here, rather than at the first extraction, is the point.
        """
        del active  # nothing here depends on it: the answer is the backend's
        return (
            servable("head", "read at any cell from the head file"),
            servable("discharge", "integrated over the domain from the budget file"),
            servable("release_flux", "per-cell surface release, from the budget file"),
            servable("water_budget_percent_discrepancy", "reported by the listing file"),
            unavailable(
                "stage",
                "MODFLOW-NWT builds no LAK package, so there is no lake state to read. "
                "Backends that honor the lake boundary, this installation "
                f"serves: {', '.join(backends_honoring('lake')) or 'none'}.",
            ),
            unavailable(
                "routed_discharge",
                "MODFLOW-NWT builds no SFR package, so no reach outflow exists. The "
                "discharge at a cell is the upstream accumulation of the release flux.",
            ),
        )

    def locate_cell(self, solver_run: SolverRun, x: float, y: float) -> tuple[int, int, int] | None:
        """Return the nearest ``(0, row, col)`` on this run's structured grid.

        MODFLOW-NWT keeps its grid on the flopy model it built, so this is the
        one backend that reads ``mf.modelgrid``. Reading it here rather than in
        the layer that asks is the whole point: a caller that serves every solver
        must not know which one owns what. A point farther than one cell size,
        the square root of the cell area, from the cell of the nearest center
        gets ``None`` and a warning that names it, like on the other backends.
        """
        import numpy as np

        solver_model = solver_run.solver_model
        if solver_model is None:
            return None
        grid = getattr(getattr(solver_model, "mf", None), "modelgrid", None)
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

    def top_active_layer(self, solver_run: SolverRun, row: int, col: int) -> int | None:
        """Return the top active layer of the column at ``(row, col)``, from the run's idomain."""
        from hydromodpy.solver.base.cell_lookup import top_active_layer_on_solver_mesh

        return top_active_layer_on_solver_mesh(solver_run, row, col)

    def cleanup(self, solver_run: SolverRun) -> None:
        """Remove the scratch directory written by this run, if any."""
        if solver_run.output_dir is not None:
            cleanup_solver_files(solver_run.output_dir)

    def observables(
        self,
        solver_run: SolverRun,
        requests: Sequence[ObservableRequest],
        *,
        time_index: pd.DatetimeIndex | None = None,
    ) -> dict[str, ObservableResult]:
        """Read observables from the scratch CBC and HDS files.

        A lightweight calibration trial never goes through a store: it reads
        ``solver_run.output_dir`` directly. MODFLOW-NWT has no lake package on
        this path, so anything the shared helper leaves unserved is refused by
        name.
        """
        if not requests:
            return {}
        output_dir, solver_model, model_name = resolve_solver_run_output(
            solver_run, name_attributes=("model_name", "name")
        )
        served, unserved = extract_common_modflow_observables(
            output_dir,
            model_name,
            solver_model,
            requests,
            time_index=time_index,
        )
        for request in unserved:
            raise ObservableNotAvailableError(
                f"MODFLOW-NWT does not produce observable {request.name!r} on support "
                f"{request.support!r}."
            )
        return served
