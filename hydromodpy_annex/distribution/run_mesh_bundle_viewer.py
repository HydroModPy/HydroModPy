"""Direct script entrypoint for the annex mesh-bundle viewer."""

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

from hydromodpy_annex.distribution.mesh_bundle_viewer import (  # noqa: E402
    DEFAULT_CONFIG_FILE,
    DEFAULT_SECTION,
    run_mesh_bundle_viewer_from_toml,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Load one exported catchment-mesh bundle, display it, and optionally "
            "write one figure and one JSON summary."
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
        help="Optional override path for the JSON summary.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = run_mesh_bundle_viewer_from_toml(
        args.config,
        section=args.section,
        output_json=args.output_json,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
