"""``hmp display`` - render figures for one or several simulations.

Usage
-----
``hmp display <config.toml>``                  Latest run of this TOML.
``hmp display <config.toml> --run <name>``     Specific run, by its name.
``hmp display <config.toml> --sim <uuid>``     Specific run, by (short) UUID.
``hmp display <config.toml> --all``            Every run of this TOML.
``hmp display <config.toml> --latest N``       N most recent runs of this TOML.
``hmp display <config.toml> --only a,b,c``     Restrict to figures a,b,c.
``hmp display <sim_id> <figure>``              One figure for one specific sim.
``hmp display --list [--all-projects]``        Browse runs in the workspace.

Run selection filters by the ``config_source`` column (the absolute path of
the TOML that produced each run) and sorts by ``created_at DESC``, so the
behavior is deterministic regardless of DuckDB insertion order. Figures are
written to ``<project_root>/<display.output_dir>/<run_name>/``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, find_workspace_root

NAME = "display"
HELP = "Render figures for a simulation from the workspace catalog"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "config_or_subcommand",
        nargs="?",
        help="Path to a project TOML file, or a simulation id",
    )
    parser.add_argument(
        "figure_name",
        nargs="?",
        help="Figure name (when first argument is a simulation id)",
    )
    parser.add_argument(
        "--run",
        dest="run_name",
        default=None,
        metavar="NAME",
        help="Target a specific run by its name.",
    )
    parser.add_argument(
        "--sim",
        dest="sim_ref",
        default=None,
        metavar="UUID",
        help="Target a specific run by its UUID (short prefix accepted).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_runs",
        help="Render for every run originating from this TOML.",
    )
    parser.add_argument(
        "--latest",
        type=int,
        default=None,
        metavar="N",
        help="Render for the N most recent runs of this TOML.",
    )
    parser.add_argument(
        "--only",
        default=None,
        metavar="FIG1,FIG2",
        help="Restrict rendering to a comma-separated subset of figures.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_runs",
        help="List runs matching the filters and exit.",
    )
    parser.add_argument(
        "--all-projects",
        action="store_true",
        dest="all_projects",
        help="With --list, include runs from every project in the workspace.",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Force show=false in the resolved DisplayConfig",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.display import get as get_figure
    from hydromodpy.display import names as figure_names
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import (
        render_figures_for_run,
        resolve_run_output_dir,
    )
    from hydromodpy.results.catalog import (
        AmbiguousReferenceError,
        SimulationCatalog,
        SimulationNotFoundError,
    )

    target = getattr(args, "config_or_subcommand", None)
    figure_name = getattr(args, "figure_name", None)

    if args.list_runs and target is None:
        _list_runs(all_projects=args.all_projects)
        return

    if target is None:
        print(
            "Usage: hmp display <config.toml> [--run NAME | --sim UUID | --all]\n"
            "       hmp display <sim_id> <figure>\n"
            "       hmp display --list [--all-projects]\n"
            f"Available figures: {', '.join(figure_names())}",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)

    target_path = Path(target).expanduser()

    # ---- Path A: TOML-driven dispatch --------------------------------------
    if target_path.is_file() and target_path.suffix == ".toml":
        from hydromodpy.core.toml_io.loader import load_toml_with_base_config

        raw_toml = load_toml_with_base_config(target_path)
        display_cfg = DisplayConfig.model_validate(raw_toml.get("display", {}))
        if args.no_show:
            display_cfg.show = False
        project_dir = target_path.parent.resolve()
        workspace_root = find_workspace_root(project_dir)
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
                # Fall back to the project-directory filter so older runs
                # (created before `config_source` existed) remain reachable.
                sims = catalog.list_simulations(
                    project=project_dir.name,
                    order_by="created_at DESC",
                )
            if sims.empty:
                print(
                    f"No simulations found for {target_path.name}.",
                    file=sys.stderr,
                )
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
        return

    # ---- Path B: direct sim_id + figure name ------------------------------
    if figure_name is None:
        print(
            "Provide a figure name: hmp display <sim_id> <figure_name>",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)

    workspace_root = find_workspace_root(Path.cwd())
    with SimulationCatalog(workspace_root) as catalog:
        try:
            sim = catalog[target]
        except (AmbiguousReferenceError, SimulationNotFoundError) as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)
        out_dir = Path.cwd() / "figures"
        save = out_dir / f"{figure_name}.png"
        get_figure(figure_name).plot(sim, save_path=save)
        print(f"wrote {save}", file=sys.stderr)


def _select_sim_ids(sims, args: argparse.Namespace) -> list[str]:
    """Narrow the sim DataFrame (already ordered DESC) down to the target IDs."""
    if args.sim_ref:
        ref = args.sim_ref.lower()
        # accept exact match or short prefix
        matches = [
            str(sid) for sid in sims["sim_id"].astype(str) if str(sid).lower().startswith(ref)
        ]
        if not matches:
            print(f"No run matches --sim {args.sim_ref!r}.", file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)
        if len(matches) > 1:
            print(
                f"--sim {args.sim_ref!r} is ambiguous; {len(matches)} runs match. "
                "Use more hex characters.",
                file=sys.stderr,
            )
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

    # Default: most recent only.
    return [str(sims.iloc[0]["sim_id"])]


def _list_runs(*, all_projects: bool) -> None:
    import os

    from hydromodpy.results.catalog import SimulationCatalog

    ws_override = os.environ.get("HYDROMODPY_WORKSPACE")
    start = Path(ws_override).expanduser() if ws_override else Path.cwd()
    workspace_root = find_workspace_root(start)
    with SimulationCatalog(workspace_root) as catalog:
        if all_projects:
            sims = catalog.list_simulations(order_by="created_at DESC")
        else:
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
