"""``hmp project show`` - print a project summary (catalog stats, TOML inventory)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_NOT_FOUND
from hydromodpy.core.state.paths import CATALOG_FILENAME, PROJECT_TOML_FILENAME

NAME: str = "show"
HELP: str = "Show a project summary (TOMLs, catalog stats)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("project", help="Project name (directory under projects/)")
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace root (default: walk up from cwd, fallback ~/hydromodpy/)",
    )
    parser.set_defaults(_handler=run)
    return parser


def _resolve_workspace(workspace_arg: str | None) -> Path:
    import os

    from hydromodpy.cli.helpers import find_workspace_root
    from hydromodpy.data.scaffold import DEFAULT_ROOT

    if workspace_arg:
        return Path(workspace_arg).expanduser().resolve()
    ws_override = os.environ.get("HMP_WORKSPACE")
    start = Path(ws_override).expanduser().resolve() if ws_override else Path.cwd()
    found = find_workspace_root(start)
    if (found / "projects").is_dir() or (found / "data").is_dir():
        return found
    return Path(DEFAULT_ROOT).expanduser().resolve()


def run(args: argparse.Namespace) -> None:
    workspace_root = _resolve_workspace(args.workspace)
    project_dir = workspace_root / "projects" / args.project
    if not project_dir.is_dir():
        print(f"No such project: {project_dir}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    print(f"# project: {args.project}")
    print(f"# path   : {project_dir}")

    project_toml = project_dir / PROJECT_TOML_FILENAME
    print(f"  {PROJECT_TOML_FILENAME:<24} {'present' if project_toml.exists() else 'missing'}")

    run_tomls = sorted(project_dir.glob("run_*.toml"))
    if run_tomls:
        print(f"  run TOMLs ({len(run_tomls)}):")
        for path in run_tomls:
            print(f"    - {path.name}")

    db_path = project_dir / CATALOG_FILENAME
    if db_path.exists():
        try:
            from hydromodpy.results.catalog import SimulationCatalog, short_id

            with SimulationCatalog(project_dir) as catalog:
                sims = catalog.list_simulations(order_by="created_at DESC")
                print(f"  simulations: {len(sims)}")
                for _, row in sims.head(10).iterrows():
                    sim_id = str(row["sim_id"])
                    name = row.get("name", "") or "(no name)"
                    solver = row.get("solver", "")
                    status = row.get("status", "")
                    print(f"    - {name}  [{short_id(sim_id)}]  solver={solver}  status={status}")
                if len(sims) > 10:
                    print(f"    ... {len(sims) - 10} more (use 'hmp catalog ls')")
        except Exception as exc:
            print(f"  Error reading project catalog: {exc}", file=sys.stderr)
    else:
        print(f"  {CATALOG_FILENAME:<24} missing")
