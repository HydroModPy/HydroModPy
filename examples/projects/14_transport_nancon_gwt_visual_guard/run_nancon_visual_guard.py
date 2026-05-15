from __future__ import annotations

import argparse
import csv
import html
import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import LinearSegmentedColormap, Normalize, PowerNorm
from scipy.special import erfc

EXAMPLE_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = EXAMPLE_ROOT / "outputs"
DEFAULT_MESH_BUNDLE = (
    EXAMPLE_ROOT.parent
    / "09_comparison_workflow"
    / "outputs"
    / "nancon_transient_seasonal_hydrography"
    / "workspace_mf6"
    / "mesh"
    / "mesh_catchment_bundle"
)

OUTLET_XY_L93_M = np.array([389285.91, 6816518.749], dtype=float)

CONCENTRATION_CMAP = LinearSegmentedColormap.from_list(
    "concentration_white_zero",
    ["#ffffff", "#d8f3ff", "#73c8d2", "#2d8fbe", "#2f4b9a", "#7b1f86", "#c51b29"],
)


@dataclass(frozen=True)
class NanconMesh:
    bundle_dir: Path
    origin_xy_m: np.ndarray
    vertices_xy_m: np.ndarray
    polygons_m: list[np.ndarray]
    polygons_km: list[np.ndarray]
    centroids_m: np.ndarray
    centroids_km: np.ndarray
    areas_m2: np.ndarray
    z_top_m: np.ndarray
    z_bottom_m: np.ndarray
    river_cells: np.ndarray
    boundary_cells: np.ndarray
    river_segments_m: list[np.ndarray]
    river_segments_km: list[np.ndarray]
    outlet_m: np.ndarray
    outlet_km: np.ndarray

    @property
    def n_cells(self) -> int:
        return int(self.centroids_m.shape[0])

    @property
    def extent_km(self) -> tuple[float, float, float, float]:
        x = self.vertices_xy_m[:, 0] - self.origin_xy_m[0]
        y = self.vertices_xy_m[:, 1] - self.origin_xy_m[1]
        return (
            float(np.min(x) / 1000.0),
            float(np.max(x) / 1000.0),
            float(np.min(y) / 1000.0),
            float(np.max(y) / 1000.0),
        )


@dataclass(frozen=True)
class NanconCase:
    name: str
    title: str
    description: str
    source_mode: str
    source_river_distance_quantile: float
    source_concentration: float
    velocity_m_per_day: float
    target_cell_peclet: float
    n_times: int
    duration_factor: float
    pulse_duration_fraction: float
    longitudinal_sigma_m: float
    transverse_sigma_m: float
    profile_half_width_m: float


@dataclass(frozen=True)
class CaseResult:
    case: NanconCase
    mesh: NanconMesh
    times_days: np.ndarray
    source_m: np.ndarray
    source_km: np.ndarray
    direction: np.ndarray
    transverse_direction: np.ndarray
    s_coord_m: np.ndarray
    r_coord_m: np.ndarray
    path_length_m: float
    diffusion_m2_per_day: float
    head_m: np.ndarray
    cell_peclet: np.ndarray
    concentration: np.ndarray
    probe_points_m: dict[str, np.ndarray]
    probe_indices: dict[str, np.ndarray]
    signatures: dict[str, Any]


def default_cases() -> list[NanconCase]:
    return [
        NanconCase(
            name="nancon_01_internal_pulse",
            title="Nancon homogeneous transport - internal pulse",
            description=(
                "A compact concentration pulse is initialized inside the Nancon domain, "
                "away from the upstream boundary, then advected toward the outlet on the "
                "existing triangular watershed mesh."
            ),
            source_mode="internal_pulse",
            source_river_distance_quantile=0.72,
            source_concentration=1.0,
            velocity_m_per_day=1.2,
            target_cell_peclet=20.0,
            n_times=81,
            duration_factor=1.18,
            pulse_duration_fraction=0.0,
            longitudinal_sigma_m=280.0,
            transverse_sigma_m=360.0,
            profile_half_width_m=900.0,
        ),
        NanconCase(
            name="nancon_02_upstream_pulse",
            title="Nancon homogeneous transport - upstream finite pulse",
            description=(
                "A finite-duration upstream source produces a moving front and tail. "
                "This is a visual boundary-condition guard for later MF6-GWT runs."
            ),
            source_mode="upstream_pulse",
            source_river_distance_quantile=0.94,
            source_concentration=1.0,
            velocity_m_per_day=1.2,
            target_cell_peclet=20.0,
            n_times=81,
            duration_factor=1.12,
            pulse_duration_fraction=0.18,
            longitudinal_sigma_m=220.0,
            transverse_sigma_m=430.0,
            profile_half_width_m=950.0,
        ),
        NanconCase(
            name="nancon_03_constant_upstream",
            title="Nancon homogeneous transport - constant upstream source",
            description=(
                "A constant upstream concentration source is maintained long enough to "
                "inspect the breakthrough shape and outlet arrival on the Nancon mesh."
            ),
            source_mode="constant_upstream",
            source_river_distance_quantile=0.94,
            source_concentration=1.0,
            velocity_m_per_day=1.2,
            target_cell_peclet=20.0,
            n_times=81,
            duration_factor=1.12,
            pulse_duration_fraction=1.0,
            longitudinal_sigma_m=220.0,
            transverse_sigma_m=430.0,
            profile_half_width_m=950.0,
        ),
    ]


