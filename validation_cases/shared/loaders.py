"""I/O helpers shared by analytical validation cases and their tests."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.field_routing import CATCHMENT_BUDGET_ZONE
from hydromodpy.core.logging import get_logger
from hydromodpy.core.toml_io.loader import load_toml_with_base_config, merge_toml_payloads

logger = get_logger(__name__)

# The public name every backend's extractor writes for a constant-head record,
# declared in `hydromodpy.results.field_registry`. The raw MODFLOW labels
# ("CONSTANT HEAD", "CHD") stopped reaching the store the day the extractors
# started mapping both vocabularies onto one name, and a lookup written against
# a name nobody writes is a lookup that never matches.
_CONSTANT_HEAD_COMPONENT = "constant_head"


def _legacy_npy_enabled() -> bool:
    """Return whether legacy validation .npy loading is explicitly enabled."""
    return os.environ.get("HMP_ALLOW_LEGACY_NPY_VALIDATION") == "1"


def load_npy_dict(path: Path) -> dict:
    """Load one legacy HydroModPy dictionary payload serialized as ``.npy``."""
    if not _legacy_npy_enabled():
        raise RuntimeError(
            "Legacy validation .npy loading is disabled. Read validation outputs "
            "through the result store, or set HMP_ALLOW_LEGACY_NPY_VALIDATION=1 "
            "for archived pre-v1 artifacts."
        )
    return np.load(path, allow_pickle=True).item()


def load_last_npy_array(postprocess_dir: Path, observable_name: str) -> tuple[int, np.ndarray]:
    """Load the last timestep array from one legacy HydroModPy ``.npy`` output."""
    payload = load_npy_dict(postprocess_dir / f"{observable_name}.npy")
    assert payload, f"{observable_name}.npy is empty."
    last_key = sorted(payload)[-1]
    return int(last_key), np.asarray(payload[last_key], dtype=float)


def load_npy_time_series_arrays(
    postprocess_dir: Path,
    observable_name: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Load one full legacy HydroModPy ``.npy`` time series as stacked arrays."""
    payload = load_npy_dict(postprocess_dir / f"{observable_name}.npy")
    assert payload, f"{observable_name}.npy is empty."

    ordered_items = sorted(
        (int(key), np.asarray(value, dtype=float)) for key, value in payload.items()
    )
    indices = np.asarray([key for key, _ in ordered_items], dtype=int)
    arrays = np.stack([value for _, value in ordered_items], axis=0)
    return indices, arrays


class _DualMeshError(ValueError):
    """A Voronoi dual was read without, or against the wrong, node positions."""


def cell_polygon_areas(store: Any, sim_id: str) -> np.ndarray:
    """Return the plan area of every solver cell of one run, in m2."""
    areas = []
    for ring in load_cell_polygons(store=store, sim_id=sim_id):
        x, y = ring[:, 0], ring[:, 1]
        areas.append(0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))))
    return np.asarray(areas, dtype=float)


def dual_column_index(node_x: np.ndarray, *, xmin: float, xmax: float, ncol: int) -> np.ndarray:
    """Return the equal-width column of each node abscissa, clipped to ``0..ncol-1``."""
    dx = (float(xmax) - float(xmin)) / int(ncol)
    return np.clip(((np.asarray(node_x, dtype=float) - float(xmin)) / dx).astype(int), 0, ncol - 1)


def dual_column_profile(
    values: np.ndarray,
    *,
    node_x: np.ndarray,
    cell_area: np.ndarray,
    xmin: float | None,
    xmax: float | None,
    ncol: int,
) -> np.ndarray:
    """Bin the cell values of a Voronoi dual by node abscissa onto ``ncol`` columns.

    A Voronoi dual holds each head at its node, so a cell belongs to the column
    of its node, not of its polygon. Each column is the area-weighted mean of
    its cells, and a column with no node is filled by index. ``xmin`` and
    ``xmax`` default to the node extent. ``values`` is one value per cell, or
    one row of them per output time.
    """
    node_x = np.asarray(node_x, dtype=float)
    lo = float(node_x.min()) if xmin is None else float(xmin)
    hi = float(node_x.max()) if xmax is None else float(xmax)
    column = dual_column_index(node_x, xmin=lo, xmax=hi, ncol=ncol)
    weight = np.asarray(cell_area, dtype=float)
    rows = np.atleast_2d(np.asarray(values, dtype=float))
    norm = np.bincount(column, weights=weight, minlength=int(ncol))
    filled = norm > 0.0
    index = np.flatnonzero(filled).astype(float)
    profiles = np.empty((rows.shape[0], int(ncol)), dtype=float)
    for row_index, row in enumerate(rows):
        total = np.bincount(column, weights=row * weight, minlength=int(ncol))
        profiles[row_index] = np.interp(
            np.arange(int(ncol), dtype=float), index, total[filled] / norm[filled]
        )
    return profiles[0] if np.ndim(values) == 1 else profiles


