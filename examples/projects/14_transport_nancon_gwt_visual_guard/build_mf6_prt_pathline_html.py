from __future__ import annotations

import argparse
import csv
import html
import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import zarr
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import PowerNorm, to_rgba
from matplotlib.path import Path as MplPath
from run_nancon_visual_guard import DEFAULT_MESH_BUNDLE, linked_figure, load_nancon_mesh
from zarr.storage import ZipStore

EXAMPLE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = EXAMPLE_ROOT.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.solver.modflow6.prt_tracks import (
    read_prt_track_csv,
    read_time_units_from_tdis,
)

DEFAULT_RUN_CONFIG = EXAMPLE_ROOT / "run_nancon_steady_mf6_prt_pathlines.toml"
DEFAULT_WORKSPACE = EXAMPLE_ROOT / "outputs" / "mf6_prt_pathlines" / "workspace"
DEFAULT_OUTPUT_DIR = EXAMPLE_ROOT / "outputs" / "mf6_prt_pathlines" / "web"
DEFAULT_POROSITY = 0.01
MAP_DPI = 300
MAP_FIGSIZE = (10.8, 7.7)
PATHLINE_COLOR = "#3b0764"


@dataclass(frozen=True)
class PrtPathlineData:
    source_path: Path
    source_kind: str
    x_m: np.ndarray
    y_m: np.ndarray
    z_m: np.ndarray
    time_days: np.ndarray
    status: np.ndarray | None
    reason: np.ndarray | None
    specific_discharge_m_s: np.ndarray | None = None

    @property
    def n_particles(self) -> int:
        return int(self.x_m.shape[0])

    @property
    def max_steps(self) -> int:
        return int(self.x_m.shape[1])


def _latest_zarr_zip(workspace: Path) -> Path:
    candidates = sorted(
        (workspace / "simulations").glob("*.zarr.zip"),
        key=lambda path: path.stat().st_mtime,
    )
    if not candidates:
        raise FileNotFoundError(f"No .zarr.zip simulation store found under {workspace}")
    return candidates[-1]