def load_nancon_mesh(bundle_dir: Path) -> NanconMesh:
    required = ["nodes.csv", "cells.csv", "edges.csv"]
    missing = [name for name in required if not (bundle_dir / name).exists()]
    if missing:
        missing_list = ", ".join(missing)
        raise FileNotFoundError(
            f"Missing Nancon mesh bundle files in {bundle_dir}: {missing_list}. "
            "Run the Nancon comparison workflow first or pass --mesh-bundle."
        )

    nodes = pd.read_csv(bundle_dir / "nodes.csv")
    cells = pd.read_csv(bundle_dir / "cells.csv").sort_values("cell_id").reset_index(drop=True)
    edges = pd.read_csv(bundle_dir / "edges.csv")

    node_ids = nodes["node_id"].to_numpy(dtype=int)
    node_xy = nodes[["x", "y"]].to_numpy(dtype=float)
    id_to_node_pos = {int(node_id): idx for idx, node_id in enumerate(node_ids)}
    origin_xy = np.array([float(np.min(node_xy[:, 0])), float(np.min(node_xy[:, 1]))])

    polygons_m: list[np.ndarray] = []
    for row in cells[["n0", "n1", "n2", "n3"]].itertuples(index=False, name=None):
        ids = [int(value) for value in row if not pd.isna(value)]
        polygon = np.vstack([node_xy[id_to_node_pos[node_id]] - origin_xy for node_id in ids])
        polygons_m.append(polygon)
    polygons_km = [polygon / 1000.0 for polygon in polygons_m]

    vertices_xy_m = node_xy.copy()
    centroids_abs = cells[["centroid_x", "centroid_y"]].to_numpy(dtype=float)
    centroids_m = centroids_abs - origin_xy
    centroids_km = centroids_m / 1000.0
    areas_m2 = cells["area_m2"].to_numpy(dtype=float)
    z_top_m = cells["z_top_mean"].to_numpy(dtype=float)
    z_bottom_m = cells["z_bottom_mean"].to_numpy(dtype=float)

    cell_ids = cells["cell_id"].to_numpy(dtype=int)
    id_to_cell_pos = {int(cell_id): idx for idx, cell_id in enumerate(cell_ids)}
    river_cells = np.zeros(cells.shape[0], dtype=bool)
    boundary_cells = np.zeros(cells.shape[0], dtype=bool)
    river_segments_m: list[np.ndarray] = []
    for edge in edges.itertuples(index=False):
        if str(edge.edge_kind) == "boundary":
            _mark_cell(boundary_cells, id_to_cell_pos, edge.cell_a)
            _mark_cell(boundary_cells, id_to_cell_pos, edge.cell_b)
        if bool(edge.is_river):
            _mark_cell(river_cells, id_to_cell_pos, edge.cell_a)
            _mark_cell(river_cells, id_to_cell_pos, edge.cell_b)
            a = int(edge.node_a)
            b = int(edge.node_b)
            river_segments_m.append(
                np.vstack(
                    [
                        node_xy[id_to_node_pos[a]] - origin_xy,
                        node_xy[id_to_node_pos[b]] - origin_xy,
                    ]
                )
            )
    river_segments_km = [segment / 1000.0 for segment in river_segments_m]
    outlet_m = OUTLET_XY_L93_M - origin_xy

    return NanconMesh(
        bundle_dir=bundle_dir,
        origin_xy_m=origin_xy,
        vertices_xy_m=vertices_xy_m,
        polygons_m=polygons_m,
        polygons_km=polygons_km,
        centroids_m=centroids_m,
        centroids_km=centroids_km,
        areas_m2=areas_m2,
        z_top_m=z_top_m,
        z_bottom_m=z_bottom_m,
        river_cells=river_cells,
        boundary_cells=boundary_cells,
        river_segments_m=river_segments_m,
        river_segments_km=river_segments_km,
        outlet_m=outlet_m,
        outlet_km=outlet_m / 1000.0,
    )


def _mark_cell(mask: np.ndarray, id_to_cell_pos: dict[int, int], value: Any) -> None:
    if pd.isna(value):
        return
    pos = id_to_cell_pos.get(int(value))
    if pos is not None:
        mask[pos] = True


def run_case(case: NanconCase, mesh: NanconMesh) -> CaseResult:
    source_m = select_source_point(mesh, case.source_river_distance_quantile)
    direction = mesh.outlet_m - source_m
    path_length_m = float(np.linalg.norm(direction))
    if path_length_m <= 0.0:
        raise ValueError("Invalid Nancon source/outlet geometry.")
    direction = direction / path_length_m
    transverse_direction = np.array([-direction[1], direction[0]])
    offsets = mesh.centroids_m - source_m
    s_coord_m = offsets @ direction
    r_coord_m = offsets @ transverse_direction

    median_cell_length = float(np.sqrt(np.median(mesh.areas_m2)))
    diffusion_m2_per_day = case.velocity_m_per_day * median_cell_length / case.target_cell_peclet
    duration_days = case.duration_factor * path_length_m / case.velocity_m_per_day
    times_days = np.linspace(0.0, duration_days, case.n_times)

    head_m = synthetic_head_field(mesh, source_m, direction, s_coord_m)
    cell_peclet = case.velocity_m_per_day * np.sqrt(mesh.areas_m2) / diffusion_m2_per_day
    concentration = simulate_concentration(
        case,
        times_days,
        s_coord_m,
        r_coord_m,
        path_length_m,
        diffusion_m2_per_day,
    )
    probe_points_m = build_probe_points(source_m, mesh.outlet_m)
    probe_indices = {
        name: cells_near_point(mesh, point, radius_m=420.0)
        for name, point in probe_points_m.items()
    }
    signatures = build_signatures(
        case,
        mesh,
        times_days,
        source_m,
        direction,
        s_coord_m,
        r_coord_m,
        path_length_m,
        diffusion_m2_per_day,
        head_m,
        cell_peclet,
        concentration,
        probe_indices,
    )

    return CaseResult(
        case=case,
        mesh=mesh,
        times_days=times_days,
        source_m=source_m,
        source_km=source_m / 1000.0,
        direction=direction,
        transverse_direction=transverse_direction,
        s_coord_m=s_coord_m,
        r_coord_m=r_coord_m,
        path_length_m=path_length_m,
        diffusion_m2_per_day=diffusion_m2_per_day,
        head_m=head_m,
        cell_peclet=cell_peclet,
        concentration=concentration,
        probe_points_m=probe_points_m,
        probe_indices=probe_indices,
        signatures=signatures,
    )