def _aggregate_triangles_to_grid(
    data: np.ndarray,
    target_shape: tuple[int, ...],
    store: Any,
    sim_id: str,
    cell_centers: np.ndarray | None = None,
) -> np.ndarray:
    """Collapse unstructured cell values onto an x-profile grid.

    Used when the store contains per-cell data from an unstructured mesh but
    the comparison expects a structured ``(nrow, ncol)`` grid. The cells are
    projected onto a 1D x-profile (mean over cells whose centroid falls
    in each x-bin, with nearest-value fill for empty bins) and the same
    profile is repeated across all rows. That keeps the cross-row spread
    exactly zero, matching the dimensional assumption of 1D validation cases.

    A Voronoi dual needs ``cell_centers``, the node of each cell (see
    :func:`run_dual_cell_centers`). Its cells are then binned by node abscissa
    and weighted by polygon area. Without them a polygon mesh is refused,
    because the vertex mean is not where the dual holds its heads.
    """
    if len(target_shape) != 2:
        return data
    nrow, ncol = target_shape
    sz = None
    try:
        sz = store.open_zarr(sim_id)
        vertices = sz.root["mesh"]["vertices"][:]
        connectivity = sz.root["mesh"]["face_node_connectivity"][:]
        if cell_centers is not None:
            flat = np.asarray(data, dtype=float).reshape(-1)
            if np.shape(cell_centers)[0] != flat.size:
                raise _DualMeshError(
                    f"{np.shape(cell_centers)[0]} cell centres for {flat.size} cell values."
                )
            profile = dual_column_profile(
                flat,
                node_x=np.asarray(cell_centers, dtype=float)[:, 0],
                cell_area=cell_polygon_areas(store, sim_id),
                xmin=None,
                xmax=None,
                ncol=int(ncol),
            )
            return np.repeat(profile.reshape(1, -1), nrow, axis=0)
        if int(np.max(np.sum(np.asarray(connectivity) >= 0, axis=1))) > 3:
            raise _DualMeshError(
                "The run holds polygon cells (a Voronoi dual), whose heads sit at their nodes, "
                "not at their vertex mean. Pass cell_centers=run_dual_cell_centers(result)."
            )
        centroids_x = np.mean(vertices[connectivity, 0], axis=1).astype(float)
        node_x = np.asarray(vertices[:, 0], dtype=float)
        x_min = float(node_x.min())
        x_max = float(node_x.max())
        dx = (x_max - x_min) / ncol
        if dx <= 0:
            return data
        col_idx = np.clip(((centroids_x - x_min) / dx).astype(int), 0, ncol - 1)
        flat = np.asarray(data, dtype=float).reshape(-1)
        if flat.size != col_idx.size:
            return data

        total_col = np.zeros(ncol, dtype=float)
        counts_col = np.zeros(ncol, dtype=int)
        for i, v in enumerate(flat):
            total_col[col_idx[i]] += float(v)
            counts_col[col_idx[i]] += 1
        col_mask = counts_col > 0
        if not np.any(col_mask):
            return data
        profile = np.full(ncol, np.nan, dtype=float)
        profile[col_mask] = total_col[col_mask] / counts_col[col_mask]
        if np.any(~col_mask):
            valid_idx = np.flatnonzero(col_mask)
            profile = np.interp(
                np.arange(ncol, dtype=float),
                valid_idx.astype(float),
                profile[valid_idx],
            )
        return np.repeat(profile.reshape(1, -1), nrow, axis=0)
    except _DualMeshError:
        raise
    except Exception:
        logger.debug("Triangle-to-grid aggregation failed, returning raw data")
        return data
    finally:
        if sz is not None:
            sz.close()


def _aggregate_triangle_history_to_grid(
    data: np.ndarray,
    target_shape: tuple[int, ...],
    store: Any,
    sim_id: str,
) -> np.ndarray:
    """Collapse a time-cell triangular history onto an x-profile grid."""
    history = np.asarray(data, dtype=float)
    if history.ndim == 1:
        return _aggregate_triangles_to_grid(history, target_shape, store, sim_id)
    if history.ndim != 2 or len(target_shape) != 2:
        return data

    mapped_steps: list[np.ndarray] = []
    for values in history:
        mapped = _aggregate_triangles_to_grid(values, target_shape, store, sim_id)
        if tuple(mapped.shape) != tuple(target_shape):
            return data
        mapped_steps.append(np.asarray(mapped, dtype=float))
    return np.stack(mapped_steps, axis=0)


def _load_toml(path: Path) -> dict:
    """Load one TOML file into a plain dictionary."""
    with path.open("r", encoding="utf-8") as stream:
        return tomllib.loads(stream.read().lstrip("\ufeff"))


def load_case_metadata(case_dir: Path) -> dict:
    """Load metadata for one validation case directory."""
    return _load_toml(case_dir / "metadata.toml")


def load_case_config(case_dir: Path, filename: str) -> dict:
    """Load one case-local config file with optional ``base_config`` support."""
    return load_toml_with_base_config(case_dir / filename)


def merge_case_flow_section(
    case_dir: Path,
    flow_section: Mapping[str, object],
    *,
    config_name: str = "config_boussinesq.toml",
) -> dict[str, object]:
    """Merge ``[flow]`` defaults from one case config into one runtime payload."""
    config_path = case_dir / str(config_name)
    if not config_path.exists():
        return dict(flow_section)

    config_payload = load_case_config(case_dir, str(config_name))
    raw_flow = config_payload.get("flow", {})
    if raw_flow is None:
        raw_flow = {}
    if not isinstance(raw_flow, Mapping):
        raise TypeError(f"{config_path} [flow] section must be a mapping")
    return merge_toml_payloads(dict(raw_flow), dict(flow_section))


