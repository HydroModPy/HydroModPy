"""Public API for MODFLOW 6 flow and transport post-processing.

The flow/transport orchestrators (``run_flow_post_processing``,
``run_transport_post_processing``) and their monkeypatchable module globals
(``bf``, ``pp``, ``raster_io``, ``masstransfer``, ``rasterio``) live in
:mod:`hydromodpy.solver.modflow6.postprocess.pipeline`; unit tests patch them
through the dotted path ``...postprocess.pipeline.<name>``.
"""

from ._budget import (
    compute_chd_outlet_discharge_east_side_m3_s,
    compute_drain_outflow_and_seepage,
    east_side_cell_ids,
    get_budget_records_or_none,
    open_budget_file,
)
from ._models import (
    NODATA,
    BudgetReaderLike,
    FlowPostprocessModel,
    RoutingContextLike,
    SolverMeshLike,
    TransportPostprocessModel,
)
from ._native_mesh import (
    export_native_mesh_outputs,
    native_cell_series_payload,
    native_mesh_exports_enabled,
)
from ._unstructured import (
    accumulate_unstructured_cell_values,
    build_unstructured_cell_adjacency,
)
from ._watertable import compute_watertable_depth, compute_watertable_elevation
from .pipeline import run_flow_post_processing, run_transport_post_processing

__all__ = [
    "BudgetReaderLike",
    "FlowPostprocessModel",
    "RoutingContextLike",
    "SolverMeshLike",
    "TransportPostprocessModel",
    "NODATA",
    "accumulate_unstructured_cell_values",
    "build_unstructured_cell_adjacency",
    "compute_chd_outlet_discharge_east_side_m3_s",
    "compute_drain_outflow_and_seepage",
    "compute_watertable_depth",
    "compute_watertable_elevation",
    "east_side_cell_ids",
    "export_native_mesh_outputs",
    "get_budget_records_or_none",
    "native_cell_series_payload",
    "native_mesh_exports_enabled",
    "open_budget_file",
    "run_flow_post_processing",
    "run_transport_post_processing",
]