def select_source_point(mesh: NanconMesh, river_distance_quantile: float) -> np.ndarray:
    river_idx = np.where(mesh.river_cells)[0]
    if river_idx.size == 0:
        river_idx = np.arange(mesh.n_cells)
    distances = np.linalg.norm(mesh.centroids_m[river_idx] - mesh.outlet_m, axis=1)
    target = float(np.quantile(distances, river_distance_quantile))
    chosen = river_idx[int(np.argmin(np.abs(distances - target)))]
    return mesh.centroids_m[chosen].copy()


def synthetic_head_field(
    mesh: NanconMesh,
    source_m: np.ndarray,
    direction: np.ndarray,
    s_coord_m: np.ndarray,
) -> np.ndarray:
    topographic_component = 0.22 * (mesh.z_top_m - float(np.mean(mesh.z_top_m)))
    upstream_component = 0.0045 * (float(np.max(s_coord_m)) - s_coord_m)
    source_bump = 1.4 * np.exp(
        -0.5 * (np.linalg.norm(mesh.centroids_m - source_m, axis=1) / 1200.0) ** 2
    )
    return 125.0 + topographic_component + upstream_component + source_bump


def simulate_concentration(
    case: NanconCase,
    times_days: np.ndarray,
    s_coord_m: np.ndarray,
    r_coord_m: np.ndarray,
    path_length_m: float,
    diffusion_m2_per_day: float,
) -> np.ndarray:
    rows = []
    for time_day in times_days:
        if case.source_mode == "internal_pulse":
            conc = internal_gaussian_pulse(
                case,
                time_day,
                s_coord_m,
                r_coord_m,
                diffusion_m2_per_day,
            )
        elif case.source_mode == "upstream_pulse":
            pulse_days = max(
                case.pulse_duration_fraction * path_length_m / case.velocity_m_per_day, 1.0
            )
            conc = upstream_front(
                case,
                time_day,
                s_coord_m,
                r_coord_m,
                diffusion_m2_per_day,
            )
            if time_day > pulse_days:
                conc -= upstream_front(
                    case,
                    time_day - pulse_days,
                    s_coord_m,
                    r_coord_m,
                    diffusion_m2_per_day,
                )
        elif case.source_mode == "constant_upstream":
            conc = upstream_front(
                case,
                time_day,
                s_coord_m,
                r_coord_m,
                diffusion_m2_per_day,
            )
        else:
            raise ValueError(f"Unknown source mode: {case.source_mode}")
        rows.append(np.clip(conc, 0.0, case.source_concentration))
    return np.vstack(rows)


def internal_gaussian_pulse(
    case: NanconCase,
    time_day: float,
    s_coord_m: np.ndarray,
    r_coord_m: np.ndarray,
    diffusion_m2_per_day: float,
) -> np.ndarray:
    longitudinal_var = case.longitudinal_sigma_m**2 + 2.0 * diffusion_m2_per_day * time_day
    transverse_var = case.transverse_sigma_m**2 + 0.55 * diffusion_m2_per_day * time_day
    amplitude = (
        case.source_concentration
        * case.longitudinal_sigma_m
        * case.transverse_sigma_m
        / math.sqrt(longitudinal_var * transverse_var)
    )
    center_s = case.velocity_m_per_day * time_day
    exponent = -0.5 * (
        ((s_coord_m - center_s) ** 2) / longitudinal_var + (r_coord_m**2) / transverse_var
    )
    return amplitude * np.exp(exponent)


def upstream_front(
    case: NanconCase,
    time_day: float,
    s_coord_m: np.ndarray,
    r_coord_m: np.ndarray,
    diffusion_m2_per_day: float,
) -> np.ndarray:
    if time_day <= 0.0:
        return np.zeros_like(s_coord_m)
    denom = max(math.sqrt(4.0 * diffusion_m2_per_day * time_day), 1.0e-12)
    longitudinal = 0.5 * erfc((s_coord_m - case.velocity_m_per_day * time_day) / denom)
    transverse_var = case.transverse_sigma_m**2 + 0.55 * diffusion_m2_per_day * time_day
    transverse = np.exp(-0.5 * (r_coord_m**2) / transverse_var)
    longitudinal = np.where(s_coord_m >= -300.0, longitudinal, 0.0)
    return case.source_concentration * longitudinal * transverse


def build_probe_points(source_m: np.ndarray, outlet_m: np.ndarray) -> dict[str, np.ndarray]:
    return {
        "source": source_m,
        "quarter": source_m + 0.25 * (outlet_m - source_m),
        "middle": source_m + 0.50 * (outlet_m - source_m),
        "downstream": source_m + 0.75 * (outlet_m - source_m),
        "outlet": outlet_m,
    }


def cells_near_point(mesh: NanconMesh, point_m: np.ndarray, radius_m: float) -> np.ndarray:
    distances = np.linalg.norm(mesh.centroids_m - point_m, axis=1)
    idx = np.where(distances <= radius_m)[0]
    if idx.size:
        return idx
    return np.array([int(np.argmin(distances))], dtype=int)


