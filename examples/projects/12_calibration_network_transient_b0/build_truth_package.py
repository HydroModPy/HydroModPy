"""Build the B0 truth package from two persisted HydroModPy runs.

This script is deliberately local to the standalone B0 example. It consumes
completed catalog runs and writes the `truth/` pseudo-observation package
without modifying the global calibration API.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.calibration.network_transient_truth import (
    mesh_cell_geometry,
    write_network_transient_truth_package,
    write_network_transient_truth_package_from_runs,
)
from hydromodpy.results.catalog import SimulationCatalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--steady-catalog",
        type=Path,
        required=True,
        help="Workspace or hydromodpy.duckdb file containing the steady network run.",
    )
    parser.add_argument(
        "--steady-ref",
        required=True,
        help="Simulation id, prefix, or run name for the steady truth run.",
    )
    parser.add_argument(
        "--steady-drain-npz",
        type=Path,
        default=None,
        help=(
            "Optional NPZ containing outflow_drain for the steady network target. "
            "When supplied, --steady-catalog/--steady-ref are still used for mesh geometry."
        ),
    )
    parser.add_argument(
        "--mesh-bundle",
        type=Path,
        default=None,
        help=(
            "Optional mesh exchange bundle containing cells.csv. When supplied, "
            "centroids and cell areas are read from the bundle instead of steady_run.mesh."
        ),
    )
    parser.add_argument(
        "--steady-project",
        default=None,
        help="Optional project name used when --steady-ref is a run name.",
    )
    parser.add_argument(
        "--transient-catalog",
        type=Path,
        default=None,
        help="Workspace or hydromodpy.duckdb file containing the transient run. Defaults to --steady-catalog.",
    )
    parser.add_argument(
        "--transient-ref",
        required=True,
        help="Simulation id, prefix, or run name for the transient truth run.",
    )
    parser.add_argument(
        "--transient-q-csv",
        type=Path,
        default=None,
        help=(
            "Optional CSV containing the target Q_total_release chronicle. Supports either "
            "q_total_release or exported timeseries columns datetime/station_id/variable/value."
        ),
    )
    parser.add_argument(
        "--transient-project",
        default=None,
        help="Optional project name used when --transient-ref is a run name.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "truth",
        help="Output truth package directory.",
    )
    parser.add_argument("--site-id", default="site_05")
    parser.add_argument("--mK-true", type=float, default=1.0)
    parser.add_argument("--Sy-true", type=float, default=0.05)
    parser.add_argument("--tau-network", type=float, default=0.0)
    parser.add_argument("--d-tol", type=float, default=None)
    parser.add_argument("--warmup-periods", type=int, default=12)
    parser.add_argument("--scored-periods", type=int, default=36)
    args = parser.parse_args(argv)

    steady_catalog = SimulationCatalog(args.steady_catalog)
    transient_catalog = None
    try:
        steady_sim_id = steady_catalog.resolve(args.steady_ref, project=args.steady_project)
        steady_run = steady_catalog[steady_sim_id]

        transient_catalog_path = args.transient_catalog or args.steady_catalog
        if Path(transient_catalog_path).resolve() == Path(args.steady_catalog).resolve():
            transient_catalog = steady_catalog
        else:
            transient_catalog = SimulationCatalog(transient_catalog_path)
        transient_sim_id = transient_catalog.resolve(
            args.transient_ref,
            project=args.transient_project,
        )
        transient_run = transient_catalog[transient_sim_id]

        metadata = {
            "site_id": args.site_id,
            "mK_true": args.mK_true,
            "Sy_true": args.Sy_true,
        }
        if args.steady_drain_npz is None:
            summary = write_network_transient_truth_package_from_runs(
                args.output_dir,
                steady_run=steady_run,
                transient_run=transient_run,
                tau_network=args.tau_network,
                d_tol=args.d_tol,
                warmup_periods=args.warmup_periods,
                scored_periods=args.scored_periods,
                metadata=metadata,
            )
        else:
            with np.load(args.steady_drain_npz) as data:
                steady_drain = np.asarray(data["outflow_drain"], dtype=float).reshape(-1)
            if args.mesh_bundle is None:
                mesh = steady_run.mesh
                centroids, cell_area = mesh_cell_geometry(
                    mesh.vertices, mesh.face_node_connectivity
                )
            else:
                centroids, cell_area = _mesh_geometry_from_bundle(args.mesh_bundle)
            if args.transient_q_csv is None:
                q_total_release = transient_run.timeseries("discharge", "_catchment").to_numpy(
                    dtype=float
                )
                time_index = transient_run.time_index
            else:
                q_total_release, time_index = _read_q_total_release_csv(args.transient_q_csv)
            metadata.update(
                {
                    "steady_sim_id": getattr(steady_run, "sim_id", None),
                    "steady_name": getattr(steady_run, "name", None),
                    "steady_solver": getattr(steady_run, "solver", None),
                    "steady_drain_npz": str(args.steady_drain_npz),
                    "mesh_bundle": None if args.mesh_bundle is None else str(args.mesh_bundle),
                    "transient_sim_id": getattr(transient_run, "sim_id", None),
                    "transient_name": getattr(transient_run, "name", None),
                    "transient_solver": getattr(transient_run, "solver", None),
                    "transient_q_csv": (
                        None if args.transient_q_csv is None else str(args.transient_q_csv)
                    ),
                }
            )
            summary = write_network_transient_truth_package(
                args.output_dir,
                steady_drain_by_cell=steady_drain,
                transient_q_total_release=q_total_release,
                centroids=centroids,
                cell_area=cell_area,
                time_index=time_index,
                tau_network=args.tau_network,
                d_tol=args.d_tol,
                warmup_periods=args.warmup_periods,
                scored_periods=args.scored_periods,
                metadata=metadata,
            )
    finally:
        if transient_catalog is not None and transient_catalog is not steady_catalog:
            transient_catalog.close()
        steady_catalog.close()

    print(f"Wrote truth package: {summary.output_dir}")
    print(f"  n_cells={summary.n_cells}")
    print(f"  n_timesteps={summary.n_timesteps}")
    print(f"  n_ref_active={summary.n_ref_active}")
    print(f"  Q_ref_steady={summary.q_ref_steady:.12g}")
    print(f"  Qbar_ref={summary.qbar_ref:.12g}")
    print(f"  L_ref={summary.l_ref:.12g}")
    return 0


def _mesh_geometry_from_bundle(bundle_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    cells = pd.read_csv(bundle_dir / "cells.csv").sort_values("cell_id")
    return (
        cells[["centroid_x", "centroid_y"]].to_numpy(dtype=float),
        cells["area_m2"].to_numpy(dtype=float),
    )


def _read_q_total_release_csv(path: Path) -> tuple[np.ndarray, pd.DatetimeIndex | None]:
    frame = pd.read_csv(path)
    if "q_total_release" in frame.columns:
        q = frame["q_total_release"].to_numpy(dtype=float)
    elif {"station_id", "variable", "value"}.issubset(frame.columns):
        mask = (frame["station_id"].astype(str) == "_catchment") & (
            frame["variable"].astype(str) == "discharge"
        )
        frame = frame.loc[mask].copy()
        q = frame["value"].to_numpy(dtype=float)
    elif "value" in frame.columns:
        q = frame["value"].to_numpy(dtype=float)
    else:
        raise ValueError(f"Cannot find a discharge column in {path}")
    time_index = None
    if "datetime" in frame.columns:
        time_index = pd.DatetimeIndex(pd.to_datetime(frame["datetime"], format="mixed", utc=True))
    return q, time_index


if __name__ == "__main__":
    raise SystemExit(main())