def load_case_tolerances(case_dir: Path, solver: str | None = None) -> dict:
    """Load tolerance thresholds for one validation case directory."""
    if solver is not None:
        solver_name = str(solver).strip().lower()
        if solver_name:
            candidate_names = [solver_name]
            compact_solver_name = solver_name.replace("_", "")
            if compact_solver_name != solver_name:
                candidate_names.append(compact_solver_name)
            for candidate_name in candidate_names:
                solver_specific = case_dir / f"tolerances_{candidate_name}.toml"
                if solver_specific.exists():
                    return _load_toml(solver_specific)
    return _load_toml(case_dir / "tolerances.toml")


def _reshape_to_expected(
    values: np.ndarray,
    expected_shape: tuple[int, ...] | None,
) -> np.ndarray:
    """Reshape a flat cell vector onto ``expected_shape`` when the size matches."""
    if (
        expected_shape is not None
        and tuple(values.shape) != tuple(expected_shape)
        and values.size == int(np.prod(expected_shape))
    ):
        return values.reshape(tuple(expected_shape))
    return values


def case_config_mesh_bundle_dir(case_dir: Path, config: Mapping[str, object]) -> Path | None:
    """Return the folder of the triangulation a case config reads in ``[mesh.triangle] path``.

    The mesh bundle of a validation case sits next to its ``mesh_2d.msh``. The path is
    relative to the case folder, like every path of the config.
    """
    mesh = config.get("mesh")
    triangle = mesh.get("triangle") if isinstance(mesh, Mapping) else None
    path_raw = str(triangle.get("path", "")).strip() if isinstance(triangle, Mapping) else ""
    if path_raw == "":
        return None
    mesh_path = Path(path_raw).expanduser()
    if not mesh_path.is_absolute():
        mesh_path = (case_dir / mesh_path).resolve()
    return mesh_path.parent


def resolve_case_mesh_bundle_dir(
    case_dir: Path,
    metadata: Mapping[str, object],
    solver: str | None,
) -> Path | None:
    """Return the mesh bundle a solver config reads in ``[mesh.triangle] path``, or None."""
    config_files = metadata.get("config_files")
    solver_name = str(solver or "").strip().lower()
    if not isinstance(config_files, Mapping) or solver_name == "":
        return None
    config_name = str(config_files.get(solver_name, "")).strip()
    if config_name == "":
        return None
    return case_config_mesh_bundle_dir(case_dir, load_case_config(case_dir, config_name))


def _read_bundle_table(bundle_dir: Path, name: str) -> np.ndarray:
    """Read one CSV table of a mesh bundle as a structured array."""
    return np.genfromtxt(
        Path(bundle_dir) / name, delimiter=",", names=True, dtype=None, encoding="utf-8"
    )


def bundle_cell_centers(bundle_dir: Path, n_cells: int) -> tuple[np.ndarray, str]:
    """Return the ``(n_cells, 2)`` solver cell centres of one mesh bundle and the dual kind.

    A triangle grid (``grid_dual = "triangle"``) keeps one cell per bundle
    triangle, centred on its centroid. A Voronoi dual (``grid_dual = "voronoi"``)
    has one cell per bundle node, and the node is the cell centre. The cell
    count tells the two apart.
    """
    cells = _read_bundle_table(bundle_dir, "cells.csv")
    if cells.size == int(n_cells):
        centers = np.column_stack([cells["centroid_x"], cells["centroid_y"]])
        return np.asarray(centers, dtype=float), "triangle"
    nodes = _read_bundle_table(bundle_dir, "nodes.csv")
    if nodes.size == int(n_cells):
        return np.asarray(np.column_stack([nodes["x"], nodes["y"]]), dtype=float), "voronoi"
    raise ValueError(
        f"{n_cells} solver cells match neither the {cells.size} triangles nor the "
        f"{nodes.size} nodes of the mesh bundle {bundle_dir}."
    )


def dual_cell_centers(bundle_dir: Path | None, n_cells: int) -> np.ndarray | None:
    """Return the node of each cell when ``n_cells`` cells are the Voronoi dual of a bundle.

    Return None for a triangle grid, a structured grid, or a cell count that
    matches neither the bundle triangles nor its nodes.
    """
    if bundle_dir is None:
        return None
    if _read_bundle_table(bundle_dir, "cells.csv").size == int(n_cells):
        return None
    if _read_bundle_table(bundle_dir, "nodes.csv").size != int(n_cells):
        return None
    centers, _ = bundle_cell_centers(bundle_dir, n_cells)
    return centers


