"""Run the natural N1 10 km2 MF6/Boussinesq comparison chain."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from hydromodpy.analysis.comparison.experiment_launcher import SimulationComparisonLauncher

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
OUTPUT_ROOT = (
    REPO_ROOT
    / "examples"
    / "projects"
    / "10_testbed_workflow"
    / "outputs"
    / "boussinesq_natural_n1_10km2_testbed"
)
GENERATED_CONFIGS = OUTPUT_ROOT / "_generated_configs"
REPORT_SCRIPT = (
    REPO_ROOT / "examples" / "projects" / "10_testbed_workflow" / "reporting"
    / "generate_testbed_web_report.py"
)
REPORT_TITLE = "Boussinesq/MODFLOW6 natural N1 10km2 regional-lab testbed"
SITE_ID_RE = re.compile(r"site_\d+$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sites",
        nargs="+",
        help="Site ids to process, for example: --sites site_03 site_08. Defaults to all generated site_XX configs.",
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
    return parser


def _site_ids(selected: list[str] | None) -> list[str]:
    if selected:
        return selected
    if not GENERATED_CONFIGS.is_dir():
        raise FileNotFoundError(f"Generated config directory not found: {GENERATED_CONFIGS}")
    return sorted(path.stem for path in GENERATED_CONFIGS.glob("*.toml") if SITE_ID_RE.match(path.stem))


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
    site_ids = _site_ids(args.sites)
    manifests: list[dict[str, object]] = []

    if not args.html_only:
        for site_id in site_ids:
            config_path = GENERATED_CONFIGS / f"{site_id}.toml"
            if not config_path.is_file():
                raise FileNotFoundError(f"Generated comparison config not found: {config_path}")
            manifest = _run_comparison(config_path, reuse_runs=bool(args.reuse_runs))
            manifests.append(manifest)
            print(
                f"{site_id}: audit={manifest.get('audit_status', '')} "
                f"root={manifest.get('comparison_root', '')}"
            )

    page = _write_testbed_html()
    print(f"Testbed synthesis page: {page}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
