"""MF6 initial-condition and rewet builders."""

from __future__ import annotations

import numpy as np

from hydromodpy.core.nodata import SENTINEL_ABS_THRESHOLD
from hydromodpy.solver.initial_conditions import (
    build_head_initial_condition_array,
    initial_condition_field,
    resolve_head_initial_condition,
)
from hydromodpy.solver.modflow6.builders.boundary_conditions import (
    apply_side_boundary_start_heads,
    ocean_chd_support_mask,
    resolve_ocean_boundary_series,
    resolve_stream_boundary_series,
    stream_chd_support_mask,
)


def rewet_is_enabled(model) -> bool:
    """Return whether MF6 rewetting is enabled for the current run."""
    runtime = getattr(model.modflow_config, "runtime", None)
    enable_rewet = getattr(runtime, "mf6_enable_rewet", None)
    return bool(enable_rewet) if enable_rewet is not None else False


def resolve_restart_from(model) -> str | None:
    """Resolve the ``[flow] restart_from`` hotstart source path, or None."""
    flow = getattr(model, "flow", None)
    config = getattr(flow, "config", None) if flow is not None else None
    value = getattr(config, "restart_from", None)
    if value is None and flow is not None:
        value = getattr(flow, "restart_from", None)
    text = str(value).strip() if value else ""
    return text or None


def _open_restart_zarr(path: str):
    import zarr

    if path.endswith(".zip"):
        return zarr.open(zarr.storage.ZipStore(path, mode="r"), mode="r")
    return zarr.open(path, mode="r")


def read_restart_heads(path: str, *, nlay: int, ncpl: int, top_flat: np.ndarray) -> np.ndarray:
    """Return start heads ``(nlay, ncpl)`` from a prior run's last time step (hotstart).

    The prior run must share this run's mesh (same cell count), which is what the
    mesh cache guarantees; a shape mismatch raises rather than silently reindexing.
    """
    root = _open_restart_zarr(path)
    if "head" not in root:
        raise ValueError(f"restart_from: no 'head' field in {path!r}")
    head = np.asarray(root["head"][-1], dtype=float)
    head = head.reshape(head.shape[0], -1) if head.ndim > 1 else head.reshape(1, -1)
    if head.shape != (nlay, ncpl):
        raise ValueError(
            f"restart_from: prior head shape {head.shape} does not match this run "
            f"({nlay}, {ncpl}). Enable [mesh_catchment] cache = true so the mesh, and the "
            f"cell count, is identical between the two runs."
        )
    # Inactive cells carry a NaN / large sentinel; MF6 ignores strt there but the array must
    # be finite, so fill them with the cell top like the default initial condition.
    head = np.where(np.abs(head) > SENTINEL_ABS_THRESHOLD, np.nan, head)
    top = np.asarray(top_flat, dtype=float).reshape(-1)
    for ilay in range(nlay):
        missing = ~np.isfinite(head[ilay])
        head[ilay][missing] = top[missing]
    return head


def read_restart_lake_stages(path: str) -> dict[str, float]:
    """Return each lake's final stage ``{lake_id: stage}`` from a prior run's Zarr.

    Reads the ``lake_state_final`` group written at extraction time, the lake
    companion of the ``head`` field for ``[flow] restart_from``. Returns an empty
    mapping when the prior run had no lake (older stores, non-lake runs), so
    callers keep the per-lake ``stageinit``.
    """
    root = _open_restart_zarr(path)
    if "lake_state_final" not in root:
        return {}
    group = root["lake_state_final"]
    if "stage" not in group:
        return {}
    stages = np.asarray(group["stage"][:], dtype=float).reshape(-1)
    lake_ids = [str(lake_id) for lake_id in group.attrs.get("lake_ids", [])]
    if len(lake_ids) != len(stages):
        return {}
    return {lake_id: float(value) for lake_id, value in zip(lake_ids, stages, strict=True)}


def read_final_head(path: str) -> np.ndarray:
    """Return a prior run's last-step head field ``(nlay, ncpl)`` for convergence.

    Inactive cells (NaN / large sentinel) come back as NaN so a cycle-to-cycle
    diff can ignore them. Unlike :func:`read_restart_heads` this does not fill
    them with the cell top; it is a read-only companion for the spin-up loop.
    """
    root = _open_restart_zarr(path)
    if "head" not in root:
        raise ValueError(f"read_final_head: no 'head' field in {path!r}")
    head = np.asarray(root["head"][-1], dtype=float)
    head = head.reshape(head.shape[0], -1) if head.ndim > 1 else head.reshape(1, -1)
    return np.where(np.abs(head) > SENTINEL_ABS_THRESHOLD, np.nan, head)


def build_start_heads(model, solver_mesh) -> np.ndarray:
    """Build MF6 starting heads as flat (nlay, ncpl) for DISV."""
    ncpl = solver_mesh.n_cells
    top_flat = solver_mesh.top  # (ncpl,)
    botm_flat = solver_mesh.botm  # (nlay, ncpl)

    restart_source = resolve_restart_from(model)
    if restart_source:
        strt = read_restart_heads(
            restart_source, nlay=int(model.nlay), ncpl=int(ncpl), top_flat=top_flat
        )
    else:
        h_ic = resolve_head_initial_condition(model)
        if h_ic is None:
            raise ValueError("flow.initial_conditions.h is required for Modflow6 pre_processing")
        strt = build_head_initial_condition_array(
            h_ic,
            top=top_flat,
            bottom=botm_flat[-1],
            target_shape=(int(model.nlay), int(ncpl)),
            location_prefix="flow.ic",
        )
    ocean_series = resolve_ocean_boundary_series(model)
    ocean_mask = ocean_chd_support_mask(model, ocean_series)
    if np.any(ocean_mask):
        for ilay in range(int(model.nlay)):
            strt[ilay][ocean_mask] = float(ocean_series[0])
    stream_series = resolve_stream_boundary_series(model)
    stream_mask = stream_chd_support_mask(model, stream_series)
    if np.any(stream_mask):
        for ilay in range(int(model.nlay)):
            strt[ilay][stream_mask] = float(stream_series[0])
    return apply_side_boundary_start_heads(model, strt)


def resolve_rewet_npf_options(
    model,
    solver_mesh,
) -> tuple[list[object] | None, np.ndarray | None]:
    """Return MF6 NPF rewet options and the matching WETDRY array."""
    runtime = getattr(model.modflow_config, "runtime", None)
    if not rewet_is_enabled(model):
        return None, None

    wetdry_value = abs(float(runtime.mf6_rewet_wetdry))
    if wetdry_value <= 0.0:
        raise ValueError("modflow6.runtime.mf6_rewet_wetdry must be > 0 when rewetting is enabled.")

    # FloPy injects the REWET keyword itself and expects only the labeled payload.
    # rewet_is_enabled() above guarantees runtime is set, so read the fields directly
    # (their defaults live on the Pydantic runtime config, not here).
    rewet_record = [
        "WETFCT",
        float(runtime.mf6_rewet_wetfct),
        "IWETIT",
        int(runtime.mf6_rewet_iwetit),
        "IHDWET",
        int(runtime.mf6_rewet_ihdwet),
    ]
    wetdry = np.where(
        np.asarray(solver_mesh.inactive_mask, dtype=bool),
        0.0,
        wetdry_value,
    ).astype(float)
    return rewet_record, wetdry


__all__ = [
    "build_start_heads",
    "initial_condition_field",
    "resolve_head_initial_condition",
    "resolve_rewet_npf_options",
    "rewet_is_enabled",
]
