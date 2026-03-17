# -*- coding: utf-8 -*-
"""Example 12 simulation-launcher entry-point.

Runs the full example12 study via :class:`HydroModPyLauncher`.
Study behavior is configured directly in ``run_extensive_nwt.toml``. This
default keeps the historical long-run NWT/MT3DMS baseline behavior, including
launcher-managed postprocess via `[postprocess]` and `[display]`.

Usage::

    python -m examples.launcher_simulation.launcher_simulation
    python -m examples.launcher_simulation.launcher_simulation path/to/run_extensive_nwt.toml

The explicit module path above is the recommended command for this study-level
launcher. The generic wrapper supports the explicit launcher-family form
``python -m launchers simulation run ...``.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# When this file is executed directly by path, Python adds the script folder to
# ``sys.path`` but not necessarily the repository root. Insert the repo root
# explicitly so the local ``launchers`` package can always be imported.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from launchers import HydroModPyLauncher


DEFAULT_CONFIG_NAME = "run_extensive_nwt.toml"
LEGACY_CONFIG_NAME = "config_standard.toml"


def _resolve_config_path(config: Path) -> Path:
    """Resolve the requested config path and report the legacy rename clearly."""
    resolved = config.expanduser().resolve()
    if resolved.exists():
        return resolved

    if resolved.name != LEGACY_CONFIG_NAME:
        return resolved

    replacement = resolved.with_name(DEFAULT_CONFIG_NAME)
    if replacement.exists():
        raise FileNotFoundError(
            f"'{LEGACY_CONFIG_NAME}' was renamed to '{DEFAULT_CONFIG_NAME}'. "
            f"Use this path instead: {replacement}"
        )
    return resolved


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the launcher_simulation workflow with a TOML config.",
    )
    parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        default=Path(__file__).parent / DEFAULT_CONFIG_NAME,
        help=f"Path to the launcher TOML file (default: {DEFAULT_CONFIG_NAME}).",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Run example12 launcher with a provided TOML or default local config."""
    args = _build_parser().parse_args(argv)
    config_path = _resolve_config_path(args.config)
    HydroModPyLauncher(config_path).run()


if __name__ == "__main__":
    main()