def run_dual_cell_centers(
    result: Any, metadata: Mapping[str, object] | None = None
) -> np.ndarray | None:
    """Return the ``(n_cells, 2)`` node of each cell of a Voronoi-dual run, or None.

    This is the opt-in test of a strip comparison. It reads the mesh bundle that
    the config of ``result.solver_name`` points at, and compares its node count
    with the cell count of the stored run. A triangle, structured or Boussinesq
    run gives None, and its comparison is untouched.
    """
    store = getattr(result, "store", None)
    sim_id = getattr(result, "sim_id", None)
    case_dir = getattr(result, "case_dir", None)
    if store is None or sim_id is None or case_dir is None:
        return None
    case_dir = Path(case_dir)
    case_metadata = load_case_metadata(case_dir) if metadata is None else metadata
    bundle_dir = resolve_case_mesh_bundle_dir(
        case_dir, case_metadata, getattr(result, "solver_name", None)
    )
    if bundle_dir is None:
        return None
    sz = store.open_zarr(sim_id)
    try:
        mesh = sz.root["mesh"] if "mesh" in sz.root else {}
        if "face_node_connectivity" not in mesh:
            return None
        n_cells = int(mesh["face_node_connectivity"].shape[0])
    finally:
        sz.close()
    return dual_cell_centers(bundle_dir, n_cells)


def _nearest_cell_history_to_grid(
    history: np.ndarray,
    centers: np.ndarray,
    *,
    nx: int,
    ny: int,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
) -> np.ndarray:
    """Give each structured cell the value of the solver cell with the nearest centre.

    For a Voronoi dual the nearest centre is the cell that holds the point, so
    each structured cell reads the solver cell under its centre. Rows run from
    ``y_min`` up, like ``interpolate_bundle_history_to_structured_grids``.
    """
    from scipy.spatial import cKDTree

    x_centers = x_min + (np.arange(int(nx), dtype=float) + 0.5) * (x_max - x_min) / float(nx)
    y_centers = y_min + (np.arange(int(ny), dtype=float) + 0.5) * (y_max - y_min) / float(ny)
    xx, yy = np.meshgrid(x_centers, y_centers)
    _, nearest = cKDTree(np.asarray(centers, dtype=float)).query(
        np.column_stack([xx.ravel(), yy.ravel()])
    )
    data = np.asarray(history, dtype=float).reshape(-1, len(centers))
    return data[:, nearest].reshape(data.shape[0], int(ny), int(nx))


def nearest_cell_grid(
    values: np.ndarray,
    centers: np.ndarray,
    *,
    nx: int,
    ny: int,
    x_min_m: float,
    x_max_m: float,
    y_min_m: float,
    y_max_m: float,
) -> np.ndarray:
    """Give each cell of a ``ny x nx`` grid the value of the solver cell with the nearest centre.

    Rows run from ``y_min_m`` up, like the other regridding helpers.
    """
    return _nearest_cell_history_to_grid(
        np.asarray(values, dtype=float).reshape(1, -1),
        centers,
        nx=nx,
        ny=ny,
        x_min=x_min_m,
        x_max=x_max_m,
        y_min=y_min_m,
        y_max=y_max_m,
    )[0]


def _regrid_bundle_history(
    history: np.ndarray,
    *,
    bundle_dir: Path,
    nx: int,
    ny: int,
    x_min_m: float | None,
    x_max_m: float | None,
    y_min_m: float | None,
    y_max_m: float | None,
    collapse_y_to_x_profile: bool = False,
    store: Any = None,
    sim_id: str | None = None,
) -> np.ndarray:
    """Project one time-cell history of a mesh-bundle run onto a ``ny x nx`` grid.

    A triangle grid goes through ``interpolate_bundle_history_to_structured_grids``.
    A Voronoi dual reads, for each structured cell, the solver cell under its centre.
    A Voronoi dual collapsed to an x-profile bins its cells by node abscissa,
    weighted by polygon area, and so needs ``store`` and ``sim_id``.
    """
    from validation_cases.shared.gmsh_irregular_strip import (
        interpolate_bundle_history_to_structured_grids,
    )

    data = np.asarray(history, dtype=float)
    n_cells = int(data.shape[-1])
    nodes = dual_cell_centers(bundle_dir, n_cells)
    if collapse_y_to_x_profile and nodes is not None:
        if store is None or sim_id is None:
            raise _DualMeshError("Collapsing a Voronoi dual needs the store and sim_id of the run.")
        profile = dual_column_profile(
            data.reshape(-1, n_cells),
            node_x=nodes[:, 0],
            cell_area=cell_polygon_areas(store, sim_id),
            xmin=x_min_m,
            xmax=x_max_m,
            ncol=int(nx),
        )
        return np.repeat(profile[:, None, :], int(ny), axis=1)
    if collapse_y_to_x_profile or _read_bundle_table(bundle_dir, "cells.csv").size == n_cells:
        return interpolate_bundle_history_to_structured_grids(
            data,
            bundle_dir=bundle_dir,
            nx=nx,
            ny=ny,
            x_min_m=x_min_m,
            x_max_m=x_max_m,
            y_min_m=y_min_m,
            y_max_m=y_max_m,
            collapse_y_to_x_profile=collapse_y_to_x_profile,
        )
    centers, _ = bundle_cell_centers(bundle_dir, n_cells)
    return _nearest_cell_history_to_grid(
        data,
        centers,
        nx=nx,
        ny=ny,
        x_min=float(np.min(centers[:, 0])) if x_min_m is None else float(x_min_m),
        x_max=float(np.max(centers[:, 0])) if x_max_m is None else float(x_max_m),
        y_min=float(np.min(centers[:, 1])) if y_min_m is None else float(y_min_m),
        y_max=float(np.max(centers[:, 1])) if y_max_m is None else float(y_max_m),
    )


