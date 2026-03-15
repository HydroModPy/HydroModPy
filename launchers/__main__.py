"""Generic CLI entry-point for HydroModPy launcher families.

Usage::

    python -m launchers simulation run path/to/config.toml
    python -m launchers mesh-catchment run path/to/config.toml

Notes
-----
This module is a shared wrapper and is intentionally not study-specific.
For one explicit study launcher, use:
``python -m examples.launcher_simulation.launcher_simulation``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _run_simulation_launcher(config_path: Path) -> None:
    """Execute the simulation launcher for one TOML configuration path."""
    from launchers import HydroModPyLauncher

    HydroModPyLauncher(config_path).run()


def _run_mesh_catchment_launcher(config_path: Path) -> None:
    """Execute the mesh-catchment launcher for one TOML configuration path."""
    from launchers import MeshCatchmentLauncher

    MeshCatchmentLauncher(config_path).run()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m launchers",
        description="HydroModPy launchers CLI.",
    )
    launchers_parser = parser.add_subparsers(dest="launcher", required=True)

    simulation_parser = launchers_parser.add_parser(
        "simulation",
        help="Simulation launcher family.",
    )
    simulation_commands = simulation_parser.add_subparsers(dest="command", required=True)
    simulation_run = simulation_commands.add_parser(
        "run",
        help="Run one simulation launcher TOML.",
    )
    simulation_run.add_argument(
        "config",
        type=Path,
        help="Path to launcher TOML file.",
    )
    simulation_run.set_defaults(_handler="simulation_run")

    mesh_parser = launchers_parser.add_parser(
        "mesh-catchment",
        help="Mesh-catchment launcher family.",
    )
    mesh_commands = mesh_parser.add_subparsers(dest="command", required=True)
    mesh_run = mesh_commands.add_parser(
        "run",
        help="Run one mesh-catchment launcher TOML.",
    )
    mesh_run.add_argument(
        "config",
        type=Path,
        help="Path to launcher TOML file.",
    )
    mesh_run.set_defaults(_handler="mesh_catchment_run")
    return parser


def main(argv: list[str] | None = None) -> int:
    args_raw = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser()

    try:
        parsed = parser.parse_args(args_raw)
    except SystemExit as exc:
        return int(exc.code)

    if parsed._handler == "simulation_run":
        _run_simulation_launcher(parsed.config.expanduser().resolve())
        return 0
    if parsed._handler == "mesh_catchment_run":
        _run_mesh_catchment_launcher(parsed.config.expanduser().resolve())
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
