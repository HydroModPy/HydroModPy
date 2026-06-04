"""MODFLOW 6 flow solver facade aligned with HydroModPy workflow APIs.

This module exposes the :class:`Modflow6` adapter. Concern-specific helpers
live in ``build`` (pre_processing), ``run`` (processing), ``postprocess``
(water table, budget, native exports) and ``render`` (matplotlib overlays).
The class methods are thin delegators so this module stays under the 1500 LOC
architectural limit.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

import numpy as np

from hydromodpy.core.io.filesystem import create_folder
from hydromodpy.solver.base.protocols import DomainLike
from hydromodpy.solver.modflow6.build import (
    apply_preprocess_options,
    log_xt3d_resolution,
    mf6_safe_name,
    resolve_flow_regime,
    resolve_ims_complexity_for,
    resolve_xt3d_options,
    run_pre_processing,
    select_active_dem,
    write_solver_grid_template,
    xt3d_is_enabled,
    xt3d_mode,
    xt3d_requested,
)
from hydromodpy.solver.modflow6.modflow6_config import (
    Modflow6Config,
    _coerce_modflow6_config,
)
from hydromodpy.solver.modflow6.postprocess import run_flow_post_processing
from hydromodpy.solver.modflow6.render import (
    export_runtime_support_overview,
    support_cell_polygons,
    support_edge_segments,
    support_overlay_specs,
    well_overlay_specs,
)
from hydromodpy.solver.modflow6.run import run_processing
from hydromodpy.solver.modflow_common import (
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
    SolverRoutingContext,
    ensure_platform_executable,
    ensure_solver_binary,
)
from hydromodpy.solver.modflow_grid import SolverGridContext


class Modflow6:
    """Flow solver based on MODFLOW 6 (GWF)."""

    def __init__(
        self,
        geographic: object,
        modflow_config: Modflow6Config | Mapping[str, object] | None = None,
        model_folder: str = "HydroModPy_outputs",
        model_name: str = "Default",
        bin_path: str | None = None,
        preprocess_options: ModflowPreprocessOptions | None = None,
    ):
        self.model_folder = model_folder
        if not os.path.exists(self.model_folder):
            create_folder(self.model_folder)

        self.model_name = model_name
        self.model_name_mf6 = mf6_safe_name(model_name)
        self.model_output_name = model_name
        self.geographic = geographic
        self.flow = None
        self.domain = None
        self.flow_regime: str | None = None
        self.last_flow_solve_time_seconds: float | None = None
        self.prob_cells = 0

        self.full_path = os.path.join(model_folder, model_name)
        self.dem_watershed_path = None
        self.grid_ctx: SolverGridContext | None = None
        self.routing_ctx: SolverRoutingContext | None = None

        self.modflow_config = _coerce_modflow6_config(modflow_config)
        runtime = self.modflow_config.runtime
        exe_name = getattr(runtime, "mf6_executable_name", None) or getattr(
            runtime, "executable_name", None
        )
        if exe_name and os.path.isabs(exe_name):
            self.exe = str(ensure_platform_executable(exe_name))
        elif not exe_name or exe_name in ("mf6", "mf6.exe"):
            self.exe = str(ensure_solver_binary("mf6", bin_path))
        else:
            self.exe = str(ensure_platform_executable(os.path.join(bin_path, exe_name)))

        self.resolution = geographic.dem_res
        self.xul = geographic.xmin
        self.yul = geographic.ymax
        self.sink = getattr(geographic, "depressions_data", None)

        self.preprocess_options = preprocess_options or ModflowPreprocessOptions()
        self._apply_preprocess_options(self.preprocess_options)
        self._evt_rate_payload: dict[int, object] | None = None
        self._pending_negative_to_evt = False
        self._heterogeneous_recharge_source = None
        self._heterogeneous_negative_to_evt = False
        self._heterogeneous_interpolation_method = "nearest"

    # build helpers ------------------------------------------------------

    def _select_active_dem(self, box: bool) -> None:
        select_active_dem(self, box)

    def _apply_preprocess_options(self, options: ModflowPreprocessOptions | None = None) -> None:
        apply_preprocess_options(self, options)

    def _xt3d_requested_value(self) -> bool | None:
        return xt3d_requested(self)

    def _xt3d_is_enabled(self, solver_mesh=None) -> bool:
        return xt3d_is_enabled(self, solver_mesh)

    def _xt3d_activation_mode(self, solver_mesh=None) -> str:
        return xt3d_mode(self, solver_mesh)

    def _resolve_xt3d_npf_options(self, solver_mesh=None) -> list[str] | None:
        return resolve_xt3d_options(self, solver_mesh)

    def _resolve_ims_complexity(self, solver_mesh=None) -> str:
        return resolve_ims_complexity_for(self, solver_mesh)

    def _log_xt3d_resolution(self, solver_mesh=None) -> None:
        log_xt3d_resolution(self, solver_mesh)

    def _to_export_array(self, flat_array: np.ndarray) -> np.ndarray:
        """Reshape flat (ncpl,) to (nrow, ncol) for raster export (structured only)."""
        return self.solver_mesh.reshape_to_grid(flat_array)

    def _write_solver_grid_template(self) -> str:
        return write_solver_grid_template(self)

    def _ensure_solver_routing_context(self) -> SolverRoutingContext:
        from hydromodpy.solver.modflow6.build import ensure_solver_routing_context

        return ensure_solver_routing_context(self)

    def _resolve_flow_regime(self) -> str | None:
        return resolve_flow_regime(self)

    def _validate_pre_processing_inputs(self) -> None:
        from hydromodpy.solver.modflow6.build import validate_pre_processing_inputs

        validate_pre_processing_inputs(self)

    def pre_processing(
        self,
        flow: object,
        domain: DomainLike,
        options: ModflowPreprocessOptions | None = None,
        *,
        mesh_planar: object | None = None,
        mesh_support: object | None = None,
        flow_runtime_overrides: Mapping[str, object] | None = None,
    ):
        run_pre_processing(
            self,
            flow,
            domain,
            options,
            mesh_planar=mesh_planar,
            mesh_support=mesh_support,
            flow_runtime_overrides=flow_runtime_overrides,
        )

    # run --------------------------------------------------------------

    def processing(self, options: ModflowRunOptions | None = None):
        return run_processing(self, options)

    # render -----------------------------------------------------------

    def _support_edge_segments(self, support: object, edge_indices: np.ndarray) -> list[np.ndarray]:
        return support_edge_segments(self, support, edge_indices)

    def _support_cell_polygons(self, support: object, cell_ids: np.ndarray) -> list[np.ndarray]:
        return support_cell_polygons(self, support, cell_ids)

    def _support_overlay_specs(self) -> list[tuple[str, np.ndarray, str]]:
        return support_overlay_specs(self)

    def _well_overlay_specs(self) -> list[dict[str, object]]:
        return well_overlay_specs(self)

    def _export_runtime_support_overview(self, *, options: ModflowPostprocessOptions) -> None:
        export_runtime_support_overview(self, options=options)

    # post_processing --------------------------------------------------

    def post_processing(self, options: ModflowPostprocessOptions | None = None):
        """Run MODFLOW 6 flow post-processing."""
        run_flow_post_processing(self, options=options)
