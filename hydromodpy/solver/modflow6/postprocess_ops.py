"""MODFLOW 6 post-processing helpers: unstructured accumulation and native mesh exports."""

from __future__ import annotations

import csv
import os
from collections.abc import Mapping

import numpy as np

from hydromodpy.core.io.filesystem import create_folder
from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow6.postprocess import (
    get_budget_records_or_none,
    open_budget_file,
)
from hydromodpy.solver.modflow_common.options import ModflowPostprocessOptions

logger = get_logger(__name__)


def to_export_array(model, flat_array: np.ndarray) -> np.ndarray:
    """Reshape flat (ncpl,) to (nrow, ncol) for raster export (structured only)."""
    return model.solver_mesh.reshape_to_grid(flat_array)


def open_mf6_budget_file(path: str):
    """Open one MF6 cell-budget file with a small precision fallback chain."""
    return open_budget_file(path)


def budget_records_or_none(cbb: object, *, kstpkper: tuple[int, int], text: str):
    """Return one budget term, or None when the term is absent from the file."""
    return get_budget_records_or_none(cbb, kstpkper=kstpkper, text=text)


def build_unstructured_cell_adjacency(model) -> list[set[int]]:
    """Return cell-to-cell adjacency for one unstructured planar mesh."""
    n_cells = int(getattr(model, "ncpl", 0) or getattr(model.solver_mesh, "n_cells", 0))
    adjacency: list[set[int]] = [set() for _ in range(n_cells)]
    support = getattr(model, "runtime_mesh_support", None)
    if support is not None:
        edge_cell_a = np.asarray(getattr(support, "edge_cell_a", ()), dtype=int).reshape(-1)
        edge_cell_b = np.asarray(getattr(support, "edge_cell_b", ()), dtype=int).reshape(-1)
        for cell_a, cell_b in zip(edge_cell_a.tolist(), edge_cell_b.tolist(), strict=False):
            if int(cell_a) < 0 or int(cell_b) < 0:
                continue
            if int(cell_a) >= n_cells or int(cell_b) >= n_cells:
                continue
            adjacency[int(cell_a)].add(int(cell_b))
            adjacency[int(cell_b)].add(int(cell_a))
        if any(neighbors for neighbors in adjacency):
            return adjacency

    planar_mesh = getattr(model.solver_mesh, "planar_mesh", None)
    if planar_mesh is None:
        return adjacency

    edge_owner: dict[tuple[int, int], int] = {}
    cell_offset = 0
    for block in tuple(getattr(planar_mesh, "cell_blocks", ()) or ()):
        connectivity = np.asarray(getattr(block, "connectivity", ()), dtype=int)
        if connectivity.ndim != 2:
            continue
        for local_index, node_ids in enumerate(connectivity.tolist()):
            cell_id = int(cell_offset + local_index)
            if cell_id >= n_cells:
                break
            nodes = np.asarray(node_ids, dtype=int).reshape(-1)
            if nodes.size < 3:
                continue
            for node_index in range(int(nodes.size)):
                node_a = int(nodes[node_index])
                node_b = int(nodes[(node_index + 1) % int(nodes.size)])
                edge = tuple(sorted((node_a, node_b)))
                owner = edge_owner.get(edge)
                if owner is None:
                    edge_owner[edge] = cell_id
                    continue
                if int(owner) == cell_id:
                    continue
                adjacency[cell_id].add(int(owner))
                adjacency[int(owner)].add(cell_id)
        cell_offset += int(connectivity.shape[0])
    return adjacency