def build_signatures(
    case: NanconCase,
    mesh: NanconMesh,
    times_days: np.ndarray,
    source_m: np.ndarray,
    direction: np.ndarray,
    s_coord_m: np.ndarray,
    r_coord_m: np.ndarray,
    path_length_m: float,
    diffusion_m2_per_day: float,
    head_m: np.ndarray,
    cell_peclet: np.ndarray,
    concentration: np.ndarray,
    probe_indices: dict[str, np.ndarray],
) -> dict[str, Any]:
    area = mesh.areas_m2
    source_abs = source_m + mesh.origin_xy_m
    rows = []
    for time_day, conc in zip(times_days, concentration, strict=True):
        moments = plume_moments(mesh, conc, s_coord_m)
        probe_values = {
            f"probe_{name}_mean": _round(float(np.average(conc[idx], weights=area[idx])))
            for name, idx in probe_indices.items()
        }
        river_mass = float(np.sum(conc[mesh.river_cells] * area[mesh.river_cells]))
        total_mass = max(moments["mass"], 1.0e-30)
        rows.append(
            {
                "time_days": _round(float(time_day), 3),
                "time_years": _round(float(time_day) / 365.25, 4),
                "mass": _round(moments["mass"]),
                "center_s_m": _round(moments["center_s_m"]),
                "center_fraction_to_outlet": _round(moments["center_s_m"] / path_length_m),
                "longitudinal_width_m": _round(moments["width_s_m"]),
                "max_concentration": _round(float(np.max(conc))),
                "mean_concentration": _round(float(np.average(conc, weights=area))),
                "river_exposure_fraction": _round(river_mass / total_mass),
                **probe_values,
            }
        )

    final = rows[-1]
    return {
        "case": {
            "name": case.name,
            "source_mode": case.source_mode,
            "source_concentration": case.source_concentration,
            "velocity_m_per_day": case.velocity_m_per_day,
            "target_cell_peclet": case.target_cell_peclet,
            "duration_days": _round(float(times_days[-1]), 3),
            "duration_years": _round(float(times_days[-1]) / 365.25, 3),
            "n_output_times": int(times_days.size),
            "pulse_duration_days": _round(
                case.pulse_duration_fraction * path_length_m / case.velocity_m_per_day,
                3,
            ),
        },
        "nancon_context": {
            "mesh_bundle": str(mesh.bundle_dir),
            "source_x_l93_m": _round(float(source_abs[0]), 3),
            "source_y_l93_m": _round(float(source_abs[1]), 3),
            "outlet_x_l93_m": _round(float(OUTLET_XY_L93_M[0]), 3),
            "outlet_y_l93_m": _round(float(OUTLET_XY_L93_M[1]), 3),
            "path_length_m": _round(path_length_m, 3),
            "unit_direction_x": _round(float(direction[0])),
            "unit_direction_y": _round(float(direction[1])),
        },
        "mesh": {
            "n_cells": mesh.n_cells,
            "n_river_cells": int(np.sum(mesh.river_cells)),
            "n_boundary_cells": int(np.sum(mesh.boundary_cells)),
            "area_total_km2": _round(float(np.sum(area)) / 1.0e6, 3),
            "cell_area_m2_min": _round(float(np.min(area)), 3),
            "cell_area_m2_median": _round(float(np.median(area)), 3),
            "cell_area_m2_max": _round(float(np.max(area)), 3),
            "cell_area_ratio_max_min": _round(float(np.max(area) / np.min(area)), 3),
            "z_top_min_m": _round(float(np.min(mesh.z_top_m)), 3),
            "z_top_max_m": _round(float(np.max(mesh.z_top_m)), 3),
        },
        "flow_transport_numbers": {
            "hydraulic_conductivity_reference_m_per_s": 5.0e-5,
            "porosity_reference": 0.30,
            "visual_pore_velocity_m_per_day": case.velocity_m_per_day,
            "diffusion_m2_per_day": _round(diffusion_m2_per_day),
            "peclet_min": _round(float(np.min(cell_peclet)), 3),
            "peclet_mean": _round(float(np.mean(cell_peclet)), 3),
            "peclet_median": _round(float(np.median(cell_peclet)), 3),
            "peclet_max": _round(float(np.max(cell_peclet)), 3),
            "head_min_m": _round(float(np.min(head_m)), 3),
            "head_max_m": _round(float(np.max(head_m)), 3),
        },
        "final": final,
        "time_signatures": rows,
    }


def plume_moments(mesh: NanconMesh, conc: np.ndarray, s_coord_m: np.ndarray) -> dict[str, float]:
    weights = np.clip(conc, 0.0, None) * mesh.areas_m2
    mass = float(np.sum(weights))
    if mass <= 1.0e-30:
        return {"mass": 0.0, "center_s_m": 0.0, "width_s_m": 0.0}
    center_s = float(np.sum(s_coord_m * weights) / mass)
    width_s = float(np.sqrt(np.sum(((s_coord_m - center_s) ** 2) * weights) / mass))
    return {"mass": mass, "center_s_m": center_s, "width_s_m": width_s}


