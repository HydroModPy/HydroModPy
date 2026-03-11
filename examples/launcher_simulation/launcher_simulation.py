# -*- coding: utf-8 -*-
"""Example 12 simulation-launcher entry-point.

Runs the full example12 study via :class:`HydroModPyLauncher`.
Study behavior is configured directly in ``config_standard.toml``, including
launcher-managed postprocess via `[postprocess]` and `[display]`.

Usage::

    python -m examples.launcher_simulation.launcher_simulation
    python -m examples.launcher_simulation.launcher_simulation path/to/config_standard.toml

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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the launcher_simulation workflow with a TOML config.",
    )
    parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        default=Path(__file__).parent / "config_standard.toml",
        help="Path to the launcher TOML file (default: config_standard.toml).",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Run example12 launcher with a provided TOML or default local config."""
    args = _build_parser().parse_args(argv)
    config_path = args.config.expanduser().resolve()
    HydroModPyLauncher(config_path).run()


if __name__ == "__main__":
    main()
