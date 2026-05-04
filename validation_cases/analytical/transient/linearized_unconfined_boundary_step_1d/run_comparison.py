"""Run a same-support simulation comparison for the transient boundary-step case."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from hydromodpy.analysis.comparison.experiment_launcher import SimulationComparisonLauncher
from hydromodpy.analysis.comparison.runtime import write_toml_payload

CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[3]
DEFAULT_COMPARISON_ID = "lu_boundary_step_same_support"
DEFAULT_OUTPUT_ROOT = CASE_DIR / "comparison" / DEFAULT_COMPARISON_ID
DEFAULT_CONFIG_PATH = CASE_DIR / ".__runtime_comparison_boundary_step.toml"


def _build_payload(*, output_root: Path, run_variants: bool) -> dict[str, Any]:
    workspace_root = REPO_ROOT / "tmp" / f"{DEFAULT_COMPARISON_ID}_workspace"
    west_head_csv = CASE_DIR / "west_head_step.csv"

    common_overlay = {
        "workspace": {
            "project_root": str(CASE_DIR),
            "root": str(workspace_root),
            "output_root": str(workspace_root),
        },
        "flow": {
            "bc": {
                "dirichlet": {
                    "west_side": {
                        "forcing": {
                            "path_file": str(west_head_csv),
                        }
                    }
                }
            }
        },
    }

    return {
        "workflow": "comparison",
        "comparison": {
            "comparison_id": DEFAULT_COMPARISON_ID,
            "base_simulation_config": str(CASE_DIR / "config_modflownwt.toml"),
            "output_root": str(output_root),
            "reference_simulation": "modflow6",
            "execution": {
                "run_simulations": bool(run_variants),
            },
            "simulation": [
                {
                    "id": "modflownwt",
                    "label": "MODFLOW-NWT 50x5",
                    "solver": "modflownwt",
                    "mesh_mode": "structured",
                    "overlay": common_overlay,
                },
                {
                    "id": "modflow6",
                    "label": "MODFLOW 6 50x5",
                    "solver": "modflow6",
                    "mesh_mode": "structured",
                    "overlay": {
                        **common_overlay,
                        "modflow6": {
                            "runtime": {
                                "mf_verbose": False,
                                "mf6_ims_complexity": "COMPLEX",
                            },
                            "sgrid": {
                                "planar": {
                                    "mode": "resample_to_shape",
                                    "nx": 50,
                                    "ny": 5,
                                    "resampling": "nearest",
                                },
                                "vertical": {"nlay": 1},
                            },
                            "tgrid": {"firstpersteady": False},
                        },
                    },
                },
            ],
            "observable": [
                {
                    "name": "head_west_response",
                    "variable": "watertable_elevation",
                    "support": "point",
                    "cell_index": 5,
                    "time": "all",
                    "unit": "m",
                },
                {
                    "name": "head_mid_response",
                    "variable": "watertable_elevation",
                    "support": "point",
                    "cell_index": 25,
                    "time": "all",
                    "unit": "m",
                },
                {
                    "name": "head_east_response",
                    "variable": "watertable_elevation",
                    "support": "point",
                    "cell_index": 45,
                    "time": "all",
                    "unit": "m",
                },
                {
                    "name": "head_map_last",
                    "variable": "watertable_elevation",
                    "support": "map",
                    "time": "last",
                    "unit": "m",
                },
                {
                    "name": "depth_map_last",
                    "variable": "watertable_depth",
                    "support": "map",
                    "time": "last",
                    "unit": "m",
                },
            ],
        },
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a same-support comparison between MODFLOW-NWT and MODFLOW 6 "
            "on the transient boundary-step case."
        )
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory where comparison artifacts are written.",
    )
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="Reuse existing simulation run folders instead of relaunching the solvers.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    output_root = Path(args.output_root).expanduser()
    if not output_root.is_absolute():
        output_root = (CASE_DIR / output_root).resolve()

    workspace_root = REPO_ROOT / "tmp" / f"{DEFAULT_COMPARISON_ID}_workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / "data").mkdir(parents=True, exist_ok=True)
    (workspace_root / "simulations").mkdir(parents=True, exist_ok=True)

    payload = _build_payload(output_root=output_root, run_variants=not bool(args.reuse))
    write_toml_payload(DEFAULT_CONFIG_PATH, payload)
    summary = SimulationComparisonLauncher(DEFAULT_CONFIG_PATH).run()

    print(f"Comparison root: {summary['comparison_root']}")
    print(f"Manifest: {summary['manifest_path']}")
    print(f"Report: {summary['comparison_report_md']}")
    print(f"Figures dir: {summary['comparison_figures_dir']}")
    for artifact in summary.get("comparison_figures", []):
        path = artifact.get("path")
        kind = artifact.get("kind")
        if path:
            print(f"{kind}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