def _latest_track_csv(workspace: Path) -> Path | None:
    candidates = sorted(
        workspace.rglob("*.trk.csv"),
        key=lambda path: path.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


def _read_array(group: Any, name: str, shape: tuple[int, int] | None = None) -> np.ndarray:
    if name in group:
        arr = np.asarray(group[name], dtype=float)
    elif shape is not None:
        arr = np.full(shape, np.nan, dtype=float)
    else:
        raise KeyError(name)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    return arr


def read_prt_pathlines_from_zarr(zarr_path: Path) -> PrtPathlineData:
    store = ZipStore(zarr_path, mode="r")
    try:
        root = zarr.open_group(store=store, mode="r")
        group = root["particles"]
        x = _read_array(group, "x")
        y = _read_array(group, "y", x.shape)
        z = _read_array(group, "z", x.shape)
        time = _read_array(group, "time", x.shape)
        status = _read_array(group, "status", x.shape) if "status" in group else None
        reason = _read_array(group, "reason", x.shape) if "reason" in group else None
        specific_discharge = None
        if "budget" in root and "data-spdis" in root["budget"]:
            raw = np.asarray(root["budget"]["data-spdis"], dtype=float)
            if raw.ndim == 3:
                specific_discharge = raw[-1, 0, :].reshape(-1)
            elif raw.ndim == 2:
                specific_discharge = raw[-1, :].reshape(-1)
            else:
                specific_discharge = raw.reshape(-1)
    finally:
        store.close()
    return PrtPathlineData(
        source_path=zarr_path,
        source_kind="zarr",
        x_m=x,
        y_m=y,
        z_m=z,
        time_days=time,
        status=status,
        reason=reason,
        specific_discharge_m_s=specific_discharge,
    )


def read_prt_pathlines_from_track_csv(csv_path: Path) -> PrtPathlineData:
    tdis_path = next(
        iter(Path(csv_path).parent.glob("*.tdis")), Path(csv_path).parent / "mfsim.tdis"
    )
    arrays = read_prt_track_csv(csv_path, time_units=read_time_units_from_tdis(tdis_path))
    if arrays is None:
        raise ValueError(f"Empty MODFLOW 6 PRT track CSV: {csv_path}")
    return PrtPathlineData(
        source_path=Path(csv_path),
        source_kind="track_csv",
        x_m=arrays.x,
        y_m=arrays.y,
        z_m=arrays.z,
        time_days=arrays.time,
        status=arrays.status,
        reason=arrays.reason,
        specific_discharge_m_s=None,
    )


def _valid_mask(data: PrtPathlineData, particle_index: int) -> np.ndarray:
    return np.isfinite(data.x_m[particle_index]) & np.isfinite(data.y_m[particle_index])


def _pathline_distances_km(data: PrtPathlineData) -> np.ndarray:
    distances = np.full(data.n_particles, np.nan, dtype=float)
    for i in range(data.n_particles):
        valid = _valid_mask(data, i)
        if np.count_nonzero(valid) < 2:
            continue
        xy = np.column_stack((data.x_m[i, valid], data.y_m[i, valid]))
        step_lengths = np.linalg.norm(np.diff(xy, axis=0), axis=1)
        distances[i] = float(np.sum(step_lengths) / 1000.0)
    return distances


def _net_displacements_m(data: PrtPathlineData) -> np.ndarray:
    displacements = np.full(data.n_particles, np.nan, dtype=float)
    for i in range(data.n_particles):
        valid = _valid_mask(data, i)
        if np.count_nonzero(valid) < 2:
            continue
        xy = np.column_stack((data.x_m[i, valid], data.y_m[i, valid]))
        displacements[i] = float(np.linalg.norm(xy[-1] - xy[0]))
    return displacements


def _final_values(values: np.ndarray, data: PrtPathlineData) -> np.ndarray:
    out = np.full(data.n_particles, np.nan, dtype=float)
    for i in range(data.n_particles):
        valid = _valid_mask(data, i) & np.isfinite(values[i])
        if np.any(valid):
            out[i] = float(values[i, valid][-1])
    return out


def compute_metrics(data: PrtPathlineData, *, porosity: float) -> dict[str, Any]:
    valid_counts = np.array(
        [np.count_nonzero(_valid_mask(data, i)) for i in range(data.n_particles)]
    )
    distances_km = _pathline_distances_km(data)
    distances_m = distances_km * 1000.0
    net_displacements_m = _net_displacements_m(data)
    final_time = _final_values(data.time_days, data)
    metrics = {
        "pathline_source": str(data.source_path),
        "pathline_source_kind": data.source_kind,
        "n_particles": data.n_particles,
        "max_steps": data.max_steps,
        "valid_point_count": int(np.sum(valid_counts)),
        "min_steps_per_particle": int(np.min(valid_counts)) if valid_counts.size else 0,
        "max_steps_per_particle": int(np.max(valid_counts)) if valid_counts.size else 0,
        "median_travel_distance_m": float(np.nanmedian(distances_m)),
        "max_travel_distance_m": float(np.nanmax(distances_m)),
        "median_travel_distance_km": float(np.nanmedian(distances_km)),
        "max_travel_distance_km": float(np.nanmax(distances_km)),
        "median_net_displacement_m": float(np.nanmedian(net_displacements_m)),
        "max_net_displacement_m": float(np.nanmax(net_displacements_m)),
        "median_final_time_days": float(np.nanmedian(final_time)),
        "max_final_time_days": float(np.nanmax(final_time)),
    }
    if data.specific_discharge_m_s is not None:
        q = np.asarray(data.specific_discharge_m_s, dtype=float)
        q = q[np.isfinite(q)]
        if q.size:
            pore_velocity_m_year = q * 365.0 * 86400.0 / porosity
            metrics["porosity_for_velocity"] = float(porosity)
            metrics["median_darcy_velocity_m_year"] = float(np.nanmedian(q * 365.0 * 86400.0))
            metrics["max_darcy_velocity_m_year"] = float(np.nanmax(q * 365.0 * 86400.0))
            metrics["median_pore_velocity_m_year"] = float(np.nanmedian(pore_velocity_m_year))
            metrics["p95_pore_velocity_m_year"] = float(np.nanquantile(pore_velocity_m_year, 0.95))
            metrics["max_pore_velocity_m_year"] = float(np.nanmax(pore_velocity_m_year))
    if data.status is not None:
        final_status = _final_values(data.status, data)
        values, counts = np.unique(final_status[np.isfinite(final_status)], return_counts=True)
        metrics["final_status_counts"] = {
            str(int(value)): int(count) for value, count in zip(values, counts, strict=False)
        }
    if data.reason is not None:
        final_reason = _final_values(data.reason, data)
        values, counts = np.unique(final_reason[np.isfinite(final_reason)], return_counts=True)
        metrics["final_reason_counts"] = {
            str(int(value)): int(count) for value, count in zip(values, counts, strict=False)
        }
    return metrics


def compute_river_endpoint_metrics(mesh, data: PrtPathlineData) -> dict[str, Any]:
    river_centroids_m = mesh.centroids_m[mesh.river_cells]
    if not len(river_centroids_m):
        return {}

    endpoint_count = 0
    river_endpoint_count = 0
    nearest_distances_m: list[float] = []
    for i in range(data.n_particles):
        valid = _valid_mask(data, i)
        if not np.any(valid):
            continue
        xy_abs = np.column_stack((data.x_m[i, valid], data.y_m[i, valid]))
        endpoint_rel_m = xy_abs[-1] - mesh.origin_xy_m
        endpoint_km = endpoint_rel_m / 1000.0
        endpoint_count += 1

        containing_cell = None
        for cell_id, polygon in enumerate(mesh.polygons_km):
            if MplPath(polygon).contains_point(endpoint_km):
                containing_cell = cell_id
                break
        if containing_cell is not None and bool(mesh.river_cells[containing_cell]):
            river_endpoint_count += 1

        distance_m = np.min(np.linalg.norm(river_centroids_m - endpoint_rel_m, axis=1))
        nearest_distances_m.append(float(distance_m))

    if not nearest_distances_m:
        return {}
    distances = np.asarray(nearest_distances_m, dtype=float)
    return {
        "endpoint_count": int(endpoint_count),
        "river_endpoint_count": int(river_endpoint_count),
        "endpoint_nearest_river_median_m": float(np.nanmedian(distances)),
        "endpoint_nearest_river_max_m": float(np.nanmax(distances)),
    }


def read_flow_configuration_cards(config_path: Path) -> list[tuple[str, str, str]]:
    if not config_path.is_file():
        return [("Run config", "not found", str(config_path))]

    with config_path.open("rb") as handle:
        config = tomllib.load(handle)

    modflow6 = config.get("modflow6", {})
    runtime = modflow6.get("runtime", {})
    tgrid = modflow6.get("tgrid", {})
    sgrid = modflow6.get("sgrid", {})
    vertical = sgrid.get("vertical", {}) if isinstance(sgrid, dict) else {}
    process_entries = config.get("simulation", {}).get("process", [])
    flow_solvers = next(
        (
            ", ".join(process.get("solvers", []))
            for process in process_entries
            if process.get("type") == "flow"
        ),
        "n/a",
    )
    transport_solvers = next(
        (
            ", ".join(process.get("solvers", []))
            for process in process_entries
            if process.get("type") == "transport"
        ),
        "n/a",
    )
    prt = config.get("transport", {}).get("modflow6prt", {}).get("parameters", {})
    track_times = prt.get("track_times_days")
    if track_times is not None:
        track_note = f"{len(track_times)} requested output times"
    elif prt.get("track_time_step_days") is not None and prt.get("stop_time_days") is not None:
        n_times = (
            int(np.floor(float(prt["stop_time_days"]) / float(prt["track_time_step_days"]))) + 1
        )
        track_note = f"{n_times} requested output times, every {prt['track_time_step_days']:g} days"
    else:
        track_note = "default PRT output times"
    return [
        (
            "Flow solver",
            flow_solvers,
            f"steady first period: {bool(tgrid.get('firstpersteady', False))}",
        ),
        (
            "Flow numerics",
            str(runtime.get("mf6_ims_complexity", "n/a")),
            (
                f"outer/inner max {runtime.get('mf6_outer_maximum', 'n/a')}/"
                f"{runtime.get('mf6_inner_maximum', 'n/a')}"
            ),
        ),
        (
            "Vertical grid",
            f"{vertical.get('nlay', 'n/a')} layer",
            f"vka={modflow6.get('process_specific', {}).get('vka', 'n/a')}",
        ),
        (
            "PRT solver",
            transport_solvers,
            f"release zone {prt.get('release_zone', 'n/a')}",
        ),
        (
            "PRT release",
            f"{prt.get('max_particles', 'n/a')} particles",
            f"upstream top quantile {prt.get('upstream_top_quantile', 'n/a')}",
        ),
        (
            "PRT porosity",
            f"{float(prt.get('porosity', DEFAULT_POROSITY)):.3g}",
            "particle speed scales as specific discharge / porosity",
        ),
        (
            "PRT tracking",
            f"{float(prt.get('stop_time_days', 0.0)):.0f} days",
            track_note,
        ),
        (
            "Base config",
            Path(str(config.get("base_config", "n/a"))).name,
            "Nancon steady hydrography mesh input",
        ),
    ]


def _mesh_collection(mesh, values: np.ndarray, *, cmap: str = "terrain") -> PolyCollection:
    return PolyCollection(
        mesh.polygons_km,
        array=values,
        cmap=cmap,
        edgecolors="#263238",
        linewidths=0.05,
    )


def _boundary_segments_from_polygons(mesh) -> list[np.ndarray]:
    edge_counts: dict[tuple[tuple[float, float], tuple[float, float]], int] = {}
    edge_values: dict[tuple[tuple[float, float], tuple[float, float]], np.ndarray] = {}
    for polygon in mesh.polygons_km:
        n_vertices = polygon.shape[0]
        for idx in range(n_vertices):
            segment = np.vstack((polygon[idx], polygon[(idx + 1) % n_vertices]))
            a = tuple(np.round(segment[0], 9))
            b = tuple(np.round(segment[1], 9))
            key = tuple(sorted((a, b)))
            edge_counts[key] = edge_counts.get(key, 0) + 1
            edge_values[key] = segment
    return [edge_values[key] for key, count in edge_counts.items() if count == 1]


def _add_watershed_boundary(ax, mesh, *, linewidth: float = 1.65) -> None:
    segments = _boundary_segments_from_polygons(mesh)
    if segments:
        ax.add_collection(
            LineCollection(
                segments,
                colors="#ffffff",
                linewidths=linewidth + 2.2,
                alpha=0.98,
                zorder=11,
            )
        )
        ax.add_collection(
            LineCollection(
                segments,
                colors="#0f172a",
                linewidths=linewidth,
                alpha=0.98,
                zorder=12,
                label="watershed boundary",
            )
        )


def _add_outlet(ax, mesh) -> None:
    ax.scatter(
        [mesh.outlet_km[0]],
        [mesh.outlet_km[1]],
        s=42,
        marker="*",
        color="#ffffff",
        edgecolor="#111827",
        linewidth=0.9,
        zorder=14,
        label="outlet",
    )
    ax.annotate(
        "outlet",
        xy=(mesh.outlet_km[0], mesh.outlet_km[1]),
        xytext=(6, 5),
        textcoords="offset points",
        fontsize=8.5,
        color="#111827",
        zorder=15,
    )


def _decorate_map(ax, mesh, title: str) -> None:
    xmin, xmax, ymin, ymax = mesh.extent_km
    padx = max((xmax - xmin) * 0.035, 0.1)
    pady = max((ymax - ymin) * 0.035, 0.1)
    ax.set_xlim(xmin - padx, xmax + padx)
    ax.set_ylim(ymin - pady, ymax + pady)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("x from local origin (km)")
    ax.set_ylabel("y from local origin (km)")
    ax.set_title(title)
    ax.grid(True, alpha=0.18)


def _add_rivers(ax, mesh, *, linewidth: float = 0.65) -> None:
    if mesh.river_segments_km:
        ax.add_collection(
            LineCollection(
                mesh.river_segments_km,
                colors="#0077b6",
                linewidths=linewidth,
                alpha=0.88,
                zorder=4,
            )
        )


def _pathline_xy_km(data: PrtPathlineData, mesh) -> list[np.ndarray]:
    tracks: list[np.ndarray] = []
    for i in range(data.n_particles):
        valid = _valid_mask(data, i)
        if not np.any(valid):
            continue
        xy_m = np.column_stack((data.x_m[i, valid], data.y_m[i, valid]))
        xy_km = (xy_m - mesh.origin_xy_m) / 1000.0
        tracks.append(xy_km)
    return tracks


def _pathline_segment_collection(
    data: PrtPathlineData,
    mesh,
    *,
    linewidth: float,
    alpha: float,
) -> LineCollection | None:
    segments: list[np.ndarray] = []

    for i in range(data.n_particles):
        valid = _valid_mask(data, i) & np.isfinite(data.time_days[i])
        if np.count_nonzero(valid) < 2:
            continue
        xy_m = np.column_stack((data.x_m[i, valid], data.y_m[i, valid]))
        xy_km = (xy_m - mesh.origin_xy_m) / 1000.0
        for j in range(xy_km.shape[0] - 1):
            segments.append(xy_km[j : j + 2])

    if not segments:
        return None
    return LineCollection(
        segments,
        colors=PATHLINE_COLOR,
        linewidths=linewidth,
        alpha=alpha,
        zorder=9,
    )


def _start_end_displacements(
    data: PrtPathlineData, mesh
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    starts_km: list[np.ndarray] = []
    ends_km: list[np.ndarray] = []
    displacements_m: list[np.ndarray] = []
    particle_ids: list[int] = []
    for i in range(data.n_particles):
        valid = _valid_mask(data, i)
        if np.count_nonzero(valid) < 2:
            continue
        xy_m = np.column_stack((data.x_m[i, valid], data.y_m[i, valid]))
        xy_km = (xy_m - mesh.origin_xy_m) / 1000.0
        starts_km.append(xy_km[0])
        ends_km.append(xy_km[-1])
        displacements_m.append(xy_m[-1] - xy_m[0])
        particle_ids.append(i)
    if not starts_km:
        empty = np.empty((0, 2), dtype=float)
        return empty, empty, empty, np.empty(0, dtype=int)
    return (
        np.vstack(starts_km),
        np.vstack(ends_km),
        np.vstack(displacements_m),
        np.asarray(particle_ids, dtype=int),
    )


def _particle_marker_colors(data: PrtPathlineData, particle_ids: np.ndarray) -> np.ndarray:
    del data
    return np.full((particle_ids.size, 4), to_rgba(PATHLINE_COLOR), dtype=float)


def _plot_start_end_markers(
    ax,
    data: PrtPathlineData,
    starts_km: np.ndarray,
    ends_km: np.ndarray,
    particle_ids: np.ndarray,
) -> None:
    if not starts_km.size:
        return
    colors = _particle_marker_colors(data, particle_ids)
    ax.scatter(
        starts_km[:, 0],
        starts_km[:, 1],
        s=5,
        c=colors,
        edgecolor="#f8fafc",
        linewidth=0.22,
        zorder=13,
    )
    ax.scatter(
        ends_km[:, 0],
        ends_km[:, 1],
        s=7,
        c=colors,
        marker="s",
        edgecolor="#f8fafc",
        linewidth=0.22,
        zorder=13,
    )


def plot_pathlines_over_topography(mesh, data: PrtPathlineData, path: Path) -> None:
    fig, ax = plt.subplots(figsize=MAP_FIGSIZE, constrained_layout=True)
    collection = _mesh_collection(mesh, mesh.z_top_m, cmap="terrain")
    collection.set_alpha(0.66)
    ax.add_collection(collection)
    _add_rivers(ax, mesh)
    _add_watershed_boundary(ax, mesh)
    track_collection = _pathline_segment_collection(data, mesh, linewidth=0.32, alpha=0.82)
    starts_km, ends_km, _, particle_ids = _start_end_displacements(data, mesh)
    if track_collection is not None:
        ax.add_collection(track_collection)
    _plot_start_end_markers(ax, data, starts_km, ends_km, particle_ids)
    _add_outlet(ax, mesh)
    _decorate_map(ax, mesh, "MF6-PRT pathlines over Nancon topography")
    cbar = fig.colorbar(collection, ax=ax, location="left", shrink=0.78, pad=0.02)
    cbar.set_label("surface elevation (m)")
    fig.savefig(path, dpi=MAP_DPI)
    plt.close(fig)


def plot_global_displacement_vectors(mesh, data: PrtPathlineData, path: Path) -> None:
    fig, ax = plt.subplots(figsize=MAP_FIGSIZE, constrained_layout=True)
    collection = _mesh_collection(mesh, mesh.z_top_m, cmap="terrain")
    collection.set_alpha(0.66)
    ax.add_collection(collection)
    _add_rivers(ax, mesh, linewidth=0.8)
    _add_watershed_boundary(ax, mesh)
    track_collection = _pathline_segment_collection(data, mesh, linewidth=0.32, alpha=0.82)
    starts_km, ends_km, _, particle_ids = _start_end_displacements(data, mesh)
    if track_collection is not None:
        ax.add_collection(track_collection)
    if starts_km.size:
        distances_m = _pathline_distances_km(data) * 1000.0
        _plot_start_end_markers(ax, data, starts_km, ends_km, particle_ids)
        note = (
            "full pathlines, no vector amplification\n"
            f"median length {format_distance_m(float(np.nanmedian(distances_m)))}; "
            f"max {format_distance_m(float(np.nanmax(distances_m)))}"
        )
        ax.text(
            0.02,
            0.02,
            note,
            transform=ax.transAxes,
            fontsize=10,
            color="#1f2933",
            bbox={"facecolor": "white", "edgecolor": "#d9e2ec", "alpha": 0.92, "pad": 7},
            zorder=12,
        )
        _add_outlet(ax, mesh)
    _decorate_map(ax, mesh, "MF6-PRT full particle paths over relief and rivers")
    cbar = fig.colorbar(collection, ax=ax, location="left", shrink=0.78, pad=0.02)
    cbar.set_label("surface elevation (m)")
    fig.savefig(path, dpi=MAP_DPI)
    plt.close(fig)


def plot_velocity_magnitude(mesh, data: PrtPathlineData, path: Path, *, porosity: float) -> None:
    if data.specific_discharge_m_s is None:
        return
    values = np.asarray(data.specific_discharge_m_s, dtype=float).reshape(-1)
    if values.size != len(mesh.polygons_km):
        return
    pore_velocity_m_year = values * 365.0 * 86400.0 / porosity
    finite = pore_velocity_m_year[np.isfinite(pore_velocity_m_year)]
    if not finite.size:
        return

    fig, ax = plt.subplots(figsize=MAP_FIGSIZE, constrained_layout=True)
    collection = _mesh_collection(mesh, pore_velocity_m_year, cmap="viridis")
    vmax = float(np.nanquantile(finite, 0.97))
    if vmax > 0.0:
        collection.set_norm(PowerNorm(gamma=0.45, vmin=0.0, vmax=vmax))
    ax.add_collection(collection)
    _add_rivers(ax, mesh, linewidth=0.8)
    _add_watershed_boundary(ax, mesh)
    _add_outlet(ax, mesh)
    _decorate_map(ax, mesh, "MF6 specific-discharge-derived pore velocity")
    cbar = fig.colorbar(collection, ax=ax, location="right", shrink=0.78, pad=0.02)
    cbar.set_label(f"pore velocity magnitude (m/year), porosity={porosity:g}")
    fig.savefig(path, dpi=MAP_DPI)
    plt.close(fig)


def plot_release_points(mesh, data: PrtPathlineData, path: Path) -> None:
    fig, ax = plt.subplots(figsize=MAP_FIGSIZE, constrained_layout=True)
    river_values = np.where(mesh.river_cells, 1.0, 0.0)
    collection = _mesh_collection(mesh, river_values, cmap="Blues")
    ax.add_collection(collection)
    _add_rivers(ax, mesh, linewidth=0.75)
    _add_watershed_boundary(ax, mesh)
    starts = np.array([track[0] for track in _pathline_xy_km(data, mesh)])
    if starts.size:
        ax.scatter(
            starts[:, 0],
            starts[:, 1],
            s=18,
            marker="o",
            color="#dc2626",
            edgecolor="white",
            linewidth=0.5,
            zorder=8,
            label="PRT release",
        )
    _add_outlet(ax, mesh)
    ax.legend(loc="upper right")
    _decorate_map(ax, mesh, "Upstream non-river PRT release points")
    fig.savefig(path, dpi=MAP_DPI)
    plt.close(fig)


def plot_travel_time(data: PrtPathlineData, path: Path) -> None:
    distances_m = _pathline_distances_km(data) * 1000.0
    final_time = _final_values(data.time_days, data)
    fig, axes = plt.subplots(1, 2, figsize=(13.6, 5.6), constrained_layout=True)
    ids = np.arange(data.n_particles)
    axes[0].bar(ids, distances_m, color="#2563eb")
    axes[0].set_title("Pathline length by particle")
    axes[0].set_xlabel("particle index")
    axes[0].set_ylabel("pathline length (m)")
    axes[0].grid(True, axis="y", alpha=0.25)
    axes[1].bar(ids, final_time, color="#16a34a")
    axes[1].set_title("Final recorded tracking time")
    axes[1].set_xlabel("particle index")
    axes[1].set_ylabel("time (days)")
    axes[1].grid(True, axis="y", alpha=0.25)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_displacement_zoom(data: PrtPathlineData, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 7.2), constrained_layout=True)
    colors = plt.cm.plasma(np.linspace(0.0, 1.0, max(data.n_particles, 2)))
    max_abs = 0.0
    for i in range(data.n_particles):
        valid = _valid_mask(data, i)
        if not np.any(valid):
            continue
        x = data.x_m[i, valid]
        y = data.y_m[i, valid]
        dx = x - x[0]
        dy = y - y[0]
        if dx.size:
            max_abs = max(max_abs, float(np.nanmax(np.abs(dx))), float(np.nanmax(np.abs(dy))))
        ax.plot(dx, dy, lw=1.55, alpha=0.94, color=colors[i], zorder=5)
        ax.scatter(dx[0], dy[0], s=12, color="#111827", zorder=8)
        ax.scatter(dx[-1], dy[-1], s=16, color="#f97316", zorder=8)
    limit = max(max_abs * 1.2, 0.001)
    ax.set_xlim(-limit, limit)
    ax.set_ylim(-limit, limit)
    ax.set_aspect("equal", adjustable="box")
    ax.axhline(0.0, color="#94a3b8", lw=0.8, alpha=0.7)
    ax.axvline(0.0, color="#94a3b8", lw=0.8, alpha=0.7)
    ax.set_title("Local displacement zoom from release point")
    ax.set_xlabel("east-west displacement (m)")
    ax.set_ylabel("north-south displacement (m)")
    ax.grid(True, alpha=0.25)
    fig.savefig(path, dpi=170)
    plt.close(fig)


def write_metrics(metrics: dict[str, Any], output_dir: Path) -> None:
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    with (output_dir / "metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value"])
        for key, value in metrics.items():
            writer.writerow(
                [key, json.dumps(value, sort_keys=True) if isinstance(value, dict) else value]
            )