def load_cell_polygons(*, store: Any, sim_id: str) -> list[np.ndarray]:
    """Return the plan-view ``(n_vertices, 2)`` polygon of every solver cell of one run."""
    sz = store.open_zarr(sim_id)
    try:
        vertices = np.asarray(sz.root["mesh"]["vertices"][:], dtype=float)[:, :2]
        faces = np.asarray(sz.root["mesh"]["face_node_connectivity"][:], dtype=int)
    finally:
        sz.close()
    return [vertices[row[row >= 0]] for row in faces]


def load_cell_centers(*, store: Any, sim_id: str) -> np.ndarray:
    """Return the ``(n_cells, 2)`` centre of every solver cell of one run, as the mesh stored it."""
    sz = store.open_zarr(sim_id)
    try:
        x = np.asarray(sz.root["mesh"]["face_x"][:], dtype=float)
        y = np.asarray(sz.root["mesh"]["face_y"][:], dtype=float)
    finally:
        sz.close()
    return np.column_stack([x, y])


def structured_cell_polygons(
    *,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    nrow: int,
    ncol: int,
) -> list[np.ndarray]:
    """Return one square per cell of a regular grid, row by row from the northern row.

    This is the order in which the result store lists the cells of a structured grid.
    """
    xs = np.linspace(float(x_min), float(x_max), int(ncol) + 1)
    ys = np.linspace(float(y_max), float(y_min), int(nrow) + 1)
    return [
        np.array([(xs[j], ys[i]), (xs[j + 1], ys[i]), (xs[j + 1], ys[i + 1]), (xs[j], ys[i + 1])])
        for i in range(int(nrow))
        for j in range(int(ncol))
    ]


def map_polygons_payload(
    polygons: list[np.ndarray], *, origin_x: float, origin_y: float
) -> list[list[tuple[float, float]]]:
    """Shift cell polygons to ``(origin_x, origin_y)`` and round them to 0.01 m for a figure."""
    return [
        [(round(float(x) - origin_x, 2), round(float(y) - origin_y, 2)) for x, y in polygon]
        for polygon in polygons
    ]


def _load_last_array_from_store(
    *,
    observable_name: str,
    store: Any,
    sim_id: str | None,
    expected_shape: tuple[int, ...] | None = None,
) -> tuple[int, np.ndarray]:
    """Return ``(timestep, values)`` for the last stored timestep.

    A field that is not persisted (the derived ones are opt-in) is rebuilt on
    the fly through ``query_field``, exactly like :func:`load_field_from_store`,
    so a validation case never has to opt a heavy Zarr field back in just to
    read its observable.
    """
    if store is None or sim_id is None:
        raise ValueError(f"Cannot load '{observable_name}': no store/sim_id provided.")

    sz = None
    try:
        sz = store.open_zarr(sim_id)
        grp = sz.root
        arr = None
        for loc in (grp, grp.get("derived"), grp.get("budget")):
            if loc is not None and observable_name in loc:
                arr = loc[observable_name][:]
                break
        if arr is not None:
            data = np.asarray(arr, dtype=float)
            if data.ndim == 3 and data.shape[1] == 1:
                data = data[:, 0, :]
            n_ts = int(data.shape[0])
            last_values = np.asarray(data[n_ts - 1], dtype=float)
            return n_ts - 1, _reshape_to_expected(last_values, expected_shape)
        n_timesteps = int(grp["head"].shape[0]) if "head" in grp else 0
    except Exception as exc:
        raise RuntimeError(
            f"ResultStore query failed for last-timestep '{observable_name}' (sim_id={sim_id})."
        ) from exc
    finally:
        if sz is not None:
            sz.close()

    if n_timesteps == 0:
        raise RuntimeError(
            f"Variable '{observable_name}' is neither stored nor derivable for "
            f"sim_id={sim_id}: the store holds no head stack to rebuild it from."
        )
    try:
        raw = store.query_field(sim_id, observable_name, n_timesteps - 1)
    except Exception as exc:
        raise RuntimeError(
            f"ResultStore query failed for last-timestep '{observable_name}' (sim_id={sim_id})."
        ) from exc
    values = np.asarray(raw, dtype=float)
    if values.ndim == 2 and values.shape[0] == 1:
        values = values[0]
    return n_timesteps - 1, _reshape_to_expected(values, expected_shape)


