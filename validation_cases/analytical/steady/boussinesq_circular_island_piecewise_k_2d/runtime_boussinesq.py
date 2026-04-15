"""Local `flow/boussinesq` runtime for the circular-island piecewise-K validation case."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.spatial.geographic.synthetic import SyntheticGridConfig, SyntheticTopographyConfig
from hydromodpy.spatial.geographic.synthetic.topography import build_topography_values
from hydromodpy.process.flow import Flow
from hydromodpy.simulation.adapters.flow.boussinesq import BoussinesqFlowAdapter
from hydromodpy.simulation.planning.plan import (
    ProcessRun,
    RunContext,
    SimulationPlan,
)
from validation_cases.analytical.steady.boussinesq_fixed_head_piecewise_k_1d.runtime_boussinesq import (
    _build_flow_config,
)
from validation_cases.shared import load_case_metadata
from validation_cases.shared.runtime import (
    ValidationRunResult,
    resolve_validation_results_dir,
)


CASE_DIR = Path(__file__).resolve().parent
CASE_ID = "boussinesq_circular_island_piecewise_k_2d"
N_SECTORS = 16
LAND_SUPPORT_RADII_M = (25.0, 50.0, 70.0, 100.0, 140.0, 180.0, 200.0)
OUTER_OCEAN_BUFFER_M = 5.0
OCEAN_RING_CONDUCTIVITY_M_S = 1.0
STORAGE_COEFFICIENT = 0.1


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _load_reference_cfg() -> dict:
    metadata = load_case_metadata(CASE_DIR)
    return dict(metadata.get("reference", {}))


def _ring_index_for_radius(radius_m: float, ring_breaks_m: tuple[float, ...]) -> int:
    for ring_index, radius_break_m in enumerate(ring_breaks_m):
        if float(radius_m) < float(radius_break_m):
            return int(ring_index)
    return int(len(ring_breaks_m))


def _radial_island_top_elevation_m(
    radius_m: float,
    *,
    island_radius_m: float,
    crest_elevation_m: float,
    ocean_floor_elevation_m: float,
) -> float:
    if float(radius_m) > float(island_radius_m):
        return float(ocean_floor_elevation_m)
    normalized_radius = max(0.0, 1.0 - (float(radius_m) / float(island_radius_m)) ** 2)
    return float(crest_elevation_m) * float(np.sqrt(normalized_radius))


def _triangle_area_m2(points_xy_m: np.ndarray) -> float:
    x0, y0 = points_xy_m[0]
    x1, y1 = points_xy_m[1]
    x2, y2 = points_xy_m[2]
    return 0.5 * abs(((x1 - x0) * (y2 - y0)) - ((x2 - x0) * (y1 - y0)))


def _reference_grid(
    reference_cfg: dict,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    grid = SyntheticGridConfig(
        length_x=float(reference_cfg["length_x_m"]),
        length_y=float(reference_cfg["length_y_m"]),
        nx=int(reference_cfg["nx"]),
        ny=int(reference_cfg["ny"]),
        xmin=float(reference_cfg["xmin"]),
        ymin=float(reference_cfg["ymin"]),
        crs=str(reference_cfg.get("crs", "EPSG:2154")),
        nodata=-9999.0,
    )
    topography = SyntheticTopographyConfig(
        kind="radial_island",
        base_elevation=float(reference_cfg["ocean_floor_elevation_m"]),
        crest_elevation=float(reference_cfg["crest_elevation_m"]),
        island_radius=float(reference_cfg["island_radius_m"]),
        center_x=float(reference_cfg["center_x_m"]),
        center_y=float(reference_cfg["center_y_m"]),
    )
    dem = build_topography_values(topography=topography, grid=grid)
    x_centers = float(grid.xmin) + (np.arange(int(grid.ncol), dtype=float) + 0.5) * float(grid.dx)
    y_centers = float(grid.ymin) + (np.arange(int(grid.nrow), dtype=float) + 0.5) * float(grid.dy)
    xx, yy = np.meshgrid(x_centers, y_centers)
    return np.asarray(dem, dtype=float), np.asarray(xx, dtype=float), np.asarray(yy, dtype=float)


def _write_circular_island_bundle(
    bundle_dir: Path,
    reference_cfg: dict,
) -> tuple[Path, tuple[tuple[float, float, float], ...]]:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "mesh_2d.msh").write_text(
        "$MeshFormat\n2.2 0 8\n$EndMeshFormat\n",
        encoding="utf-8",
    )
    (bundle_dir / "metadata.json").write_text(
        json.dumps(
            {
                "bundle_schema_version": "mesh_catchment_bundle_v1",
                "crs": str(reference_cfg.get("crs", "EPSG:2154")),
                "files": {"mesh": "mesh_2d.msh"},
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "mesh_summary.json").write_text(
        json.dumps({"constraints_mode": "geology_only"}, indent=2, ensure_ascii=True)
        + "\n",
        encoding="utf-8",
    )

    center_x_m = float(reference_cfg["center_x_m"])
    center_y_m = float(reference_cfg["center_y_m"])
    ring_breaks_m = tuple(float(value) for value in reference_cfg["ring_radius_breaks_m"])
    conductivity_by_ring = tuple(
        float(value) for value in reference_cfg["hydraulic_conductivity_m_per_s_by_ring"]
    )
    island_radius_m = float(reference_cfg["island_radius_m"])
    crest_elevation_m = float(reference_cfg["crest_elevation_m"])
    ocean_floor_elevation_m = float(reference_cfg["ocean_floor_elevation_m"])
    substratum_elevation_m = float(reference_cfg["substratum_elevation_m"])

    support_radii_m = LAND_SUPPORT_RADII_M + (
        island_radius_m + float(OUTER_OCEAN_BUFFER_M),
    )

    node_xy_by_id: dict[int, tuple[float, float]] = {0: (center_x_m, center_y_m)}
    node_rows = [f"0,{center_x_m:.6f},{center_y_m:.6f},{crest_elevation_m:.6f},{substratum_elevation_m:.6f}"]

    def ring_node_id(ring_index: int, sector_index: int) -> int:
        return 1 + (int(ring_index) * int(N_SECTORS)) + int(sector_index)

    for ring_index, radius_m in enumerate(support_radii_m):
        for sector_index in range(N_SECTORS):
            theta_rad = (2.0 * np.pi * float(sector_index)) / float(N_SECTORS)
            x_m = center_x_m + float(radius_m) * float(np.cos(theta_rad))
            y_m = center_y_m + float(radius_m) * float(np.sin(theta_rad))
            radius_for_top_m = min(float(radius_m), island_radius_m)
            z_top_m = _radial_island_top_elevation_m(
                radius_for_top_m,
                island_radius_m=island_radius_m,
                crest_elevation_m=crest_elevation_m,
                ocean_floor_elevation_m=ocean_floor_elevation_m,
            )
            node_id = ring_node_id(ring_index, sector_index)
            node_xy_by_id[node_id] = (x_m, y_m)
            node_rows.append(
                f"{node_id},{x_m:.6f},{y_m:.6f},{z_top_m:.6f},{substratum_elevation_m:.6f}"
            )
    _write_csv(bundle_dir / "nodes.csv", "node_id,x,y,z_top,z_bottom", node_rows)

    cell_rows: list[str] = []
    geology_rows: list[str] = []
    ocean_cell_specs: list[tuple[float, float, float]] = []
    edge_records: dict[tuple[int, int], dict[str, object]] = {}
    cell_id = 0

    def append_triangle(node_ids: tuple[int, int, int]) -> None:
        nonlocal cell_id

        triangle_points = np.asarray(
            [node_xy_by_id[int(node_id)] for node_id in node_ids],
            dtype=float,
        )
        triangle_radii_m = np.sqrt(
            (triangle_points[:, 0] - center_x_m) ** 2
            + (triangle_points[:, 1] - center_y_m) ** 2
        )
        centroid_x_m = float(np.mean(triangle_points[:, 0]))
        centroid_y_m = float(np.mean(triangle_points[:, 1]))
        centroid_radius_m = float(
            np.hypot(centroid_x_m - center_x_m, centroid_y_m - center_y_m)
        )
        is_ocean_cell = bool(np.max(triangle_radii_m) > float(island_radius_m) + 1.0e-9)
        if is_ocean_cell:
            geology_code = int(len(conductivity_by_ring) + 1)
            geology_key = "ocean_ring"
            hydraulic_conductivity_m_s = float(OCEAN_RING_CONDUCTIVITY_M_S)
            z_top_m = float(ocean_floor_elevation_m)
        else:
            zone_index = _ring_index_for_radius(centroid_radius_m, ring_breaks_m)
            geology_code = int(zone_index + 1)
            geology_key = f"ring_{zone_index + 1}"
            hydraulic_conductivity_m_s = float(conductivity_by_ring[zone_index])
            z_top_m = _radial_island_top_elevation_m(
                centroid_radius_m,
                island_radius_m=island_radius_m,
                crest_elevation_m=crest_elevation_m,
                ocean_floor_elevation_m=ocean_floor_elevation_m,
            )
        area_m2 = _triangle_area_m2(triangle_points)
        if is_ocean_cell:
            ocean_cell_specs.append((centroid_x_m, centroid_y_m, area_m2))
        cell_rows.append(
            ",".join(
                [
                    str(cell_id),
                    "triangle",
                    str(node_ids[0]),
                    str(node_ids[1]),
                    str(node_ids[2]),
                    "",
                    f"{centroid_x_m:.6f}",
                    f"{centroid_y_m:.6f}",
                    f"{area_m2:.6f}",
                    f"{z_top_m:.6f}",
                    f"{z_top_m:.6f}",
                    f"{substratum_elevation_m:.6f}",
                    f"{substratum_elevation_m:.6f}",
                    str(geology_code),
                    geology_key,
                    f"{hydraulic_conductivity_m_s:.12g}",
                    f"{STORAGE_COEFFICIENT:.12g}",
                ]
            )
        )
        geology_rows.append(f"{cell_id},{geology_key},1.0")

        for edge_nodes in (
            (node_ids[0], node_ids[1]),
            (node_ids[1], node_ids[2]),
            (node_ids[2], node_ids[0]),
        ):
            key = tuple(sorted((int(edge_nodes[0]), int(edge_nodes[1]))))
            edge = edge_records.get(key)
            if edge is None:
                point_a = np.asarray(node_xy_by_id[key[0]], dtype=float)
                point_b = np.asarray(node_xy_by_id[key[1]], dtype=float)
                edge_records[key] = {
                    "node_a": key[0],
                    "node_b": key[1],
                    "cell_a": cell_id,
                    "cell_b": None,
                    "length_m": float(np.linalg.norm(point_b - point_a)),
                    "geology_a_key": geology_key,
                    "geology_b_key": "",
                }
            else:
                edge["cell_b"] = cell_id
                edge["geology_b_key"] = geology_key
        cell_id += 1

    for sector_index in range(N_SECTORS):
        next_sector_index = (sector_index + 1) % N_SECTORS
        append_triangle(
            (
                0,
                ring_node_id(0, sector_index),
                ring_node_id(0, next_sector_index),
            )
        )

    for ring_index in range(len(support_radii_m) - 1):
        for sector_index in range(N_SECTORS):
            next_sector_index = (sector_index + 1) % N_SECTORS
            inner_a = ring_node_id(ring_index, sector_index)
            inner_b = ring_node_id(ring_index, next_sector_index)
            outer_a = ring_node_id(ring_index + 1, sector_index)
            outer_b = ring_node_id(ring_index + 1, next_sector_index)
            append_triangle((inner_a, outer_a, outer_b))
            append_triangle((inner_a, outer_b, inner_b))

    _write_csv(
        bundle_dir / "cells.csv",
        "cell_id,geom_type,n0,n1,n2,n3,centroid_x,centroid_y,area_m2,z_top_centroid,z_top_mean,z_bottom_centroid,z_bottom_mean,geology_code,geology_key,hydraulic_conductivity_m_s,storage_coefficient",
        cell_rows,
    )
    _write_csv(
        bundle_dir / "cell_geology_fractions.csv",
        "cell_id,geology_key,fraction",
        geology_rows,
    )

    edge_rows: list[str] = []
    for edge_id, edge in enumerate(edge_records.values()):
        cell_b = edge["cell_b"]
        edge_rows.append(
            ",".join(
                [
                    str(edge_id),
                    str(edge["node_a"]),
                    str(edge["node_b"]),
                    str(edge["cell_a"]),
                    "" if cell_b is None else str(cell_b),
                    f"{float(edge['length_m']):.6f}",
                    "boundary" if cell_b is None else "internal",
                    "false",
                    str(edge["geology_a_key"]),
                    str(edge["geology_b_key"]),
                ]
            )
        )
    _write_csv(
        bundle_dir / "edges.csv",
        "edge_id,node_a,node_b,cell_a,cell_b,length_m,edge_kind,is_river,geology_a_key,geology_b_key",
        edge_rows,
    )
    return bundle_dir, tuple(ocean_cell_specs)


def _aggregate_triangle_history_to_reference_grid(model, reference_cfg: dict) -> None:
    """Project cellwise Boussinesq heads back to the structured validation grid."""
    if model.state is None or model.mesh is None:
        raise RuntimeError("Boussinesq validation case requires a solved model state.")

    raw_head_history = np.asarray(model.state.head_history_m, dtype=float)
    if raw_head_history.ndim == 1:
        head_history = raw_head_history.reshape(1, -1)
    else:
        head_history = raw_head_history

    dem, xx, yy = _reference_grid(reference_cfg)
    sea_level_m = float(reference_cfg["sea_level_m"])
    island_radius_m = float(reference_cfg["island_radius_m"])
    outer_support_radius_m = island_radius_m + float(OUTER_OCEAN_BUFFER_M)
    radius = np.sqrt(
        (xx - float(reference_cfg["center_x_m"])) ** 2
        + (yy - float(reference_cfg["center_y_m"])) ** 2
    )

    projection_indices = np.full(dem.shape, -1, dtype=int)
    within_support_mask = radius <= float(outer_support_radius_m)
    for row_index, col_index in np.argwhere(within_support_mask):
        projection_indices[row_index, col_index] = model.mesh.locate_cell_index_for_point(
            float(xx[row_index, col_index]),
            float(yy[row_index, col_index]),
            allow_nearest=True,
        )

    watertable_elevation: dict[int, np.ndarray] = {}
    watertable_depth: dict[int, np.ndarray] = {}
    for time_index, head_values in enumerate(head_history):
        head_grid = np.full(dem.shape, sea_level_m, dtype=float)
        valid_mask = projection_indices >= 0
        head_grid[valid_mask] = np.asarray(head_values, dtype=float)[projection_indices[valid_mask]]
        head_grid[np.asarray(dem, dtype=float) <= sea_level_m] = sea_level_m
        watertable_elevation[int(time_index)] = head_grid
        watertable_depth[int(time_index)] = np.maximum(np.asarray(dem, dtype=float) - head_grid, 0.0)

    postprocess_dir = Path(model.full_path) / "_postprocess"
    postprocess_dir.mkdir(parents=True, exist_ok=True)
    np.save(postprocess_dir / "watertable_elevation.npy", watertable_elevation)
    np.save(postprocess_dir / "watertable_depth.npy", watertable_depth)


def run_boussinesq_circular_island_piecewise_k_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
) -> ValidationRunResult:
    """Run the circular-island piecewise-K case through the local `flow/boussinesq` adapter."""
    del timeout

    reference_cfg = _load_reference_cfg()
    out_path = resolve_validation_results_dir(
        test_file=caller_file,
        run_name=f"{CASE_ID}_boussinesq",
    )
    recharge_rate_m_s = float(reference_cfg["recharge_mm_day"]) * 1.0e-3 / 86400.0
    bundle_dir, ocean_cell_specs = _write_circular_island_bundle(
        out_path / "mesh_bundle",
        reference_cfg,
    )
    simulations_folder = out_path / "results_simulations"
    simulations_folder.mkdir(parents=True, exist_ok=True)
    wells_payload = {
        f"ocean_comp_{index:03d}": {
            "location_mode": "absolute_xy",
            "layer": 0,
            "x": float(x_m),
            "y": float(y_m),
            "flux": -recharge_rate_m_s * float(area_m2),
        }
        for index, (x_m, y_m, area_m2) in enumerate(ocean_cell_specs)
    }

    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(
                _build_flow_config(
                    {
                        "flow_regime": "steady",
                        # This medium-size island mesh still converges more
                        # robustly on the dense local Newton path than on the
                        # sparse validation backend.
                        "runtime_backend": "local",
                        "ic": {"type": "custom", "value": 1.0},
                        "active_sinks_sources": ["recharge", "wells"],
                        "active_bc": ["ocean"],
                        "sinks_sources": {
                            "recharge": {
                                "values": recharge_rate_m_s,
                                "first_clim": "mean",
                    "units": "m/s",
                            },
                            "wells": wells_payload,
                        },
                        "bc": {
                            "dirichlet": {
                                "ocean": {"value": float(reference_cfg["sea_level_m"])},
                            }
                        },
                    },
                    case_dir=CASE_DIR,
                )
            ),
            domain=None,
            time_grid=None,
            workspace=SimpleNamespace(simulations_folder=simulations_folder, solver_scratch_folder=simulations_folder),
        ),
    )
    run = ProcessRun(
        id="flow_validation::boussinesq",
        process_id="flow_validation",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(
            name="Boussinesq circular-island validation",
            description="Steady circular island with ocean boundary and concentric K rings",
            runs=(run,),
        ),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model
    _aggregate_triangle_history_to_reference_grid(model, reference_cfg)

    model_ws = Path(model.full_path)
    postprocess_dir = model_ws / "_postprocess"
    particles_dir = postprocess_dir / "_particles"
    return ValidationRunResult(
        case_dir=CASE_DIR,
        solver_name="boussinesq",
        out_path=out_path,
        model_ws=model_ws,
        postprocess_dir=postprocess_dir,
        particles_dir=particles_dir,
        run_returncode=0,
        run_stdout="",
        run_stderr="",
    )


__all__ = ["run_boussinesq_circular_island_piecewise_k_case"]
