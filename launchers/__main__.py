"""Generic CLI entry-point for HydroModPy launcher families.

Usage::

    hmp simulation path/to/config.toml          # recommended
    python -m launchers simulation path/to/config.toml   # equivalent
    python -m launchers mesh-catchment run path/to/config.toml

Notes
-----
The canonical CLI is ``hmp simulation`` (defined in ``hydromodpy/__main__.py``).
``python -m launchers`` is kept as an equivalent alternative.
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
    subparsers = parser.add_subparsers(dest="command", required=True)

    sim_parser = subparsers.add_parser(
        "simulation",
        help="Run a simulation from a TOML configuration file.",
    )
    sim_parser.add_argument(
        "config",
        type=Path,
        help="Path to the simulation TOML file.",
    )

    mesh_parser = subparsers.add_parser(
        "mesh-catchment",
        help="Mesh-catchment launcher family.",
    )
    mesh_commands = mesh_parser.add_subparsers(dest="mesh_command", required=True)
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

    if parsed.command == "simulation":
        _run_simulation_launcher(parsed.config.expanduser().resolve())
        return 0

    handler = getattr(parsed, "_handler", None)
    if handler == "mesh_catchment_run":
        _run_mesh_catchment_launcher(parsed.config.expanduser().resolve())
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
