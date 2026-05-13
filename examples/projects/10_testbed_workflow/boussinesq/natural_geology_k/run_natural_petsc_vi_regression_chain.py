"""Run the PETSc vi_obstacle natural MF6/Boussinesq regression chain."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from hydromodpy.analysis.comparison.experiment_launcher import SimulationComparisonLauncher
from hydromodpy.analysis.testbed.runtime import TestbedLauncher

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
TESTBED_CONFIG = HERE / "natural_petsc_vi_regression_testbed.toml"
OUTPUT_ROOT = (
    REPO_ROOT
    / "examples"
    / "projects"
    / "10_testbed_workflow"
    / "outputs"
    / "boussinesq_petsc_vi_regression_testbed"
)
GENERATED_CONFIGS = OUTPUT_ROOT / "_generated_configs"
REPORT_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "projects"
    / "10_testbed_workflow"
    / "reporting"
    / "generate_testbed_web_report.py"
)
REPORT_TITLE = "Boussinesq PETSc vi_obstacle natural regression testbed"
SITE_ID_RE = re.compile(r"^(site_\d+|headwater_100km2_outlet_\d+|s3_100km2_outlet_\d+)$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sites",
        nargs="+",
        help=(
            "Site ids to process, for example: --sites site_03 "
            "headwater_100km2_outlet_2. Defaults to all generated configs."
        ),
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Only materialize comparison TOMLs and testbed manifests.",
    )
    parser.add_argument(
        "--html-only",
        action="store_true",
        help="Only rebuild the testbed synthesis HTML from existing comparison outputs.",
    )
    parser.add_argument(
        "--reuse-runs",
        action="store_true",
        help="Reuse existing child run folders and rerun comparison extraction/HTML only.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue with later sites after a site-level launcher failure.",
    )
    return parser


def _ensure_plan() -> dict[str, Any]:
    return TestbedLauncher(TESTBED_CONFIG).run()


def _site_ids(selected: list[str] | None) -> list[str]:
    if selected:
        return selected
    if not GENERATED_CONFIGS.is_dir():
        raise FileNotFoundError(f"Generated config directory not found: {GENERATED_CONFIGS}")
    return sorted(
        path.stem for path in GENERATED_CONFIGS.glob("*.toml") if SITE_ID_RE.match(path.stem)
    )


def _run_comparison(config_path: Path, *, reuse_runs: bool) -> dict[str, object]:
    launcher = SimulationComparisonLauncher(config_path)
    if reuse_runs:
        launcher.cfg.comparison.execution.run_simulations = False
    return launcher.run()


def _write_testbed_html() -> Path:
    subprocess.run(
        [
            sys.executable,
            str(REPORT_SCRIPT),
            str(OUTPUT_ROOT),
            "--title",
            REPORT_TITLE,
        ],
        cwd=REPO_ROOT,
        check=True,
    )
    return OUTPUT_ROOT / "web_synthesis" / "index.html"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    failures: list[tuple[str, str]] = []
    if not args.html_only:
        summary = _ensure_plan()
        print(
            "Plan materialized: "
            f"{summary.get('variant_count', '')} variants, "
            f"configs={summary.get('generated_configs_dir', '')}"
        )
        if args.plan_only:
            return 0

        for site_id in _site_ids(args.sites):
            config_path = GENERATED_CONFIGS / f"{site_id}.toml"
            if not config_path.is_file():
                raise FileNotFoundError(f"Generated comparison config not found: {config_path}")
            try:
                manifest = _run_comparison(config_path, reuse_runs=bool(args.reuse_runs))
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                failures.append((site_id, message))
                print(f"{site_id}: failed {message}", file=sys.stderr)
                if not args.continue_on_error:
                    raise
                continue
            print(
                f"{site_id}: audit={manifest.get('audit_status', '')} "
                f"root={manifest.get('comparison_root', '')}"
            )

    page = _write_testbed_html()
    print(f"Testbed synthesis page: {page}")
    if failures:
        print("Failed site-level launchers:", file=sys.stderr)
        for site_id, message in failures:
            print(f"- {site_id}: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