def format_distance_m(value_m: float) -> str:
    if not np.isfinite(value_m):
        return "n/a"
    if value_m >= 1000.0:
        return f"{value_m / 1000.0:.2f} km"
    if value_m >= 1.0:
        return f"{value_m:.2f} m"
    if value_m >= 0.01:
        return f"{value_m * 100.0:.2f} cm"
    return f"{value_m * 1000.0:.2f} mm"


def metric_card(label: str, value: str, note: str) -> str:
    return (
        "<div class='metric-card'>"
        f"<div class='metric-label'>{html.escape(label)}</div>"
        f"<div class='metric-value'>{html.escape(value)}</div>"
        f"<div class='metric-note'>{html.escape(note)}</div>"
        "</div>"
    )


def write_html(
    metrics: dict[str, Any],
    output_dir: Path,
    *,
    flow_configuration_cards: list[tuple[str, str, str]],
) -> None:
    card_items = [
        metric_card("Particles", str(metrics["n_particles"]), "upstream non-river release"),
        metric_card("Steps", str(metrics["max_steps"]), "maximum stored points per particle"),
        metric_card(
            "Median path",
            format_distance_m(metrics["median_travel_distance_m"]),
            f"max {format_distance_m(metrics['max_travel_distance_m'])}",
        ),
        metric_card(
            "Net shift",
            format_distance_m(metrics["median_net_displacement_m"]),
            f"max {format_distance_m(metrics['max_net_displacement_m'])}",
        ),
        metric_card(
            "Final time",
            f"{metrics['median_final_time_days']:.0f} days",
            f"max {metrics['max_final_time_days']:.0f} days",
        ),
    ]
    if "median_pore_velocity_m_year" in metrics:
        card_items.append(
            metric_card(
                "Median pore velocity",
                f"{metrics['median_pore_velocity_m_year']:.1f} m/year",
                f"p95 {metrics['p95_pore_velocity_m_year']:.1f} m/year",
            )
        )
    if "river_endpoint_count" in metrics:
        card_items.append(
            metric_card(
                "River endpoints",
                f"{metrics['river_endpoint_count']}/{metrics['endpoint_count']}",
                f"max nearest river {metrics['endpoint_nearest_river_max_m']:.0f} m",
            )
        )
    cards = "\n".join(card_items)
    flow_config = "\n".join(
        metric_card(label, value, note) for label, value, note in flow_configuration_cards
    )
    pathlines = linked_figure("figures/pathlines_topography.png", "PRT pathlines")
    velocity = (
        linked_figure(
            "figures/velocity_magnitude.png", "Pore velocity magnitude over relief and rivers"
        )
        if (output_dir / "figures" / "velocity_magnitude.png").is_file()
        else ""
    )
    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Nancon MF6-PRT pathline demo</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 28px; color: #1f2933; background: #f7f9fb; }}
    h1, h2 {{ margin-bottom: 0.35rem; }}
    h2 {{ margin-top: 2rem; border-bottom: 2px solid #d9e2ec; padding-bottom: 0.35rem; }}
    .muted {{ color: #52606d; }}
    .panel {{ background: white; border: 1px solid #d9e2ec; padding: 18px; margin: 16px 0 24px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(460px, 1fr)); gap: 18px; }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px; }}
    .metric-card {{ background: white; border: 1px solid #d9e2ec; padding: 14px; }}
    .metric-label {{ color: #52606d; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }}
    .metric-value {{ font-size: 24px; font-weight: 700; margin: 6px 0; }}
    .metric-note {{ color: #52606d; font-size: 12px; line-height: 1.35; }}
    img {{ width: min(100%, 980px); border: 1px solid #d9e2ec; margin: 8px 0 22px; background: white; }}
    .figure-link {{ display: block; color: inherit; }}
    .figure-link img {{ cursor: zoom-in; transition: box-shadow 0.15s ease, transform 0.15s ease; }}
    .figure-link:hover img {{ box-shadow: 0 6px 18px rgba(31, 41, 51, 0.18); transform: translateY(-1px); }}
    code {{ background: #eef2f7; padding: 2px 4px; }}
  </style>
</head>
<body>
  <h1>Nancon MF6-PRT pathline demo</h1>
  <p class="muted">
    Demonstration page generated from the real steady MODFLOW 6 flow plus MODFLOW 6 PRT run.
    Figures are clickable and open at full resolution.
  </p>
  <div class="panel">
    <p><b>Pathline source:</b> <code>{html.escape(str(metrics["pathline_source"]))}</code></p>
    <p><b>Source kind:</b> <code>{html.escape(str(metrics["pathline_source_kind"]))}</code></p>
    <p>
      Particle release uses the configured non-river zone: active cells are
      selected away from river-support cells, then spatially thinned when a
      maximum particle count is requested.
    </p>
    <p>
      PRT release and tracking times are reported in days after conversion from the
      MODFLOW 6 model time units. The velocity panel uses the extracted SPDIS vector
      magnitude divided by porosity to show the pore-velocity scale used by PRT.
    </p>
  </div>
  <h2>Flow Configuration</h2>
  <div class="metric-grid">{flow_config}</div>
  <h2>Summary</h2>
  <div class="metric-grid">{cards}</div>
  <h2>Pathlines</h2>
  {pathlines}
  <h2>Velocity Field</h2>
  {velocity}
</body>
</html>
"""
    (output_dir / "index.html").write_text(body, encoding="utf-8")


def build_report(
    *,
    workspace: Path,
    zarr_zip: Path | None,
    track_csv: Path | None,
    prefer_track_csv: bool,
    mesh_bundle: Path,
    config_path: Path,
    output_dir: Path,
    porosity: float,
) -> Path:
    mesh = load_nancon_mesh(mesh_bundle)
    csv_path = track_csv
    if csv_path is None and prefer_track_csv:
        csv_path = _latest_track_csv(workspace)
    if csv_path is not None:
        data = read_prt_pathlines_from_track_csv(csv_path)
    else:
        zarr_path = zarr_zip or _latest_zarr_zip(workspace)
        data = read_prt_pathlines_from_zarr(zarr_path)
    metrics = compute_metrics(data, porosity=porosity)
    metrics.update(compute_river_endpoint_metrics(mesh, data))
    if output_dir.exists():
        import shutil

        shutil.rmtree(output_dir)
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    plot_pathlines_over_topography(mesh, data, figures_dir / "pathlines_topography.png")
    plot_velocity_magnitude(mesh, data, figures_dir / "velocity_magnitude.png", porosity=porosity)
    write_metrics(metrics, output_dir)
    write_html(
        metrics,
        output_dir,
        flow_configuration_cards=read_flow_configuration_cards(config_path),
    )
    return output_dir / "index.html"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a Nancon MF6-PRT pathline HTML page.")
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--zarr-zip", type=Path, default=None)
    parser.add_argument("--track-csv", type=Path, default=None)
    parser.add_argument(
        "--prefer-track-csv",
        action="store_true",
        help="Read the latest *.trk.csv in the workspace directly when available.",
    )
    parser.add_argument("--mesh-bundle", type=Path, default=DEFAULT_MESH_BUNDLE)
    parser.add_argument("--config", type=Path, default=DEFAULT_RUN_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--porosity", type=float, default=DEFAULT_POROSITY)
    args = parser.parse_args()
    index = build_report(
        workspace=args.workspace,
        zarr_zip=args.zarr_zip,
        track_csv=args.track_csv,
        prefer_track_csv=args.prefer_track_csv,
        mesh_bundle=args.mesh_bundle,
        config_path=args.config,
        output_dir=args.output_dir,
        porosity=args.porosity,
    )
    print(f"Open {index}")


if __name__ == "__main__":
    main()
