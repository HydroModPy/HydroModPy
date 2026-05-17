"""Run the Nancon network physical benchmark and build its compact HTML page."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hydromodpy.analysis.comparison.experiment_launcher import SimulationComparisonLauncher

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "compare_nancon_network_physical_benchmark.toml"


def _build_html() -> Path:
    import build_nancon_network_synthesis

    return build_nancon_network_synthesis.build_page()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--html-only",
        action="store_true",
        help="Rebuild the compact HTML page from existing outputs without running simulations.",
    )
    parser.add_argument(
        "--reuse-runs",
        action="store_true",
        help="Reuse existing run folders, rerun comparison extraction, then rebuild HTML.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the comparison manifest as JSON after execution.",
    )
    args = parser.parse_args(argv)

    manifest = None
    if not args.html_only:
        launcher = SimulationComparisonLauncher(CONFIG)
        if args.reuse_runs:
            launcher.cfg.comparison.execution.run_simulations = False
        manifest = launcher.run()

    page = _build_html()
    print(f"Synthesis page: {page}")
    if manifest is not None:
        print(f"Comparison root: {manifest.get('comparison_root', '')}")
        print(f"Audit status: {manifest.get('audit_status', '')}")
        if args.print_json:
            print(json.dumps(manifest, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
