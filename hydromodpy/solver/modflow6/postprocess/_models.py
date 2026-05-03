"""Protocol contracts consumed by MODFLOW-6 post-processing helpers."""

from __future__ import annotations

from typing import Protocol

import numpy as np

from hydromodpy.solver.modflow6.diagnostics import RuntimeSupportOverviewModel
from hydromodpy.solver.modflow_common.options import ModflowPostprocessOptions

NODATA = -9999


class BudgetReaderLike(Protocol):
    """Minimal MF6 budget-reader contract consumed by helper functions."""

    def get_data(self, *, kstpkper: tuple[int, int], text: str): ...


class SolverMeshLike(Protocol):
    """Minimal solver-mesh contract consumed by MF6 post-processing helpers."""

    is_structured: bool
    top: np.ndarray
    planar_mesh: object
    n_cells: int

    def reshape_to_grid(self, flat_array: np.ndarray) -> np.ndarray: ...

    def flatten_from_grid(self, values: np.ndarray) -> np.ndarray: ...

    def cell_centroids(self) -> object: ...


class RoutingContextLike(Protocol):
    """Minimal routing-context contract for raster accumulation exports."""

    correc_path: str
    direc_path: str


class FlowPostprocessModel(RuntimeSupportOverviewModel, Protocol):
    """Minimal MODFLOW-6 contract consumed by flow post-processing exports."""

    full_path: str
    model_name: str
    save_file: str
    tifs_file: str
    times: list[float] | tuple[float, ...]
    ncpl: int
    nper: int
    nrow: int
    ncol: int
    dem: np.ndarray
    dem_mask: np.ndarray
    dem_watershed_path: str
    geographic: object
    solver_mesh: SolverMeshLike

    def _to_export_array(self, flat_array: np.ndarray) -> np.ndarray: ...

    def _ensure_solver_routing_context(self) -> RoutingContextLike: ...


class TransportPostprocessModel(Protocol):
    """Minimal MODFLOW transport contract consumed by GWT post-processing."""

    full_path: str
    model_name_mt: str
    save_file: str
    tifs_file: str
    model_modflow: FlowPostprocessModel

    def _resolve_postprocess_options(
        self,
        *,
        export_all_tif: bool,
        options: ModflowPostprocessOptions | None,
    ) -> ModflowPostprocessOptions: ...
