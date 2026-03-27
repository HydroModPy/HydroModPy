"""Launcher for catchment-identification annex workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Support direct execution from file path and ensure local package precedence.
_repo_root = Path(__file__).resolve()
for _parent in _repo_root.parents:
    if (_parent / "hydromodpy").exists():
        if str(_parent) not in sys.path:
            sys.path.insert(0, str(_parent))
        break

from hydromodpy_annex.preprocess.catchment_identification_scan.config import (  # noqa: E402
    DEFAULT_CONFIG_FILE,
    DEFAULT_SECTION,
    CatchmentIdentificationConfig,
)
from hydromodpy_annex.preprocess.catchment_identification_scan.workflow import (  # noqa: E402
    run_catchment_identification_from_toml,
)

__all__ = [
    "DEFAULT_CONFIG_FILE",
    "DEFAULT_SECTION",
    "CatchmentIdentificationConfig",
    "run_catchment_identification_from_toml",
    "main",
]


def _format_cli_summary(
    summary: dict,
    *,
    compact: bool,
    summary_json_path: Path | None = None,
) -> str:
    """Render one CLI summary string suited to direct terminal execution."""
    if not compact:
        return json.dumps(summary, indent=2, ensure_ascii=True)

    lines = [
        (
            "Catchment identification completed: "
            f"basins={int(summary.get('basins_count', 0))}; "
            f"outlets={int(summary.get('outlets_count', 0))}; "
            f"candidates={int(summary.get('outlet_candidates_count', 0))}"
        )
    ]
    output_dir = summary.get("output_dir")
    if output_dir:
        lines.append(f"output_dir: {output_dir}")
    outlets_csv_path = summary.get("outlets_csv_path")
    if outlets_csv_path:
        lines.append(f"outlets_csv_path: {outlets_csv_path}")
    if summary_json_path is not None:
        lines.append(
            f"summary_json_path: {summary_json_path.expanduser().resolve()}"
        )
    figures_dir = summary.get("figures_dir")
    if figures_dir:
        lines.append(f"figures_dir: {figures_dir}")
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Identify all catchments above one accumulation-area threshold from a DEM, "
            "with GeoPackage/CSV export and diagnostic figures."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name(DEFAULT_CONFIG_FILE),
        help="Path to TOML configuration file.",
    )
    parser.add_argument(
        "--section",
        type=str,
        default=DEFAULT_SECTION,
        help=f"TOML section to load (default: {DEFAULT_SECTION}).",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional output path for summary JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = run_catchment_identification_from_toml(
        args.config,
        section=args.section,
        output_json=args.output_json,
    )
    print(
        _format_cli_summary(
            summary,
            compact=(args.output_json is not None),
            summary_json_path=args.output_json,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
