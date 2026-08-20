"""Run and score a small real MF6 B0 parameter grid.

This stays local to the B0 prototype.  It deliberately orchestrates two
standard HydroModPy simulations per parameter pair instead of extending the
global calibration API before the B0 contract has stabilized.
"""

# ruff: noqa: E402,I001

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.results.catalog import Catalog  # noqa: E402

from score_candidate_table import load_candidate_specs, score_candidate_specs  # noqa: E402


ROOT = Path(__file__).resolve().parent
SOURCE_TRANSIENT_CONFIG = (
    REPO_ROOT
    / "examples"
    / "projects"
    / "10_testbed_workflow"
    / "boussinesq"
    / "natural_geology_k"
    / "base_site_01_mf6_bouss_transient.toml"
)
SOURCE_K_CSV = REPO_ROOT / "data" / "geology" / "geology_K_dummy_demo.csv"
if not SOURCE_K_CSV.is_file():
    SOURCE_K_CSV = REPO_ROOT / "examples" / "data" / "geology" / "geology_K_dummy_demo.csv"
REAL_ROOT = ROOT / "outputs" / "real_runs"
CONFIG_ROOT = REAL_ROOT / "configs"
TRUTH_DIR = REAL_ROOT / "site_01_truth_package_mK_0p65"
GRID_CANDIDATES_CSV = REAL_ROOT / "site_01_parameter_grid_candidates_mK_0p65.csv"
GRID_SCORES_CSV = REAL_ROOT / "site_01_parameter_grid_scores_mK_0p65.csv"
GRID_SCORES_JSON = REAL_ROOT / "site_01_parameter_grid_scores_mK_0p65.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mk-values",
        nargs="+",
        type=float,
        default=[0.50, 0.60, 0.65, 0.70, 0.75],
        help="mK grid values.",
    )
    parser.add_argument(
        "--sy-values",
        nargs="+",
        type=float,
        default=[0.03, 0.05, 0.08, 0.12],
        help="Sy grid values.",
    )
    parser.add_argument(
        "--skip-runs",
        action="store_true",
        help="Only rebuild the candidate table and scores from already completed runs.",
    )
    parser.add_argument(
        "--max-new-runs",
        type=int,
        default=None,
        help="Stop after launching this many missing steady/transient runs.",
    )
    args = parser.parse_args(argv)

    CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
    launched = 0
    timings: list[dict[str, Any]] = []
    for mk in args.mk_values:
        if not args.skip_runs and not _catalog_ready(_steady_root(mk)):
            launched += _run_limited(
                _launch_steady(mk, timings),
                launched=launched,
                limit=args.max_new_runs,
            )
        for sy in args.sy_values:
            if args.skip_runs or _catalog_ready(_transient_root(mk, sy)):
                continue
            launched += _run_limited(
                _launch_transient(mk, sy, timings),
                launched=launched,
                limit=args.max_new_runs,
            )

    candidate_rows = _write_candidate_table(args.mk_values, args.sy_values)
    frame = score_candidate_specs(load_candidate_specs(GRID_CANDIDATES_CSV), truth_dir=TRUTH_DIR)
    frame.to_csv(GRID_SCORES_CSV, index=False)
    GRID_SCORES_JSON.write_text(
        json.dumps(frame.to_dict(orient="records"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if timings:
        timing_path = REAL_ROOT / "site_01_parameter_grid_timings_mK_0p65.json"
        timing_path.write_text(
            json.dumps(timings, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    completed = frame[frame["status"] == "completed"] if "status" in frame else frame.iloc[0:0]
    print(f"Wrote candidates: {GRID_CANDIDATES_CSV} ({len(candidate_rows)} rows)")
    print(f"Wrote scores: {GRID_SCORES_CSV}")
    print(f"Completed: {len(completed)} / {len(frame)}")
    if not completed.empty:
        best = completed.iloc[0]
        print(
            "Best: "
            f"{best['candidate_id']} J={float(best['objective']):.12g} "
            f"mK={float(best['mK']):.6g} Sy={float(best['Sy']):.6g}"
        )
    return 0


def _run_limited(did_run: bool, *, launched: int, limit: int | None) -> int:
    if not did_run:
        return 0
    if limit is not None and launched + 1 >= limit:
        raise SystemExit("Reached --max-new-runs limit after completing the latest run.")
    return 1


def _launch_steady(mk: float, timings: list[dict[str, Any]]) -> bool:
    root = _steady_root(mk)
    overlay = _write_steady_overlay(mk)
    return _run_hmp(
        "steady",
        _tag(mk, 0.05),
        root,
        overlay,
        timings,
    )


def _launch_transient(mk: float, sy: float, timings: list[dict[str, Any]]) -> bool:
    root = _transient_root(mk, sy)
    overlay = _write_transient_overlay(mk, sy)
    return _run_hmp(
        "transient",
        _tag(mk, sy),
        root,
        overlay,
        timings,
    )


def _run_hmp(
    kind: str,
    tag: str,
    workspace: Path,
    overlay: Path,
    timings: list[dict[str, Any]],
) -> bool:
    if _catalog_ready(workspace):
        return False
    cmd = [
        sys.executable,
        "-m",
        "hydromodpy.cli.main",
        "run",
        str(SOURCE_TRANSIENT_CONFIG),
        "--overlay",
        str(overlay),
        "--set",
        f"workspace.project_root={workspace}",
        "--no-display",
    ]
    print(f"[{kind}] launching {tag} -> {workspace}")
    start = time.perf_counter()
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)
    elapsed = time.perf_counter() - start
    timings.append(
        {
            "kind": kind,
            "tag": tag,
            "workspace": str(_relative_or_abs(workspace)),
            "seconds": elapsed,
        }
    )
    print(f"[{kind}] completed {tag} in {elapsed:.1f} s")
    return True


def _write_candidate_table(mk_values: list[float], sy_values: list[float]) -> list[dict[str, str]]:
    rows = []
    for mk in mk_values:
        for sy in sy_values:
            if not _catalog_ready(_steady_root(mk)) or not _catalog_ready(_transient_root(mk, sy)):
                continue
            cid = (
                f"truth_{_tag(mk, sy)}"
                if abs(mk - 0.65) < 1e-12 and abs(sy - 0.05) < 1e-12
                else _tag(mk, sy)
            )
            rows.append(
                {
                    "candidate_id": cid,
                    "mK": f"{mk:.6g}",
                    "Sy": f"{sy:.6g}",
                    "steady_catalog": str(_relative_or_abs(_steady_root(mk))),
                    "steady_ref": "run_0001",
                    "transient_catalog": str(_relative_or_abs(_transient_root(mk, sy))),
                    "transient_ref": "run_0001",
                }
            )
    with GRID_CANDIDATES_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "candidate_id",
                "mK",
                "Sy",
                "steady_catalog",
                "steady_ref",
                "transient_catalog",
                "transient_ref",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    return rows


def _write_steady_overlay(mk: float) -> Path:
    k_csv = _write_k_csv(mk)
    tag = _tag(mk, 0.05)
    path = CONFIG_ROOT / f"{tag}_steady_grid_overlay.toml"
    path.write_text(
        "\n".join(
            [
                "[simulation]",
                f'name = "b0_{tag}_steady_mf6"',
                f'run_id = "b0_{tag}_steady_mf6"',
                "",
                "[simulation.time]",
                'start_datetime = "2000-09-01"',
                'end_datetime = "2000-09-30"',
                'step_value = "1 month"',
                'coverage_policy = "warn"',
                "",
                "[data.recharge]",
                'date_start = "2000-09-01"',
                'date_end = "2000-09-30"',
                "",
                "[[data.recharge.sources]]",
                'source = "synthetic"',
                'freq = "MS"',
                'start_date = "2000-09-01"',
                "periods = 1",
                "values = [0.6629166666666667]",
                "runoff_ratio = 0.0",
                "",
                "[flow]",
                'flow_regime = "steady"',
                'active_sinks_sources = ["recharge"]',
                'active_bc = ["drainage"]',
                "",
                "[flow.ic]",
                'type = "top"',
                "",
                "[flow.param.K.field]",
                f'values_csv_file = "{k_csv.as_posix()}"',
                "",
                "[flow.param.Sy.field]",
                'value = "0.05 -"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _write_transient_overlay(mk: float, sy: float) -> Path:
    k_csv = _write_k_csv(mk)
    tag = _tag(mk, sy)
    path = CONFIG_ROOT / f"{tag}_transient_grid_overlay.toml"
    path.write_text(
        "\n".join(
            [
                "[simulation]",
                f'name = "b0_{tag}_transient_mf6"',
                f'run_id = "b0_{tag}_transient_mf6"',
                "",
                "[flow.param.K.field]",
                f'values_csv_file = "{k_csv.as_posix()}"',
                "",
                "[flow.param.Sy.field]",
                f'value = "{sy:.8g} -"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _write_k_csv(mk: float) -> Path:
    out = CONFIG_ROOT / f"geology_K_dummy_demo_{_mk_tag(mk)}.csv"
    if out.is_file():
        return out
    with SOURCE_K_CSV.open("r", encoding="utf-8-sig", newline="") as src:
        reader = csv.DictReader(src)
        if reader.fieldnames is None or "K_value" not in reader.fieldnames:
            raise ValueError(f"Missing K_value column in {SOURCE_K_CSV}")
        rows = []
        for row in reader:
            row = dict(row)
            row["K_value"] = f"{float(row['K_value']) * mk:.16g}"
            rows.append(row)
    with out.open("w", encoding="utf-8", newline="") as dst:
        writer = csv.DictWriter(dst, fieldnames=reader.fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return out


def _catalog_ready(root: Path) -> bool:
    try:
        if not root.exists():
            return False
        with Catalog(root) as catalog:
            return not catalog.simulations.empty
    except Exception:
        return False


def _steady_root(mk: float) -> Path:
    return REAL_ROOT / f"candidate_{_mk_tag(mk)}_Sy_0p05_steady_mf6"


def _transient_root(mk: float, sy: float) -> Path:
    return REAL_ROOT / f"candidate_{_tag(mk, sy)}_transient_mf6"


def _tag(mk: float, sy: float) -> str:
    return f"{_mk_tag(mk)}_{_sy_tag(sy)}"


def _mk_tag(mk: float) -> str:
    return f"mK_{mk:.2f}".replace(".", "p")


def _sy_tag(sy: float) -> str:
    return f"Sy_{sy:.2f}".replace(".", "p")


def _relative_or_abs(path: Path) -> Path:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        return path.resolve()


if __name__ == "__main__":
    raise SystemExit(main())
