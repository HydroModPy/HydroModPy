"""Read an earlier run as the state a new run starts from.

``[flow] restart_from`` names the field store of an earlier run. This module
opens that store once, before the solve, and returns a
:class:`~hydromodpy.model.initial.state.PriorState`: the last head, the final
stage of each lake and the store it came from. Before it reads, it checks that
the earlier run was solved on the mesh of this run, because the heads are copied
cell by cell. ``read_final_head`` is the same read for the spin-up loop.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.exceptions import IncompatibleMeshError
from hydromodpy.core.fields.nodata import SENTINEL_ABS_THRESHOLD
from hydromodpy.core.logging import get_logger
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.model.initial.state import PriorState

logger = get_logger(__name__)


def written_step(values: np.ndarray) -> np.ndarray:
    """Return the rounding step flopy applies to each value it writes to a MODFLOW 6 file.

    Flopy 3.10 keeps eight decimals, and nine significant digits above 1e5 or
    below 1e-3 in magnitude. Two coordinates closer than half a step are the
    same coordinate to the solver.
    """
    magnitude = np.abs(np.asarray(values, dtype=np.float64))
    scaled = (magnitude > 1e5) | ((magnitude > 0.0) & (magnitude < 1e-3))
    exponent = np.floor(np.log10(np.where(scaled, magnitude, 1.0)))
    return np.where(scaled, 10.0 ** (exponent - 8.0), 1e-8)


def reoriented_rows(rows: np.ndarray) -> np.ndarray:
    """Return padded cell rows with each ring walked the other way, first node kept.

    ``[n0, n1, ..., n_k-1]`` becomes ``[n0, n_k-1, ..., n1]``; the ``-1`` padding stays.
    """
    size = (rows >= 0).sum(axis=1)[:, None]
    columns = np.arange(rows.shape[1])[None, :]
    order = np.where(columns == 0, 0, np.where(columns < size, size - columns, columns))
    return np.take_along_axis(rows, order, axis=1)


def _open_restart_zarr(path: str):
    import zarr

    if path.endswith(".zip"):
        return zarr.open(zarr.storage.ZipStore(path, mode="r"), mode="r")
    return zarr.open(path, mode="r")


def _identity_text(engine: object, version: object, request_hash: object) -> str:
    """One mesh identity as a phrase; attributes a store never recorded read ``unrecorded``."""
    request = str(request_hash or "unrecorded")[:12]
    return f"engine {engine or 'unrecorded'} {version or ''}, request {request}"


def verify_restart_mesh(path: str, cell_mesh: PlanarCellMesh) -> None:
    """Refuse a ``restart_from`` store that was solved on another mesh than ``cell_mesh``.

    A hotstart copies heads cell by cell, so it needs the same cells in the
    same order. The source ``mesh/`` group is compared with the current mesh:
    ``face_node_connectivity`` exactly (a ring walked the other way is the same
    cell, as MODFLOW 6 stores its DISV clockwise) and the vertices to half the
    rounding step flopy writes (a finer difference never reaches the solver).
    A source store that holds no mesh keeps the cell-count rule of the head
    shape check and a warning.

    Raises
    ------
    IncompatibleMeshError
        When the connectivity or a vertex differs. The message names the
        engine, version and request hash of both meshes.
    """
    root = _open_restart_zarr(path)
    if "mesh" not in root or "face_node_connectivity" not in root["mesh"]:
        logger.warning(
            "restart_from: %r stores no mesh, so only the cell count is checked; the heads are "
            "copied cell by cell and are wrong if the cell order differs.",
            path,
        )
        return
    group = root["mesh"]
    stored_rows = np.asarray(group["face_node_connectivity"][:], dtype=np.int64)
    current_rows = np.asarray(cell_mesh.geometry.padded_connectivity, dtype=np.int64)
    width = max(stored_rows.shape[1], current_rows.shape[1])
    stored_rows, current_rows = (
        np.pad(rows, ((0, 0), (0, width - rows.shape[1])), constant_values=-1)
        for rows in (stored_rows, current_rows)
    )
    stored_xy = np.asarray(group["vertices"][:], dtype=float)[:, :2]
    current_xy = np.asarray(cell_mesh.mesh.vertices, dtype=float)[:, :2]
    reason = None
    if stored_rows.shape != current_rows.shape or stored_xy.shape != current_xy.shape:
        reason = (
            f"{stored_rows.shape[0]} cells and {stored_xy.shape[0]} vertices stored, "
            f"{current_rows.shape[0]} and {current_xy.shape[0]} in this run"
        )
    else:
        same_ring = (stored_rows == current_rows).all(axis=1) | (
            stored_rows == reoriented_rows(current_rows)
        ).all(axis=1)
        moved = np.abs(stored_xy - current_xy) > 0.505 * written_step(stored_xy)
        if not same_ring.all():
            first = int(np.flatnonzero(~same_ring)[0])
            reason = f"the cell connectivity differs from cell {first}"
        elif moved.any():
            first = int(np.flatnonzero(moved.any(axis=1))[0])
            shift = float(np.abs(stored_xy - current_xy)[moved].max())
            reason = (
                f"{int(moved.any(axis=1).sum())} vertices moved (first: {first}, "
                f"up to {shift:.3g} m)"
            )
    if reason is None:
        return
    identity = cell_mesh.identity
    prior = _identity_text(
        group.attrs.get("engine"),
        group.attrs.get("engine_version"),
        group.attrs.get("mesh_request_hash"),
    )
    current = _identity_text(identity.engine_id, identity.engine_version, identity.request_hash)
    raise IncompatibleMeshError(
        f"restart_from: {path!r} was solved on another mesh than this run: {reason}. "
        f"Prior run: {prior}. This run: {current}. "
        "Restart from a run with the same [mesh] settings, on the same engine build."
    )


def _last_head(root, path: str, who: str) -> np.ndarray:
    """Return the last time step of ``head`` as ``(nlay, ncpl)``, sentinel cells as NaN."""
    if "head" not in root:
        raise ValueError(f"{who}: no 'head' field in {path!r}")
    head = np.asarray(root["head"][-1], dtype=float)
    head = head.reshape(head.shape[0], -1) if head.ndim > 1 else head.reshape(1, -1)
    return np.where(np.abs(head) > SENTINEL_ABS_THRESHOLD, np.nan, head)


def read_restart_lake_stages(path: str) -> dict[str, float]:
    """Return each lake's final stage ``{lake_id: stage}`` from a prior run's Zarr.

    Reads the ``lake_state_final`` group written at extraction time, the lake
    companion of the ``head`` field for ``[flow] restart_from``. Returns an empty
    mapping when the prior run had no lake (older stores, non-lake runs), so
    callers keep the per-lake ``initial_stage``.
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
    diff can ignore them. The spin-up loop reads this to compare two cycles.
    """
    return _last_head(_open_restart_zarr(path), path, "read_final_head")


def read_prior_state(
    path: str, cell_mesh: PlanarCellMesh, *, sim_id: str | None = None
) -> PriorState:
    """Return the state a run restarts from, read from the field store at ``path``.

    The mesh of the store is checked against ``cell_mesh`` first, so a store
    solved on another mesh is refused before any head is read. ``sim_id`` is the
    run the store belongs to, when the caller knows it.

    Raises
    ------
    IncompatibleMeshError
        When the store was solved on another mesh.
    ValueError
        When the store holds no ``head`` field.
    """
    verify_restart_mesh(path, cell_mesh)
    head = _last_head(_open_restart_zarr(path), path, "restart_from")
    return PriorState(
        head=head,
        lake_stages=read_restart_lake_stages(path),
        path=str(path),
        sim_id=sim_id,
    )


__all__ = [
    "read_final_head",
    "read_prior_state",
    "read_restart_lake_stages",
    "reoriented_rows",
    "verify_restart_mesh",
    "written_step",
]
