"""Build the B0 truth package from two persisted HydroModPy runs.

This script is deliberately local to the standalone B0 example. It consumes
completed catalog runs and writes the `truth/` pseudo-observation package
without modifying the global calibration API.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.calibration.network_transient_truth import (
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

        summary = write_network_transient_truth_package_from_runs(
            args.output_dir,
            steady_run=steady_run,
            transient_run=transient_run,
            tau_network=args.tau_network,
            d_tol=args.d_tol,
            warmup_periods=args.warmup_periods,
            scored_periods=args.scored_periods,
            metadata={
                "site_id": args.site_id,
                "mK_true": args.mK_true,
                "Sy_true": args.Sy_true,
            },
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


if __name__ == "__main__":
    raise SystemExit(main())
