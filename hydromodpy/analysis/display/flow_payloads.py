"""Solver-agnostic payload builders for common flow figures.

This module isolates the translation from solver/runtime outputs to a small
set of generic payloads consumed by the display layer. The goal is to keep
figure code independent from specific solver classes whenever possible.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
import warnings

import numpy as np
import pandas as pd

from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh

if TYPE_CHECKING:
    from hydromodpy.analysis.display.posthoc import RunArtifacts


_NODATA_THRESHOLD = -9_999.0
_SECONDS_PER_DAY = 86_400.0


@dataclass(frozen=True, init=False)
class FlowSpatialFigurePayload:
    """Generic cell-centered state payload for 2D flow figures.

    ``artifact_id`` is the canonical display identifier. ``run_id`` remains a
    deprecated compatibility alias for callers that still use the historical
    vocabulary.
    """

    artifact_id: str
    hydro_mesh: HydroMesh
    top_elevation_m: np.ndarray | None = None
    watertable_elevation_m: np.ndarray | None = None
    watertable_depth_m: np.ndarray | None = None
    seepage_areas_m_per_day: np.ndarray | None = None
    outflow_drain_m_per_day: np.ndarray | None = None
    accumulation_flux_m_per_day: np.ndarray | None = None

    @property
    def run_id(self) -> str:
        """Deprecated compatibility alias for :attr:`artifact_id`."""
        warnings.warn(
            "'FlowSpatialFigurePayload.run_id' is deprecated. "
            "Use 'artifact_id' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.artifact_id

    def __init__(
        self,
        artifact_id: str | None = None,
        hydro_mesh: HydroMesh | None = None,
        top_elevation_m: np.ndarray | None = None,
        watertable_elevation_m: np.ndarray | None = None,
        watertable_depth_m: np.ndarray | None = None,
        seepage_areas_m_per_day: np.ndarray | None = None,
        outflow_drain_m_per_day: np.ndarray | None = None,
        accumulation_flux_m_per_day: np.ndarray | None = None,
        *,
        run_id: str | None = None,
    ) -> None:
        resolved_artifact_id = _resolve_deprecated_run_id_alias(
            artifact_id=artifact_id,
            run_id=run_id,
            target_name="FlowSpatialFigurePayload",
        )
        object.__setattr__(self, "artifact_id", resolved_artifact_id)
        object.__setattr__(self, "hydro_mesh", hydro_mesh)
        object.__setattr__(self, "top_elevation_m", top_elevation_m)
        object.__setattr__(self, "watertable_elevation_m", watertable_elevation_m)
        object.__setattr__(self, "watertable_depth_m", watertable_depth_m)
        object.__setattr__(self, "seepage_areas_m_per_day", seepage_areas_m_per_day)
        object.__setattr__(self, "outflow_drain_m_per_day", outflow_drain_m_per_day)
        object.__setattr__(self, "accumulation_flux_m_per_day", accumulation_flux_m_per_day)


@dataclass(frozen=True, init=False)
class FlowCumulativeSeriesPayload:
    """Generic cumulative recharge/discharge payload for 1D figures.

    ``artifact_id`` is the canonical display identifier. ``run_id`` remains a
    deprecated compatibility alias for callers that still use the historical
    vocabulary.
    """

    artifact_id: str
    time_days: np.ndarray
    recharge_cumulative_mm: np.ndarray | None = None
    discharge_components_cumulative_mm: dict[str, np.ndarray] | None = None
    discharge_total_cumulative_mm: np.ndarray | None = None

    @property
    def run_id(self) -> str:
        """Deprecated compatibility alias for :attr:`artifact_id`."""
        warnings.warn(
            "'FlowCumulativeSeriesPayload.run_id' is deprecated. "
            "Use 'artifact_id' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.artifact_id

    def __init__(
        self,
        artifact_id: str | None = None,
        time_days: np.ndarray | None = None,
        recharge_cumulative_mm: np.ndarray | None = None,
        discharge_components_cumulative_mm: dict[str, np.ndarray] | None = None,
        discharge_total_cumulative_mm: np.ndarray | None = None,
        *,
        run_id: str | None = None,
    ) -> None:
        resolved_artifact_id = _resolve_deprecated_run_id_alias(
            artifact_id=artifact_id,
            run_id=run_id,
            target_name="FlowCumulativeSeriesPayload",
        )
        object.__setattr__(self, "artifact_id", resolved_artifact_id)
        object.__setattr__(self, "time_days", time_days)
        object.__setattr__(self, "recharge_cumulative_mm", recharge_cumulative_mm)
        object.__setattr__(
            self,
            "discharge_components_cumulative_mm",
            discharge_components_cumulative_mm,
        )
        object.__setattr__(self, "discharge_total_cumulative_mm", discharge_total_cumulative_mm)


def _resolve_deprecated_run_id_alias(
    *,
    artifact_id: str | None,
    run_id: str | None,
    target_name: str,
) -> str:
    """Resolve one canonical artifact identifier from modern and legacy names."""
    normalized_artifact_id = str(artifact_id or "").strip()
    normalized_run_id = str(run_id or "").strip()
    if normalized_artifact_id and normalized_run_id and normalized_artifact_id != normalized_run_id:
        raise ValueError(
            f"{target_name} received both artifact_id={normalized_artifact_id!r} "
            f"and run_id={normalized_run_id!r}; use only one identifier."
        )
    if normalized_artifact_id:
        return normalized_artifact_id
    if normalized_run_id:
        warnings.warn(
            f"'{target_name}(run_id=...)' is deprecated. Use 'artifact_id=' instead.",
            DeprecationWarning,
            stacklevel=3,
        )
        return normalized_run_id
    raise TypeError(f"{target_name} requires 'artifact_id' (or deprecated 'run_id').")


def resolve_flow_artifact_id(model) -> str:
    """Resolve the display/artifact identifier from one live flow model."""
    return (
        str(getattr(model, "model_name", "")).strip()
        or str(getattr(model, "model_name_mf6", "")).strip()
        or "flow"
    )


def _sanitize_cell_values(values: np.ndarray | None) -> np.ndarray | None:
    """Normalize one cell-centered array and mask HydroModPy nodata values."""
    if values is None:
        return None
    array = np.asarray(values, dtype=float).reshape(-1).copy()
    if array.size == 0:
        return None
    array[~np.isfinite(array)] = np.nan
    array[array <= _NODATA_THRESHOLD] = np.nan
    return array


def _load_npy_dict(path: Path) -> dict[int, np.ndarray] | None:
    """Load one dict-of-arrays NPY payload when it exists."""
    if not path.exists():
        return None
    return np.load(path, allow_pickle=True).item()


def _latest_dict_values(path: Path) -> np.ndarray | None:
    """Return the latest time slice from one dict-of-arrays NPY payload."""
    data_by_time = _load_npy_dict(path)
    if not data_by_time:
        return None
    latest_key = max(data_by_time.keys(), key=int)
    return np.asarray(data_by_time[latest_key], dtype=float)


def _flatten_solver_output(solver_mesh, values: np.ndarray | None) -> np.ndarray | None:
    """Flatten one solver output to `(ncpl,)` using the solver mesh contract."""
    if values is None:
        return None
    return _sanitize_cell_values(solver_mesh.flatten_from_grid(np.asarray(values)))


def _build_hydromesh_from_mesh_like(mesh_like) -> HydroMesh | None:
    """Convert one light mesh-like object to the generic HydroMesh pivot."""
    if mesh_like is None:
        return None
    if isinstance(mesh_like, HydroMesh):
        return mesh_like

    planar_mesh = getattr(mesh_like, "planar_mesh", None)
    if isinstance(planar_mesh, HydroMesh):
        return planar_mesh

    node_x = getattr(mesh_like, "node_x_m", None)
    node_y = getattr(mesh_like, "node_y_m", None)
    cell_node_ids = getattr(mesh_like, "cell_node_ids", None)
    if node_x is None or node_y is None or cell_node_ids is None:
        return None

    connectivity = np.asarray(cell_node_ids, dtype=int)
    if connectivity.ndim != 2 or connectivity.shape[0] == 0:
        return None

    nodes_per_cell = int(connectivity.shape[1])
    if nodes_per_cell == 3:
        cell_type = CellType.TRIANGLE
    elif nodes_per_cell == 4:
        cell_type = CellType.QUADRILATERAL
    else:
        return None

    vertices = np.column_stack(
        [
            np.asarray(node_x, dtype=float).reshape(-1),
            np.asarray(node_y, dtype=float).reshape(-1),
        ]
    )
    return HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(cell_type=cell_type, connectivity=connectivity),),
    )


def build_flow_spatial_payload_from_model(model) -> FlowSpatialFigurePayload | None:
    """Build the generic flow-state payload from a live runtime model."""
    if model is None:
        return None

    artifact_id = resolve_flow_artifact_id(model)

    solver_mesh = getattr(model, "solver_mesh", None)
    if solver_mesh is not None:
        hydro_mesh = getattr(solver_mesh, "planar_mesh", None)
        if hydro_mesh is None:
            return None
        full_path = getattr(model, "full_path", None)
        postprocess_dir = (
            Path(full_path).resolve() / "_postprocess"
            if full_path is not None
            else Path(".").resolve() / "_postprocess"
        )
        return FlowSpatialFigurePayload(
            artifact_id=artifact_id,
            hydro_mesh=hydro_mesh,
            top_elevation_m=_sanitize_cell_values(np.asarray(solver_mesh.top, dtype=float)),
            watertable_elevation_m=_flatten_solver_output(
                solver_mesh,
                _latest_dict_values(postprocess_dir / "watertable_elevation.npy"),
            ),
            watertable_depth_m=_flatten_solver_output(
                solver_mesh,
                _latest_dict_values(postprocess_dir / "watertable_depth.npy"),
            ),
            seepage_areas_m_per_day=_flatten_solver_output(
                solver_mesh,
                _latest_dict_values(postprocess_dir / "seepage_areas.npy"),
            ),
            outflow_drain_m_per_day=_flatten_solver_output(
                solver_mesh,
                _latest_dict_values(postprocess_dir / "outflow_drain.npy"),
            ),
            accumulation_flux_m_per_day=_flatten_solver_output(
                solver_mesh,
                _latest_dict_values(postprocess_dir / "accumulation_flux.npy"),
            ),
        )

    mesh = getattr(model, "mesh", None)
    hydro_mesh = _build_hydromesh_from_mesh_like(mesh)
    if hydro_mesh is None:
        return None

    state = getattr(model, "state", None)
    head = None if state is None else _sanitize_cell_values(getattr(state, "head_m", None))
    top = _sanitize_cell_values(getattr(mesh, "z_top_m", None))
    if head is None and top is None:
        return None

    wt_depth = None
    if top is not None and head is not None and top.size == head.size:
        wt_depth = np.asarray(top - head, dtype=float)

    return FlowSpatialFigurePayload(
        artifact_id=artifact_id,
        hydro_mesh=hydro_mesh,
        top_elevation_m=top,
        watertable_elevation_m=head,
        watertable_depth_m=wt_depth,
    )


def discover_latest_native_mesh_vtu(run: "RunArtifacts", *, prefix: str = "flow") -> Path | None:
    """Return the latest solver-native VTU export for one run when present."""
    mesh_dir = run.postprocess_dir / "_mesh"
    if not mesh_dir.is_dir():
        return None
    candidates = sorted(mesh_dir.glob(f"{prefix}_t(*).vtu"))
    if not candidates:
        return None
    return candidates[-1]


def build_flow_spatial_payload_from_run(run: "RunArtifacts") -> FlowSpatialFigurePayload | None:
    """Build the generic flow-state payload from post-hoc disk outputs."""
    vtu_path = discover_latest_native_mesh_vtu(run, prefix="flow")
    if vtu_path is None:
        return None

    try:
        from hydromodpy.spatial.mesh.io import read_vtu
    except Exception:
        return None

    try:
        hydro_mesh = read_vtu(vtu_path)
    except Exception:
        return None
    cell_data = getattr(hydro_mesh, "cell_data", {})
    return FlowSpatialFigurePayload(
        artifact_id=run.artifact_id,
        hydro_mesh=hydro_mesh,
        top_elevation_m=_sanitize_cell_values(cell_data.get("top_elevation")),
        watertable_elevation_m=_sanitize_cell_values(cell_data.get("watertable_elevation")),
        watertable_depth_m=_sanitize_cell_values(cell_data.get("watertable_depth")),
        seepage_areas_m_per_day=_sanitize_cell_values(cell_data.get("seepage_areas")),
        outflow_drain_m_per_day=_sanitize_cell_values(cell_data.get("outflow_drain")),
        accumulation_flux_m_per_day=_sanitize_cell_values(cell_data.get("accumulation_flux")),
    )


def _resolve_time_axis_days(index: pd.Index) -> tuple[np.ndarray, np.ndarray]:
    """Resolve elapsed-time and step-length arrays in days from one index."""
    if isinstance(index, pd.DatetimeIndex):
        time_days = (
            (index - index[0]).total_seconds() / 86_400.0
        ).to_numpy(dtype=float)
    else:
        try:
            time_days = index.to_numpy(dtype=float)
        except Exception:
            time_days = np.arange(len(index), dtype=float)
    time_days = np.asarray(time_days, dtype=float).reshape(-1)
    if time_days.size == 0:
        return time_days, time_days

    step_days = np.diff(time_days, prepend=np.nan)
    positive = step_days[np.isfinite(step_days) & (step_days > 0.0)]
    default_step = float(positive[0]) if positive.size else 1.0
    step_days[0] = default_step
    step_days[~np.isfinite(step_days) | (step_days <= 0.0)] = default_step
    return time_days, step_days


def _rate_m_per_s_to_cumulative_mm(
    values_m_per_s: np.ndarray,
    step_days: np.ndarray,
) -> np.ndarray:
    """Convert one SI flux-rate series to cumulative water depth in millimeters."""
    clean_values = np.nan_to_num(
        np.asarray(values_m_per_s, dtype=float),
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )
    return np.cumsum(clean_values * step_days * _SECONDS_PER_DAY * 1_000.0)


def _has_at_least_one_finite_value(values: np.ndarray) -> bool:
    """Return True when one time-series component carries usable data."""
    return bool(np.any(np.isfinite(np.asarray(values, dtype=float))))


def build_flow_cumulative_payload(
    simulated_timeseries: pd.DataFrame | None,
    *,
    artifact_id: str | None = None,
    run_id: str | None = None,
) -> FlowCumulativeSeriesPayload | None:
    """Build cumulative recharge/discharge curves from the common timeseries CSV.

    Flow time-series rates are kept in SI units (m/s) by the solvers and
    postprocessing layer. The conversion to millimeters is intentionally local
    to the display payload.
    """
    if simulated_timeseries is None or simulated_timeseries.empty:
        return None

    resolved_artifact_id = _resolve_deprecated_run_id_alias(
        artifact_id=artifact_id,
        run_id=run_id,
        target_name="build_flow_cumulative_payload",
    )

    time_days, step_days = _resolve_time_axis_days(simulated_timeseries.index)
    if time_days.size == 0:
        return None

    recharge_cumulative_mm = None
    if "recharge_budget" in simulated_timeseries.columns:
        recharge = np.asarray(simulated_timeseries["recharge_budget"], dtype=float).reshape(-1)
        if _has_at_least_one_finite_value(recharge):
            recharge_cumulative_mm = _rate_m_per_s_to_cumulative_mm(recharge, step_days)

    discharge_components: dict[str, np.ndarray] = {}
    component_mapping = {
        "outflow_drain": "Drain discharge",
        "runoff": "Runoff",
    }
    for column, label in component_mapping.items():
        if column not in simulated_timeseries.columns:
            continue
        values = np.asarray(simulated_timeseries[column], dtype=float).reshape(-1)
        if not _has_at_least_one_finite_value(values):
            continue
        discharge_components[label] = _rate_m_per_s_to_cumulative_mm(values, step_days)

    discharge_total = None
    if discharge_components:
        discharge_total = np.sum(
            np.vstack(list(discharge_components.values())),
            axis=0,
            dtype=float,
        )

    if recharge_cumulative_mm is None and discharge_total is None:
        return None

    return FlowCumulativeSeriesPayload(
        artifact_id=resolved_artifact_id,
        time_days=time_days,
        recharge_cumulative_mm=recharge_cumulative_mm,
        discharge_components_cumulative_mm=(
            discharge_components if discharge_components else None
        ),
        discharge_total_cumulative_mm=discharge_total,
    )


__all__ = [
    "FlowCumulativeSeriesPayload",
    "FlowSpatialFigurePayload",
    "build_flow_cumulative_payload",
    "build_flow_spatial_payload_from_model",
    "build_flow_spatial_payload_from_run",
    "discover_latest_native_mesh_vtu",
    "resolve_flow_artifact_id",
]
