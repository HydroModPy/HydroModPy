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
from typing import Any


def _run_simulation_launcher(config_path: Path) -> None:
    """Execute the simulation launcher for one TOML configuration path."""
    from launchers import HydroModPyLauncher

    HydroModPyLauncher(config_path).run()


def _collect_mesh_catchment_figures(summary: Any) -> list[str]:
    """Extract created figure paths from one mesh-catchment launcher summary."""
    if not isinstance(summary, dict):
        return []

    mode = str(summary.get("mode", "")).strip().lower()
    if mode == "batch":
        figures: list[str] = []
        for row in summary.get("results", ()):
            if not isinstance(row, dict):
                continue
            figure_path = str(row.get("output_figure", "")).strip()
            if figure_path != "":
                figures.append(figure_path)
        return figures

    figure_path = str(summary.get("output_figure", "")).strip()
    if figure_path == "":
        return []
    return [figure_path]


def _print_mesh_catchment_figures(summary: Any) -> None:
    """Print created figure paths at the end of one mesh-catchment CLI run."""
    figures = _collect_mesh_catchment_figures(summary)
    if not figures:
        return
    print("")
    print("Created figures:")
    for figure_path in figures:
        print(f"  {figure_path}")


def _run_mesh_catchment_launcher(config_path: Path) -> None:
    """Execute the mesh-catchment launcher for one TOML configuration path."""
    from launchers import MeshCatchmentLauncher

    summary = MeshCatchmentLauncher(config_path).run()
    _print_mesh_catchment_figures(summary)


def _render_mesh_catchment_template(
    *,
    batch: bool,
    profile: str,
    output_path: Path | None,
) -> None:
    """Render one canonical mesh-catchment TOML template."""
    from launchers.mesh_catchment.templates import (
        render_mesh_catchment_template,
        write_mesh_catchment_template,
    )

    if output_path is None:
        sys.stdout.write(
            render_mesh_catchment_template(batch=batch, profile=profile)
        )
        return

    write_mesh_catchment_template(
        output_path=output_path,
        batch=batch,
        profile=profile,
    )
    print(f"Wrote template: {output_path}")


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
    mesh_template = mesh_commands.add_parser(
        "template",
        help="Render a canonical TOML template derived from Pydantic schemas.",
    )
    mesh_template.add_argument(
        "--batch",
        action="store_true",
        help="Include the optional [mesh_catchment_batch] section.",
    )
    mesh_template.add_argument(
        "--profile",
        choices=("user", "dev", "expert"),
        default="user",
        help="Visibility profile forwarded to the generic TOML generator.",
    )
    mesh_template.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output path. When omitted, print the template to stdout.",
    )
    mesh_template.set_defaults(_handler="mesh_catchment_template")

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
    if handler == "mesh_catchment_template":
        output_path = None
        if parsed.output is not None:
            output_path = parsed.output.expanduser().resolve()
        _render_mesh_catchment_template(
            batch=bool(parsed.batch),
            profile=str(parsed.profile),
            output_path=output_path,
        )
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
