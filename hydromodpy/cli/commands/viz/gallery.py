"""``hmp viz gallery <config.toml>`` - render the figure gallery for a run.

Renders the figures declared in ``[display]`` for one or several simulations
matched by their ``config_source`` (the TOML path that produced each run).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, find_catalog_root

NAME: str = "gallery"
HELP: str = "Render the [display] figure gallery for one or several runs"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "config",
        nargs="?",
        help="Path to a project TOML file (omit with --list)",
    )
    parser.add_argument(
        "--run", dest="run_name", default=None, metavar="NAME", help="Filter by run name"
    )
    parser.add_argument(
        "--sim", dest="sim_ref", default=None, metavar="UUID", help="Filter by sim id (or prefix)"
    )
    parser.add_argument(
        "--all", action="store_true", dest="all_runs", help="Render every matching run"
    )
    parser.add_argument(
        "--latest",
        type=int,
        default=None,
        metavar="N",
        help="Render the N most recent runs",
    )
    parser.add_argument(
        "--only",
        default=None,
        metavar="FIG1,FIG2",
        help="Comma-separated subset of figure names",
    )
    parser.add_argument(
        "--list", action="store_true", dest="list_runs", help="List matching runs and exit"
    )
    parser.add_argument(
        "--no-show", action="store_true", help="Force show=false in the resolved DisplayConfig"
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import render_figures_for_run, resolve_run_output_dir
    from hydromodpy.results.catalog import SimulationCatalog

    if args.list_runs and args.config is None:
        _list_runs()
        return

    if args.config is None:
        print(
            "Usage: hmp viz gallery <config.toml> [--run NAME | --sim UUID | --all | --latest N]",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)

    target_path = Path(args.config).expanduser()
    if not target_path.is_file() or target_path.suffix != ".toml":
        print(f"Expected a TOML file: {target_path}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    from hydromodpy.core.toml_io.loader import load_toml_with_base_config

    raw_toml = load_toml_with_base_config(target_path)
    display_cfg = DisplayConfig.model_validate(raw_toml.get("display", {}))
    if args.no_show:
        display_cfg.show = False
    project_dir = target_path.parent.resolve()
    workspace_root = project_dir
    config_source = str(target_path.resolve())

    figure_filter = None
    if args.only:
        figure_filter = [s.strip() for s in args.only.split(",") if s.strip()]

    with SimulationCatalog(workspace_root) as catalog:
        sims = catalog.list_simulations(
            config_source=config_source,
            order_by="created_at DESC",
        )
        if sims.empty:
            sims = catalog.list_simulations(
                project=project_dir.name,
                order_by="created_at DESC",
            )
        if sims.empty:
            print(f"No simulations found for {target_path.name}.", file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)

        if args.list_runs:
            _print_run_table(sims, source_label=target_path.name)
            return

        selected_ids = _select_sim_ids(sims, args)
        for sim_id in selected_ids:
            sim = catalog[sim_id]
            out_dir = resolve_run_output_dir(
                display_cfg,
                project_root=project_dir,
                run_name=sim.name,
                sim_id=sim_id,
            )
            written = render_figures_for_run(
                sim,
                display_cfg,
                output_dir=out_dir,
                figure_names=figure_filter,
            )
            for path in written:
                print(f"  wrote {path}", file=sys.stderr)


def _select_sim_ids(sims, args: argparse.Namespace) -> list[str]:
    if args.sim_ref:
        ref = args.sim_ref.lower()
        matches = [
            str(sid) for sid in sims["sim_id"].astype(str) if str(sid).lower().startswith(ref)
        ]
        if not matches:
            print(f"No run matches --sim {args.sim_ref!r}.", file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)
        if len(matches) > 1:
            print(f"--sim {args.sim_ref!r} is ambiguous.", file=sys.stderr)
            sys.exit(EXIT_CONFIG)
        return matches

    if args.run_name:
        subset = sims[sims["name"] == args.run_name]
        if subset.empty:
            print(f"No run named {args.run_name!r}.", file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)
        return [str(sid) for sid in subset["sim_id"].tolist()]

    if args.all_runs:
        return [str(sid) for sid in sims["sim_id"].tolist()]

    if args.latest is not None and args.latest > 0:
        return [str(sid) for sid in sims["sim_id"].tolist()[: args.latest]]

    return [str(sims.iloc[0]["sim_id"])]


def _list_runs() -> None:
    import os

    from hydromodpy.results.catalog import SimulationCatalog

    ws_override = os.environ.get("HMP_WORKSPACE")
    start = Path(ws_override).expanduser() if ws_override else Path.cwd()
    workspace_root = find_catalog_root(start)
    with SimulationCatalog(workspace_root) as catalog:
        sims = catalog.list_simulations(
            project=Path.cwd().name,
            order_by="created_at DESC",
        )
    if sims.empty:
        print("No simulations found.", file=sys.stderr)
        return
    _print_run_table(sims)


def _print_run_table(sims, *, source_label: str | None = None) -> None:
    columns = [
        c for c in ("sim_id", "name", "status", "created_at", "config_source") if c in sims.columns
    ]
    header = source_label or "runs"
    print(f"# {header} ({len(sims)} total, sorted by created_at DESC)")
    for _, row in sims[columns].iterrows():
        sid = str(row.get("sim_id", ""))[:8]
        name = row.get("name") or "(unnamed)"
        status = row.get("status", "?")
        created = str(row.get("created_at", ""))
        src = row.get("config_source") or ""
        src_tail = Path(src).name if src else ""
        print(f"  {sid}  {status:<10}  {created}  {name:<24}  {src_tail}")