def accumulate_unstructured_cell_values(
    model,
    *,
    local_values: np.ndarray,
    reference_values: np.ndarray,
    inactive_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Accumulate one per-cell source field along a downhill mesh graph."""
    local = np.asarray(local_values, dtype=float).reshape(-1)
    reference = np.asarray(reference_values, dtype=float).reshape(-1)
    n_cells = int(getattr(model, "ncpl", 0) or getattr(model.solver_mesh, "n_cells", 0))
    if local.size != n_cells or reference.size != n_cells:
        raise ValueError(
            "Unstructured accumulation requires local_values/reference_values "
            f"with {n_cells} entries."
        )

    if inactive_mask is None:
        mask = np.zeros(n_cells, dtype=bool)
    else:
        mask = np.asarray(inactive_mask, dtype=bool).reshape(-1)
        if mask.size != n_cells:
            raise ValueError(f"inactive_mask must have {n_cells} entries, got {mask.size}.")

    active = (~mask) & np.isfinite(reference)
    if not np.any(active):
        return np.zeros(n_cells, dtype=float)

    adjacency = build_unstructured_cell_adjacency(model)
    centroids: np.ndarray | None
    try:
        centroids = np.asarray(model.solver_mesh.cell_centroids(), dtype=float).reshape(n_cells, 2)
    except Exception:
        centroids = None

    ref_active = reference[active]
    ref_range = float(np.nanmax(ref_active) - np.nanmin(ref_active)) if ref_active.size > 0 else 0.0
    tolerance = max(1.0e-9, 1.0e-9 * max(abs(ref_range), 1.0))
    downstream = np.full(n_cells, -1, dtype=int)

    for cell_id in np.flatnonzero(active).tolist():
        best_neighbor = -1
        best_score = 0.0
        cell_ref = float(reference[cell_id])
        for neighbor in adjacency[int(cell_id)]:
            if neighbor < 0 or neighbor >= n_cells or not bool(active[neighbor]):
                continue
            neighbor_ref = float(reference[int(neighbor)])
            drop = cell_ref - neighbor_ref
            if not np.isfinite(drop) or drop <= tolerance:
                continue
            score = drop
            if centroids is not None:
                delta_x = float(centroids[cell_id, 0] - centroids[int(neighbor), 0])
                delta_y = float(centroids[cell_id, 1] - centroids[int(neighbor), 1])
                distance = max((delta_x * delta_x + delta_y * delta_y) ** 0.5, 1.0e-12)
                score = drop / distance
            if score > best_score:
                best_score = float(score)
                best_neighbor = int(neighbor)
        downstream[int(cell_id)] = int(best_neighbor)

    clean_local = np.where(
        active & np.isfinite(local) & (local > -9999.0),
        np.maximum(local, 0.0),
        0.0,
    )
    accumulated = np.zeros(n_cells, dtype=float)
    order = np.argsort(np.where(active, reference, -np.inf).astype(float, copy=False))[::-1]
    for cell_id in order.tolist():
        if not bool(active[int(cell_id)]):
            continue
        accumulated[int(cell_id)] += float(clean_local[int(cell_id)])
        target = int(downstream[int(cell_id)])
        if target >= 0:
            accumulated[target] += float(accumulated[int(cell_id)])

    accumulated[~active] = np.nan
    return accumulated


def native_mesh_exports_enabled(options: ModflowPostprocessOptions) -> bool:
    """Return True when one native mesh export format is enabled."""
    return bool(
        getattr(options, "native_mesh_npz", False)
        or getattr(options, "native_mesh_csv", False)
        or getattr(options, "native_mesh_vtu", False)
        or getattr(options, "native_mesh_png", False)
    )


def native_cell_series_payload(
    model,
    *,
    datasets: Mapping[str, Mapping[int, np.ndarray]],
) -> dict[str, np.ndarray]:
    """Normalize time-indexed cell datasets to stacked (ntime, ncpl) arrays."""
    payload: dict[str, np.ndarray] = {}
    for name, data_by_time in datasets.items():
        if not data_by_time:
            continue
        stacked_rows: list[np.ndarray] = []
        for _, values in sorted(data_by_time.items(), key=lambda item: int(item[0])):
            flat = np.asarray(
                model.solver_mesh.flatten_from_grid(np.asarray(values)),
                dtype=float,
            ).reshape(-1)
            if flat.size != int(model.ncpl):
                continue
            stacked_rows.append(flat)
        if stacked_rows:
            payload[str(name)] = np.vstack(stacked_rows).astype(float, copy=False)
    return payload


def east_side_cell_ids(model) -> set[int]:
    """Return east-boundary cell ids for one DISV topological layer."""
    if getattr(model.solver_mesh, "is_structured", False):
        nrow = int(model.nrow)
        ncol = int(model.ncol)
        return {row * ncol + (ncol - 1) for row in range(nrow)}
    support = getattr(model, "runtime_mesh_support", None)
    if support is None:
        return set()
    return {
        int(cell_id) for cell_id in support.boundary_cell_indices_for_side("east_side").tolist()
    }


def compute_chd_outlet_discharge_east_side_m3_s(
    chd_records,
    *,
    ncpl: int,
    east_side_cell_ids_: set[int],
) -> float:
    """Return total positive east-side CHD outflow [m3/s] for one stress period."""
    if not chd_records or not east_side_cell_ids_:
        return 0.0

    record = chd_records[0]
    if record is None or len(record) == 0:
        return 0.0

    if getattr(record, "dtype", None) is not None and record.dtype.names is not None:
        node_field = "node" if "node" in record.dtype.names else record.dtype.names[0]
        q_field = "q" if "q" in record.dtype.names else record.dtype.names[-1]
        iterator = ((int(item[node_field]), float(item[q_field])) for item in record)
    else:
        iterator = ((int(item[0]), float(item[-1])) for item in record)

    discharge_m3_s = 0.0
    for node, q in iterator:
        if node <= 0:
            continue
        cell_id = (int(node) - 1) % int(ncpl)
        if cell_id not in east_side_cell_ids_:
            continue
        discharge_m3_s += max(-float(q), 0.0)
    return float(discharge_m3_s)


def export_native_mesh_outputs(
    model,
    *,
    options: ModflowPostprocessOptions,
    times: list[float] | tuple[float, ...],
    datasets: Mapping[str, Mapping[int, np.ndarray]],
    prefix: str,
) -> None:
    """Write native mesh exports (NPZ, CSV, VTU, PNG) for cell-based outputs."""
    if not native_mesh_exports_enabled(options):
        return

    cell_series = native_cell_series_payload(model, datasets=datasets)
    if not cell_series:
        return

    mesh_dir = os.path.join(model.save_file, "_mesh")
    create_folder(mesh_dir)
    time_index = np.arange(len(times), dtype=int)
    times_array = np.asarray(times, dtype=float)
    cell_ids = np.arange(int(model.ncpl), dtype=int)

    if getattr(options, "native_mesh_npz", False):
        for name, values in cell_series.items():
            np.savez_compressed(
                os.path.join(mesh_dir, f"{prefix}_{name}.npz"),
                time_index=time_index,
                times=times_array,
                cell_ids=cell_ids,
                values=values,
            )

    if getattr(options, "native_mesh_csv", False):
        for name, values in cell_series.items():
            csv_path = os.path.join(mesh_dir, f"{prefix}_{name}.csv")
            with open(csv_path, "w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["time_index", "time", "cell_id", "value"])
                for tidx, time_value in enumerate(times_array.tolist()):
                    for cell_id, cell_value in enumerate(values[tidx].tolist()):
                        writer.writerow(
                            [
                                int(tidx),
                                float(time_value),
                                int(cell_id),
                                float(cell_value),
                            ]
                        )

    if getattr(options, "native_mesh_vtu", False):
        try:
            from hydromodpy.spatial.mesh.io import write_vtu

            for tidx, _time_value in enumerate(times_array.tolist()):
                cell_fields = {
                    "cell_id": cell_ids.astype(float, copy=False),
                    "top_elevation": np.asarray(model.solver_mesh.top, dtype=float).reshape(-1),
                }
                for name, values in cell_series.items():
                    cell_fields[str(name)] = np.asarray(values[tidx], dtype=float).reshape(-1)
                mesh_with_data = model.solver_mesh.planar_mesh.with_cell_data(**cell_fields)
                write_vtu(
                    os.path.join(mesh_dir, f"{prefix}_t({int(tidx)}).vtu"),
                    mesh_with_data,
                )
        except ImportError as exc:
            logger.warning("Skipping native mesh VTU export: %s", exc)

    if getattr(options, "native_mesh_png", False):
        from hydromodpy.solver.modflow6.render import render_native_mesh_png

        render_native_mesh_png(
            model=model,
            cell_series=cell_series,
            times_array=times_array,
            prefix=prefix,
        )