def load_field_on_expected_grid(
    *,
    observable_name: str,
    case_dir: Path,
    metadata: Mapping[str, object],
    solver: str | None,
    expected_shape: tuple[int, ...],
    x_min_m: float | None = None,
    x_max_m: float | None = None,
    y_min_m: float | None = None,
    y_max_m: float | None = None,
    collapse_y_to_x_profile: bool = False,
    store: Any = None,
    sim_id: str | None = None,
) -> tuple[int, np.ndarray]:
    """Load one validation output and regrid irregular meshes when needed.

    Structured launcher runs already emit arrays matching ``expected_shape``.
    For irregular-triangle launcher runs, the stored watertable output can be
    one cell vector. This helper either projects that vector back onto the
    expected structured grid, or reduces it to one area-weighted x-profile
    when ``collapse_y_to_x_profile`` is requested.
    """

    timestep, values = _load_last_array_from_store(
        observable_name=observable_name,
        store=store,
        sim_id=sim_id,
        expected_shape=expected_shape,
    )
    expected_shape = tuple(expected_shape)
    if not expected_shape or tuple(values.shape) == expected_shape:
        return timestep, values

    normalized_solver = str(solver).strip().lower()
    config_files = metadata.get("config_files")
    if not isinstance(config_files, Mapping) or normalized_solver == "":
        raise AssertionError(
            f"Unexpected shape for {observable_name}: {values.shape} != {expected_shape}"
        )

    config_name = str(config_files.get(normalized_solver, "")).strip()
    if config_name == "":
        raise AssertionError(
            f"Unexpected shape for {observable_name}: {values.shape} != {expected_shape}"
        )

    config_payload = load_case_config(case_dir, config_name)
    bundle_dir = case_config_mesh_bundle_dir(case_dir, config_payload)
    if bundle_dir is None or values.ndim != 1 or len(expected_shape) != 2:
        raise AssertionError(
            f"Unexpected shape for {observable_name}: {values.shape} != {expected_shape}"
        )

    if collapse_y_to_x_profile and dual_cell_centers(bundle_dir, values.size) is not None:
        regridded = _regrid_bundle_history(
            values,
            bundle_dir=bundle_dir,
            nx=int(expected_shape[1]),
            ny=int(expected_shape[0]),
            x_min_m=x_min_m,
            x_max_m=x_max_m,
            y_min_m=y_min_m,
            y_max_m=y_max_m,
            collapse_y_to_x_profile=True,
            store=store,
            sim_id=sim_id,
        )
        return timestep, np.asarray(regridded[0], dtype=float)

    if collapse_y_to_x_profile:
        cells = np.genfromtxt(
            bundle_dir / "cells.csv",
            delimiter=",",
            names=True,
            dtype=None,
            encoding="utf-8",
        )
        centroid_x = np.asarray(cells["centroid_x"], dtype=float).reshape(-1)
        cell_area = np.asarray(cells["area_m2"], dtype=float).reshape(-1)
        x_min = float(np.min(centroid_x)) if x_min_m is None else float(x_min_m)
        x_max = float(np.max(centroid_x)) if x_max_m is None else float(x_max_m)
        x_edges = np.linspace(x_min, x_max, int(expected_shape[1]) + 1, dtype=float)
        profile = np.full(int(expected_shape[1]), np.nan, dtype=float)
        for col_idx in range(int(expected_shape[1])):
            left = float(x_edges[col_idx])
            right = float(x_edges[col_idx + 1])
            if col_idx == int(expected_shape[1]) - 1:
                mask = (centroid_x >= left) & (centroid_x <= right)
            else:
                mask = (centroid_x >= left) & (centroid_x < right)
            if np.any(mask):
                profile[col_idx] = float(np.average(values[mask], weights=cell_area[mask]))
        if np.isnan(profile).any():
            valid_idx = np.flatnonzero(~np.isnan(profile))
            if valid_idx.size == 0:
                raise AssertionError(
                    f"Unexpected shape for {observable_name}: {values.shape} != {expected_shape}"
                )
            profile = np.interp(
                np.arange(profile.size, dtype=float),
                valid_idx.astype(float),
                profile[valid_idx],
            )
        tiled = np.repeat(profile.reshape(1, -1), int(expected_shape[0]), axis=0)
        return timestep, np.asarray(tiled, dtype=float)

    regridded = _regrid_bundle_history(
        values,
        bundle_dir=bundle_dir,
        nx=int(expected_shape[1]),
        ny=int(expected_shape[0]),
        x_min_m=x_min_m,
        x_max_m=x_max_m,
        y_min_m=y_min_m,
        y_max_m=y_max_m,
    )
    return timestep, np.asarray(regridded[0], dtype=float)


def load_last_cell_values(*, observable_name: str, store: Any, sim_id: str | None) -> np.ndarray:
    """Return the flat per-cell values of one observable at the last stored timestep."""
    _, values = _load_last_array_from_store(
        observable_name=observable_name, store=store, sim_id=sim_id
    )
    return np.asarray(values, dtype=float).reshape(-1)