def render_case_report(result: CaseResult, output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    write_signatures(result, output_dir)

    plot_context(result, figures_dir / "domain_context.png")
    plot_cell_field(
        result,
        result.mesh.z_top_m,
        "Nancon surface elevation (m)",
        figures_dir / "topography.png",
        cmap="terrain",
    )
    plot_mesh_overview(result, figures_dir / "mesh_overview.png")
    plot_flow_field(result, figures_dir / "flow_head_direction.png")
    plot_cell_field(
        result,
        result.cell_peclet,
        "Cell Peclet number",
        figures_dir / "cell_peclet.png",
        cmap="magma",
    )
    plot_concentration_snapshots(result, figures_dir / "concentration_snapshots.png")
    plot_concentration_profiles(result, figures_dir / "concentration_profiles.png")
    plot_probe_breakthrough(result, figures_dir / "probe_breakthrough.png")
    plot_plume_evolution(result, figures_dir / "plume_evolution.png")
    plot_network_exposure(result, figures_dir / "network_exposure.png")
    write_case_html(result, output_dir)


def write_signatures(result: CaseResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "signatures.json").write_text(
        json.dumps(result.signatures, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    rows = result.signatures["time_signatures"]
    with (output_dir / "signatures.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot_context(result: CaseResult, path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(15.5, 7.2), constrained_layout=True)
    ax = axes[0]
    collection = PolyCollection(
        result.mesh.polygons_km,
        array=result.mesh.z_top_m,
        cmap="terrain",
        edgecolors="#27343a",
        linewidths=0.08,
    )
    ax.add_collection(collection)
    add_rivers(ax, result)
    add_markers(ax, result)
    decorate_map_axis(ax, result, "Watershed, river network, source and probes")
    cbar = fig.colorbar(collection, ax=ax, shrink=0.78)
    cbar.set_label("surface elevation (m)", fontsize=12)
    cbar.ax.tick_params(labelsize=11)

    ax = axes[1]
    head_norm = Normalize(vmin=float(np.min(result.head_m)), vmax=float(np.max(result.head_m)))
    collection = PolyCollection(
        result.mesh.polygons_km,
        array=result.head_m,
        cmap="Blues",
        norm=head_norm,
        edgecolors="#27343a",
        linewidths=0.06,
    )
    ax.add_collection(collection)
    add_rivers(ax, result)
    add_flow_arrows(ax, result, stride=220)
    add_markers(ax, result)
    decorate_map_axis(ax, result, "Synthetic head and visual transport direction")
    cbar = fig.colorbar(collection, ax=ax, shrink=0.78)
    cbar.set_label("head proxy (m)", fontsize=12)
    cbar.ax.tick_params(labelsize=11)
    fig.savefig(path, dpi=170)
    plt.close(fig)


def plot_mesh_overview(result: CaseResult, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11.5, 10.0), constrained_layout=True)
    base = PolyCollection(
        result.mesh.polygons_km,
        facecolors="#f8fafc",
        edgecolors="#263238",
        linewidths=0.11,
    )
    ax.add_collection(base)
    river_polys = [result.mesh.polygons_km[idx] for idx in np.where(result.mesh.river_cells)[0]]
    if river_polys:
        river_cells = PolyCollection(
            river_polys,
            facecolors="#b9e6ff",
            edgecolors="#1f78b4",
            linewidths=0.16,
            alpha=0.92,
        )
        ax.add_collection(river_cells)
    add_rivers(ax, result, linewidth=1.8)
    add_markers(ax, result)
    decorate_map_axis(
        ax,
        result,
        f"Triangular DISV mesh ({result.mesh.n_cells} cells) and river-adjacent cells",
    )
    fig.savefig(path, dpi=175)
    plt.close(fig)


def plot_cell_field(
    result: CaseResult,
    values: np.ndarray,
    title: str,
    path: Path,
    *,
    cmap: str | LinearSegmentedColormap,
) -> None:
    fig, ax = plt.subplots(figsize=(11.5, 10.0), constrained_layout=True)
    collection = PolyCollection(
        result.mesh.polygons_km,
        array=np.asarray(values, dtype=float),
        cmap=cmap,
        edgecolors="#263238",
        linewidths=0.07,
    )
    ax.add_collection(collection)
    add_rivers(ax, result)
    add_markers(ax, result)
    decorate_map_axis(ax, result, title)
    cbar = fig.colorbar(collection, ax=ax, shrink=0.80)
    cbar.set_label(title, fontsize=13)
    cbar.ax.tick_params(labelsize=12)
    fig.savefig(path, dpi=175)
    plt.close(fig)


def plot_flow_field(result: CaseResult, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11.5, 10.0), constrained_layout=True)
    collection = PolyCollection(
        result.mesh.polygons_km,
        array=result.head_m,
        cmap="Blues",
        edgecolors="#263238",
        linewidths=0.06,
    )
    ax.add_collection(collection)
    add_rivers(ax, result)
    add_flow_arrows(ax, result, stride=155)
    add_markers(ax, result)
    decorate_map_axis(ax, result, "Head proxy and advective direction")
    cbar = fig.colorbar(collection, ax=ax, shrink=0.80)
    cbar.set_label("head proxy (m)", fontsize=13)
    cbar.ax.tick_params(labelsize=12)
    fig.savefig(path, dpi=175)
    plt.close(fig)


def plot_concentration_snapshots(result: CaseResult, path: Path) -> None:
    indices = selected_indices(result.times_days.size, max_count=9)
    vmax = float(np.percentile(result.concentration[result.concentration > 0.0], 99.4))
    vmax = max(vmax, 1.0e-8)
    norm = PowerNorm(gamma=0.52, vmin=0.0, vmax=vmax)
    fig, axes = plt.subplots(3, 3, figsize=(15.6, 15.0), constrained_layout=True)
    axes_flat = list(axes.ravel())
    last_collection = None
    for ax, idx in zip(axes_flat, indices, strict=False):
        conc = result.concentration[idx]
        last_collection = PolyCollection(
            result.mesh.polygons_km,
            array=conc,
            cmap=CONCENTRATION_CMAP,
            norm=norm,
            edgecolors="#28353c",
            linewidths=0.045,
        )
        ax.add_collection(last_collection)
        add_rivers(ax, result, linewidth=0.75, alpha=0.65)
        add_markers(ax, result, probe_labels=False)
        time_years = result.times_days[idx] / 365.25
        decorate_map_axis(
            ax,
            result,
            f"t = {result.times_days[idx]:.0f} d ({time_years:.1f} yr)",
            compact=True,
        )
    for ax in axes_flat[len(indices) :]:
        ax.axis("off")
    cbar = fig.colorbar(last_collection, ax=axes_flat, shrink=0.72, location="right")
    cbar.set_label("concentration", fontsize=16)
    cbar.ax.tick_params(labelsize=14)
    fig.savefig(path, dpi=170)
    plt.close(fig)


def plot_concentration_profiles(result: CaseResult, path: Path) -> None:
    profile_indices = selected_indices(result.times_days.size, max_count=7)
    fig, ax = plt.subplots(figsize=(12.8, 6.8), constrained_layout=True)
    for idx in profile_indices:
        s_centers, profile = longitudinal_profile(result, result.concentration[idx])
        ax.plot(
            s_centers / 1000.0,
            profile,
            linewidth=2.2,
            label=f"{result.times_days[idx] / 365.25:.1f} yr",
        )
    ax.axvline(result.path_length_m / 1000.0, color="#d62728", linestyle="--", linewidth=1.8)
    ax.set_xlabel("distance from source along visual flow axis (km)", fontsize=13)
    ax.set_ylabel("mean concentration in corridor", fontsize=13)
    ax.set_title("Longitudinal concentration profiles", fontsize=15)
    ax.grid(True, alpha=0.25)
    ax.tick_params(labelsize=12)
    ax.legend(ncol=4, fontsize=11)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def longitudinal_profile(result: CaseResult, conc: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    max_s = max(float(np.max(result.s_coord_m)), result.path_length_m) * 1.05
    bins = np.linspace(-400.0, max_s, 110)
    centers = 0.5 * (bins[:-1] + bins[1:])
    profile = np.zeros_like(centers)
    corridor = np.abs(result.r_coord_m) <= result.case.profile_half_width_m
    for idx in range(centers.size):
        mask = corridor & (result.s_coord_m >= bins[idx]) & (result.s_coord_m < bins[idx + 1])
        if np.any(mask):
            profile[idx] = float(np.average(conc[mask], weights=result.mesh.areas_m2[mask]))
    return centers, profile


def plot_probe_breakthrough(result: CaseResult, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(12.8, 6.8), constrained_layout=True)
    for name, indices in result.probe_indices.items():
        values = [
            float(np.average(row[indices], weights=result.mesh.areas_m2[indices]))
            for row in result.concentration
        ]
        ax.plot(result.times_days / 365.25, values, linewidth=2.3, label=name)
    ax.set_xlabel("simulation time (years)", fontsize=13)
    ax.set_ylabel("local mean concentration", fontsize=13)
    ax.set_title("Breakthrough at source-to-outlet probes", fontsize=15)
    ax.grid(True, alpha=0.25)
    ax.tick_params(labelsize=12)
    ax.legend(ncol=3, fontsize=11)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_plume_evolution(result: CaseResult, path: Path) -> None:
    rows = result.signatures["time_signatures"]
    time_years = np.array([row["time_years"] for row in rows], dtype=float)
    center_km = np.array([row["center_s_m"] for row in rows], dtype=float) / 1000.0
    width_km = np.array([row["longitudinal_width_m"] for row in rows], dtype=float) / 1000.0
    mass = np.array([row["mass"] for row in rows], dtype=float)

    fig, axes = plt.subplots(2, 1, figsize=(12.8, 8.6), sharex=True, constrained_layout=True)
    axes[0].plot(time_years, center_km, linewidth=2.6, color="#1f78b4", label="mean position")
    axes[0].fill_between(
        time_years,
        np.maximum(center_km - width_km, 0.0),
        center_km + width_km,
        color="#a6cee3",
        alpha=0.55,
        label="one longitudinal std",
    )
    axes[0].axhline(result.path_length_m / 1000.0, color="#d62728", linestyle="--", linewidth=1.7)
    axes[0].set_ylabel("distance from source (km)", fontsize=13)
    axes[0].set_title("Plume center and longitudinal spread", fontsize=15)
    axes[0].grid(True, alpha=0.25)
    axes[0].legend(fontsize=11)

    axes[1].plot(
        time_years, mass / max(float(np.max(mass)), 1.0e-30), linewidth=2.5, color="#2ca25f"
    )
    axes[1].set_xlabel("simulation time (years)", fontsize=13)
    axes[1].set_ylabel("normalized aquifer mass", fontsize=13)
    axes[1].set_title("Mass remaining inside the modeled domain", fontsize=15)
    axes[1].grid(True, alpha=0.25)
    for ax in axes:
        ax.tick_params(labelsize=12)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_network_exposure(result: CaseResult, path: Path) -> None:
    rows = result.signatures["time_signatures"]
    time_years = np.array([row["time_years"] for row in rows], dtype=float)
    exposure = np.array([row["river_exposure_fraction"] for row in rows], dtype=float)
    outlet = np.array([row["probe_outlet_mean"] for row in rows], dtype=float)

    fig, axes = plt.subplots(1, 2, figsize=(14.4, 6.6), constrained_layout=True)
    river_mask = np.where(result.mesh.river_cells, 1.0, 0.0)
    collection = PolyCollection(
        result.mesh.polygons_km,
        array=river_mask,
        cmap=LinearSegmentedColormap.from_list("river_cells", ["#f8fafc", "#1f78b4"]),
        edgecolors="#263238",
        linewidths=0.06,
    )
    axes[0].add_collection(collection)
    add_rivers(axes[0], result, linewidth=1.8)
    add_markers(axes[0], result, probe_labels=False)
    decorate_map_axis(axes[0], result, "Cells adjacent to the Nancon network")

    axes[1].plot(time_years, exposure, linewidth=2.5, label="river exposure fraction")
    axes[1].plot(time_years, outlet, linewidth=2.5, label="outlet concentration")
    axes[1].set_xlabel("simulation time (years)", fontsize=13)
    axes[1].set_ylabel("dimensionless", fontsize=13)
    axes[1].set_title("Network exposure and outlet arrival", fontsize=15)
    axes[1].grid(True, alpha=0.25)
    axes[1].tick_params(labelsize=12)
    axes[1].legend(fontsize=11)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def add_rivers(
    ax: Any,
    result: CaseResult,
    *,
    linewidth: float = 1.15,
    alpha: float = 0.90,
) -> None:
    if not result.mesh.river_segments_km:
        return
    lines = LineCollection(
        result.mesh.river_segments_km,
        colors="#0077b6",
        linewidths=linewidth,
        alpha=alpha,
        zorder=5,
    )
    ax.add_collection(lines)


def add_markers(result_ax: Any, result: CaseResult, *, probe_labels: bool = True) -> None:
    ax = result_ax
    ax.scatter(
        [result.source_km[0]],
        [result.source_km[1]],
        marker="*",
        s=180,
        color="#c51b29",
        edgecolor="white",
        linewidth=0.9,
        zorder=8,
        label="source",
    )
    ax.scatter(
        [result.mesh.outlet_km[0]],
        [result.mesh.outlet_km[1]],
        marker="v",
        s=95,
        color="#111827",
        edgecolor="white",
        linewidth=0.8,
        zorder=8,
        label="outlet",
    )
    if probe_labels:
        for name, point_m in result.probe_points_m.items():
            point = point_m / 1000.0
            ax.scatter(
                [point[0]],
                [point[1]],
                marker="o",
                s=36,
                color="#ffb703",
                edgecolor="#2b2d42",
                linewidth=0.6,
                zorder=7,
            )
            if name not in {"source", "outlet"}:
                ax.text(
                    point[0] + 0.06,
                    point[1] + 0.06,
                    name,
                    fontsize=9,
                    color="#1f2933",
                    zorder=9,
                )


def add_flow_arrows(result_ax: Any, result: CaseResult, *, stride: int) -> None:
    ax = result_ax
    order = np.argsort(result.s_coord_m)
    selected = order[:: max(stride, 1)]
    points = result.mesh.centroids_km[selected]
    direction = result.direction
    ax.quiver(
        points[:, 0],
        points[:, 1],
        np.full(points.shape[0], direction[0]),
        np.full(points.shape[0], direction[1]),
        angles="xy",
        scale_units="xy",
        scale=1.8,
        width=0.0042,
        color="#111827",
        alpha=0.74,
        zorder=7,
    )


def decorate_map_axis(
    ax: Any,
    result: CaseResult,
    title: str,
    *,
    compact: bool = False,
) -> None:
    xmin, xmax, ymin, ymax = result.mesh.extent_km
    pad_x = 0.03 * max(xmax - xmin, 1.0)
    pad_y = 0.03 * max(ymax - ymin, 1.0)
    ax.set_xlim(xmin - pad_x, xmax + pad_x)
    ax.set_ylim(ymin - pad_y, ymax + pad_y)
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=12 if compact else 15)
    ax.set_xlabel("x local L93 (km)", fontsize=10 if compact else 12)
    ax.set_ylabel("y local L93 (km)", fontsize=10 if compact else 12)
    ax.tick_params(labelsize=9 if compact else 11)


def selected_indices(count: int, *, max_count: int) -> list[int]:
    if count <= max_count:
        return list(range(count))
    return sorted({int(round(value)) for value in np.linspace(0, count - 1, max_count)})


def write_case_html(result: CaseResult, output_dir: Path) -> None:
    cards = "\n".join(
        f"<div class='metric-card'><div class='metric-label'>{html.escape(label)}</div>"
        f"<div class='metric-value'>{html.escape(value)}</div>"
        f"<div class='metric-note'>{html.escape(note)}</div></div>"
        for label, value, note in parameter_cards(result)
    )
    domain_context = linked_figure("figures/domain_context.png", "Nancon domain context")
    mesh_overview = linked_figure("figures/mesh_overview.png", "Mesh overview")
    topography = linked_figure("figures/topography.png", "Topography")
    flow_direction = linked_figure("figures/flow_head_direction.png", "Flow direction")
    cell_peclet = linked_figure("figures/cell_peclet.png", "Cell Peclet")
    concentration_snapshots = linked_figure(
        "figures/concentration_snapshots.png", "Concentration snapshots"
    )
    concentration_profiles = linked_figure(
        "figures/concentration_profiles.png", "Concentration profiles"
    )
    probe_breakthrough = linked_figure("figures/probe_breakthrough.png", "Probe breakthrough")
    plume_evolution = linked_figure("figures/plume_evolution.png", "Plume evolution")
    network_exposure = linked_figure("figures/network_exposure.png", "Network exposure")
    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html.escape(result.case.title)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 28px; color: #1f2933; background: #f7f9fb; }}
    h1, h2 {{ margin-bottom: 0.35rem; }}
    h2 {{ margin-top: 2rem; border-bottom: 2px solid #d9e2ec; padding-bottom: 0.35rem; }}
    h3 {{ margin-bottom: 0.35rem; }}
    .muted {{ color: #52606d; }}
    .panel {{ background: white; border: 1px solid #d9e2ec; padding: 18px; margin: 16px 0 24px; }}
    img {{ max-width: 100%; border: 1px solid #d9e2ec; margin: 8px 0 22px; background: white; }}
    .figure-link {{ display: block; color: inherit; }}
    .figure-link img {{ cursor: zoom-in; transition: box-shadow 0.15s ease, transform 0.15s ease; }}
    .figure-link:hover img {{ box-shadow: 0 6px 18px rgba(31, 41, 51, 0.18); transform: translateY(-1px); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(460px, 1fr)); gap: 18px; }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px; }}
    .metric-card {{ background: white; border: 1px solid #d9e2ec; padding: 14px; }}
    .metric-label {{ color: #52606d; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }}
    .metric-value {{ font-size: 24px; font-weight: 700; margin: 6px 0; }}
    .metric-note {{ color: #52606d; font-size: 12px; line-height: 1.35; }}
  </style>
</head>
<body>
  <h1>{html.escape(result.case.title)}</h1>
  <p class="muted">{html.escape(result.case.description)}</p>
  <p><b>Case:</b> {html.escape(result.case.name)} | <b>Mesh:</b> existing Nancon triangular DISV bundle</p>

  <h2>Context</h2>
  <div class="panel">
    <p>
      This report is a high-quality visual guard for a future Nancon MF6-GWT
      transport case. The transport field is deterministic and intentionally
      controlled: the real Nancon mesh, topography and river constraints are used,
      while the advective velocity is scaled to make plume motion visible in a
      compact report.
    </p>
    <p><b>Transport boundary condition:</b> {html.escape(transport_boundary_description(result.case))}</p>
    {domain_context}
  </div>

  <h2>Key Parameters</h2>
  <div class="metric-grid">{cards}</div>

  <h2>Mesh And Flow</h2>
  <div class="grid">
    <div><h3>Mesh</h3>{mesh_overview}</div>
    <div><h3>Topography</h3>{topography}</div>
    <div><h3>Head and direction</h3>{flow_direction}</div>
    <div><h3>Cell Peclet</h3>{cell_peclet}</div>
  </div>

  <h2>Transport</h2>
  <p class="muted">
    Concentration maps use a white-zero scale with power normalization so dilute
    parts of the plume remain visible without coloring zero-concentration cells.
  </p>
  {concentration_snapshots}
  {concentration_profiles}
  <div class="grid">
    <div><h3>Breakthrough</h3>{probe_breakthrough}</div>
    <div><h3>Plume evolution</h3>{plume_evolution}</div>
  </div>
  {network_exposure}
</body>
</html>
"""
    (output_dir / "index.html").write_text(body, encoding="utf-8")


def linked_figure(src: str, alt: str) -> str:
    escaped_src = html.escape(src)
    escaped_alt = html.escape(alt)
    return (
        f'<a class="figure-link" href="{escaped_src}" target="_blank" rel="noopener">'
        f'<img src="{escaped_src}" alt="{escaped_alt}" title="Open full-size image"></a>'
    )


def parameter_cards(result: CaseResult) -> list[tuple[str, str, str]]:
    numbers = result.signatures["flow_transport_numbers"]
    case = result.signatures["case"]
    mesh = result.signatures["mesh"]
    return [
        (
            "Mesh",
            f"{mesh['n_cells']} cells",
            f"{mesh['area_total_km2']} km2 watershed, {mesh['n_river_cells']} river-adjacent cells",
        ),
        (
            "Path",
            f"{result.path_length_m / 1000.0:.1f} km",
            "source-to-outlet visual transport axis",
        ),
        (
            "Velocity",
            f"{case['velocity_m_per_day']:.2g} m/day",
            "scaled pore velocity for readable plume movement",
        ),
        (
            "Duration",
            f"{case['duration_years']:.1f} yr",
            f"{case['n_output_times']} output times",
        ),
        (
            "Cell Peclet",
            f"{numbers['peclet_mean']:.1f}",
            f"range {numbers['peclet_min']:.1f}-{numbers['peclet_max']:.1f}",
        ),
        (
            "Diffusion",
            f"{numbers['diffusion_m2_per_day']:.2g} m2/day",
            "chosen from the target mean cell Peclet",
        ),
        (
            "Source",
            result.case.source_mode.replace("_", " "),
            f"C0 = {case['source_concentration']}",
        ),
        (
            "Reference K",
            "5e-5 m/s",
            "from existing Nancon benchmark configs; not yet a coupled GWT run",
        ),
    ]


def transport_boundary_description(case: NanconCase) -> str:
    if case.source_mode == "internal_pulse":
        return (
            "internal finite pulse, no solute imposed at the upstream boundary, "
            "downstream outlet treated visually as open/absorbing."
        )
    if case.source_mode == "upstream_pulse":
        return (
            "finite upstream concentration pulse, then clean inflow; downstream outlet "
            "treated visually as open/absorbing."
        )
    return (
        "constant upstream concentration source; downstream outlet treated visually "
        "as open/absorbing."
    )


def write_index(results: list[CaseResult], output_dir: Path) -> None:
    rows = "\n".join(
        "<tr>"
        f"<td><a href='{html.escape(result.case.name)}/index.html'>{html.escape(result.case.name)}</a></td>"
        f"<td>{html.escape(result.case.source_mode)}</td>"
        f"<td>{result.mesh.n_cells}</td>"
        f"<td>{result.path_length_m / 1000.0:.2f} km</td>"
        f"<td>{result.signatures['case']['duration_years']} yr</td>"
        f"<td>{result.signatures['flow_transport_numbers']['peclet_mean']}</td>"
        f"<td>{result.signatures.get('runtime', {}).get('total_seconds', 'n/a')} s</td>"
        "</tr>"
        for result in results
    )
    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Nancon Transport Visual Guard</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 28px; color: #1f2933; background: #f7f9fb; }}
    table {{ border-collapse: collapse; width: 100%; background: white; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px 10px; text-align: left; }}
    th {{ background: #f0f4f8; }}
  </style>
</head>
<body>
  <h1>Nancon Transport Visual Guard</h1>
  <p>Dedicated visual transport bench on the existing Nancon triangular DISV mesh.</p>
  <table>
    <thead><tr><th>Case</th><th>Source</th><th>Cells</th><th>Path</th><th>Duration</th><th>Mean Pe</th><th>Generated in</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</body>
</html>
"""
    (output_dir / "index.html").write_text(body, encoding="utf-8")


def run_cases(
    *,
    mesh_bundle: Path,
    output_dir: Path,
    case_names: set[str] | None,
) -> list[CaseResult]:
    mesh = load_nancon_mesh(mesh_bundle)
    available = default_cases()
    if case_names is not None:
        available = [case for case in available if case.name in case_names]
    if not available:
        raise ValueError("No Nancon visual case selected.")

    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for case in available:
        start = perf_counter()
        result = run_case(case, mesh)
        backend_seconds = perf_counter() - start
        render_start = perf_counter()
        result.signatures["runtime"] = {"backend_seconds": _round(backend_seconds, 3)}
        render_case_report(result, output_dir / case.name)
        render_seconds = perf_counter() - render_start
        total_seconds = perf_counter() - start
        result.signatures["runtime"].update(
            {
                "report_seconds": _round(render_seconds, 3),
                "total_seconds": _round(total_seconds, 3),
            }
        )
        write_signatures(result, output_dir / case.name)
        write_case_html(result, output_dir / case.name)
        results.append(result)
    write_index(results, output_dir)
    return results


def _round(value: float, ndigits: int = 6) -> float:
    if not np.isfinite(value):
        return 0.0
    return round(float(value), ndigits)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mesh-bundle",
        type=Path,
        default=DEFAULT_MESH_BUNDLE,
        help="Path to a mesh_catchment_bundle directory with nodes/cells/edges CSV files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for the Nancon visual report.",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        help="Case name to run. Can be supplied multiple times. Default: all cases.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    results = run_cases(
        mesh_bundle=args.mesh_bundle,
        output_dir=args.output_dir,
        case_names=set(args.cases) if args.cases else None,
    )
    print(f"Wrote {len(results)} Nancon visual case(s) to {args.output_dir}")
    print(f"Open {args.output_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