def load_field(
    *,
    store: Any = None,
    sim_id: str | None = None,
    observable_name: str,
    timestep: int = -1,
    expected_shape: tuple[int, ...] | None = None,
    cell_centers: np.ndarray | None = None,
) -> tuple[int, np.ndarray]:
    """Load one spatial field from the result store.

    Parameters
    ----------
    store : ResultStore, optional
        Open :class:`~hydromodpy.results.store.ResultStore` instance.
    sim_id : str, optional
        Simulation identifier inside *store*.
    observable_name : str
        Variable name (e.g. ``"head"``, ``"watertable_elevation"``).
    timestep : int
        Timestep index to load.  ``-1`` (the default) loads the last
        available timestep.
    expected_shape : tuple[int, ...], optional
        When provided and the loaded array has compatible element count
        but a different shape, reshape it.  This bridges the flat
        per-cell vectors returned by the Catalog with the
        ``(nrow, ncol)`` grids expected by validation comparisons.
    cell_centers : np.ndarray, optional
        ``(n_cells, 2)`` node of each cell of a Voronoi-dual run, from
        :func:`run_dual_cell_centers`. It makes the x-profile collapse bin the
        cells by node abscissa. Leave it out for a triangle or structured run.

    Returns
    -------
    tuple[int, np.ndarray]
        ``(timestep_key, values)`` - the resolved integer timestep key
        and the corresponding spatial array.
    """
    resolved_ts: int
    data: np.ndarray

    if store is None or sim_id is None:
        raise ValueError(f"Cannot load field '{observable_name}': no store/sim_id provided.")

    try:
        raw = store.query_field(sim_id, observable_name, timestep)
        resolved_ts = timestep
        if timestep < 0:
            sz = None
            try:
                sz = store.open_zarr(sim_id)
                grp = sz.root
                for loc in (grp, grp.get("derived"), grp.get("budget")):
                    if loc is not None and observable_name in loc:
                        n_ts = loc[observable_name].shape[0]
                        resolved_ts = n_ts + timestep
                        break
            except Exception:
                resolved_ts = timestep
            finally:
                if sz is not None:
                    sz.close()
        data = np.asarray(raw, dtype=float)
        eff_shape = expected_shape
        if eff_shape is None and data.ndim == 1:
            try:
                geo_meta = store.read_geographic_metadata(sim_id)
                nrow = int(geo_meta.get("nrow", 0))
                ncol = int(geo_meta.get("ncol", 0))
                if nrow > 0 and ncol > 0 and nrow * ncol == data.size:
                    eff_shape = (nrow, ncol)
            except Exception:
                pass
        if (
            eff_shape is not None
            and tuple(data.shape) != eff_shape
            and data.size == int(np.prod(eff_shape))
        ):
            data = data.reshape(eff_shape)
        elif (
            eff_shape is not None
            and tuple(data.shape) != eff_shape
            and data.size != int(np.prod(eff_shape))
        ):
            data = _aggregate_triangles_to_grid(
                data,
                eff_shape,
                store,
                sim_id,
                cell_centers,
            )
        return int(resolved_ts), data
    except Exception as exc:
        raise RuntimeError(
            f"ResultStore query failed for variable '{observable_name}' (sim_id={sim_id})."
        ) from exc


def load_time_series_fields(
    *,
    store: Any = None,
    sim_id: str | None = None,
    observable_name: str,
    expected_spatial_shape: tuple[int, ...] | None = None,
    mesh_bundle_dir: Path | None = None,
    x_min_m: float | None = None,
    x_max_m: float | None = None,
    y_min_m: float | None = None,
    y_max_m: float | None = None,
    collapse_y_to_x_profile: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Load all timesteps for one variable from the result store.

    Returns ``(period_indices, stacked_arrays)`` where
    ``stacked_arrays`` has shape ``(n_timesteps, *spatial_shape)``.
    """
    if store is None or sim_id is None:
        raise ValueError(f"Cannot load time-series '{observable_name}': no store/sim_id provided.")

    errors: list[Exception] = []
    sz = None
    try:
        sz = store.open_zarr(sim_id)
        grp = sz.root
        arr = None
        for loc in (grp, grp.get("derived"), grp.get("budget")):
            if loc is not None and observable_name in loc:
                arr = loc[observable_name][:]
                break
        if arr is None and "head" in grp:
            # Not persisted (derived fields are opt-in): rebuild the whole
            # history on the fly, one timestep at a time, like the readers in
            # ``hydromodpy.results.run.array`` do.
            arr = np.stack(
                [
                    np.asarray(store.query_field(sim_id, observable_name, step), dtype=float)
                    for step in range(int(grp["head"].shape[0]))
                ]
            )
        if arr is not None:
            data = np.asarray(arr, dtype=float)
            # Zarr shape is (n_timesteps, n_layers, n_cells) or (n_timesteps, n_cells).
            if data.ndim == 3 and data.shape[1] == 1:
                data = data[:, 0, :]
            n_ts = data.shape[0]
            indices = np.arange(n_ts, dtype=int)
            eff_shape = expected_spatial_shape
            if eff_shape is None and data.ndim == 2:
                try:
                    geo_meta = store.read_geographic_metadata(sim_id)
                    nrow = int(geo_meta.get("nrow", 0))
                    ncol = int(geo_meta.get("ncol", 0))
                    if nrow > 0 and ncol > 0 and nrow * ncol == data.shape[1]:
                        eff_shape = (nrow, ncol)
                except Exception:
                    pass
            if (
                eff_shape is not None
                and tuple(data.shape[1:]) != eff_shape
                and data[:1].size > 0
                and int(np.prod(data.shape[1:])) == int(np.prod(eff_shape))
            ):
                data = data.reshape(n_ts, *eff_shape)
            elif (
                eff_shape is not None
                and tuple(data.shape[1:]) != eff_shape
                and data.ndim == 2
                and data[:1].size > 0
            ):
                if mesh_bundle_dir is not None and len(tuple(eff_shape)) == 2:
                    data = _regrid_bundle_history(
                        data,
                        bundle_dir=Path(mesh_bundle_dir),
                        nx=int(eff_shape[1]),
                        ny=int(eff_shape[0]),
                        x_min_m=x_min_m,
                        x_max_m=x_max_m,
                        y_min_m=y_min_m,
                        y_max_m=y_max_m,
                        collapse_y_to_x_profile=collapse_y_to_x_profile,
                        store=store,
                        sim_id=sim_id,
                    )
                else:
                    data = _aggregate_triangle_history_to_grid(
                        data,
                        eff_shape,
                        store,
                        sim_id,
                    )
            return indices, data
    except Exception as exc:
        errors.append(exc)
    finally:
        if sz is not None:
            sz.close()

    # Try DuckDB timeseries (scalar per timestep, e.g. outlet discharge).
    try:
        ts = store.query_timeseries(sim_id, "_catchment", observable_name)
        values = np.asarray(ts.values, dtype=float)
        indices = np.arange(values.shape[0], dtype=int)
        return indices, values
    except Exception as exc:
        errors.append(exc)

    # Derive outlet discharge from budget table (constant head flux_out).
    # NOTE: the ``unit`` column is a free-text label and does not reliably
    # describe the numerical values (the extractors currently record
    # everything as ``"m3/d"`` regardless of the model's real time unit),
    # so no unit conversion is applied here - callers are responsible for
    # interpreting the values in the model's native units.
    if "outlet_discharge" in observable_name:
        budgets = None
        try:
            budgets = store.query_budget(sim_id)
        except Exception as exc:
            errors.append(exc)
        if budgets is not None and not budgets.empty:
            chd = budgets[budgets["component"].str.lower() == _CONSTANT_HEAD_COMPONENT]
            # The catchment zone is a second support of the same records, the
            # basin of D inside the domain, and not a second boundary. A flux
            # across a boundary of the model is read on the domain row.
            chd = chd[chd["zone_id"].astype(str) != CATCHMENT_BUDGET_ZONE]
            if chd.empty:
                raise RuntimeError(
                    f"'{observable_name}' asks for the flux across a constant-head "
                    f"boundary and the budget of sim {sim_id} carries no "
                    f"'{_CONSTANT_HEAD_COMPONENT}' record; components present: "
                    f"{sorted(budgets['component'].astype(str).unique())}."
                )
            # One record lumps every constant-head cell of one zone, so it answers
            # a question about one named side only while the model holds a single
            # constant-head boundary. Where the store does tell two apart, refuse:
            # handing back a total under one side's name is the silent answer.
            zones = sorted(chd["zone_id"].astype(str).unique())
            if len(zones) > 1 or bool(chd["timestep"].duplicated().any()):
                raise RuntimeError(
                    f"'{observable_name}' names one boundary while the budget of sim "
                    f"{sim_id} carries {len(chd)} constant-head records over "
                    f"{len(zones)} zone(s) and {chd['timestep'].nunique()} timesteps; "
                    "a per-boundary discharge is not readable from a lumped total."
                )
            chd_sorted = chd.sort_values("timestep")
            values = np.asarray(chd_sorted["flux_out"].values, dtype=float)
            indices = np.arange(values.shape[0], dtype=int)
            return indices, values

    cause = errors[-1] if errors else None
    raise RuntimeError(
        f"ResultStore queries failed for time-series '{observable_name}' (sim_id={sim_id})."
    ) from cause


def align_snapshot_series_to_expected_count(
    time_keys: np.ndarray,
    values: np.ndarray,
    elapsed_seconds: np.ndarray | None,
    *,
    expected_count: int,
    name: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Align snapshot-like ``t0..tN`` histories to one expected row count."""
    keys = np.asarray(time_keys, dtype=int).reshape(-1)
    arrays = np.asarray(values, dtype=float)
    expected = int(expected_count)
    if expected < 0:
        raise ValueError(f"{name} expected_count must be non-negative.")
    if arrays.ndim == 0:
        raise ValueError(f"{name} must expose one leading time dimension.")
    if int(arrays.shape[0]) != keys.size:
        raise ValueError(f"{name} has {arrays.shape[0]} value rows but {keys.size} time keys.")

    elapsed = (
        None if elapsed_seconds is None else np.asarray(elapsed_seconds, dtype=float).reshape(-1)
    )
    if elapsed is not None and elapsed.size != keys.size:
        raise ValueError(
            f"{name} has {keys.size} time keys but {elapsed.size} elapsed-second values."
        )

    if keys.size == expected:
        return keys, arrays, elapsed
    if keys.size == expected + 1:
        aligned_elapsed = None if elapsed is None else elapsed[1:]
        return keys[1:], arrays[1:], aligned_elapsed

    raise ValueError(
        f"{name} has {keys.size} rows, expected {expected} step rows or "
        f"{expected + 1} snapshot rows."
    )
