"""``hmp display`` — render figures for a simulation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy._cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, find_workspace_root


NAME = "display"
HELP = "Render figures for a simulation from the workspace catalog"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "config_or_subcommand", nargs="?",
        help="Path to a project TOML file, or a simulation id",
    )
    parser.add_argument(
        "figure_name", nargs="?",
        help="Figure name (when first argument is a simulation id)",
    )
    parser.add_argument(
        "--no-show", action="store_true",
        help="Force show=false in the resolved DisplayConfig",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    import tomllib

    from hydromodpy.display import get as get_figure, names as figure_names
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.results.catalog import SimulationCatalog

    target = getattr(args, "config_or_subcommand", None)
    figure_name = getattr(args, "figure_name", None)

    if target is None:
        print(
            "Usage: hmp display <config.toml>\n"
            "       hmp display <sim_id> <figure>\n"
            f"Available figures: {', '.join(figure_names())}",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)

    target_path = Path(target).expanduser()

    if target_path.is_file() and target_path.suffix == ".toml":
        with target_path.open("rb") as f:
            raw_toml = tomllib.load(f)
        display_cfg = DisplayConfig.model_validate(raw_toml.get("display", {}))
        if args.no_show:
            display_cfg.show = False
        project_dir = target_path.parent.resolve()
        workspace_root = find_workspace_root(project_dir)
        out_dir = (project_dir / display_cfg.output_dir).resolve()
        with SimulationCatalog(workspace_root) as catalog:
            sims = catalog.list_simulations(project=project_dir.name)
            if sims.empty:
                print("No simulations found in catalog.", file=sys.stderr)
                sys.exit(EXIT_NOT_FOUND)
            sim_id = str(sims.iloc[-1]["sim_id"])
            sim = catalog[sim_id]
            wanted = display_cfg.figures or sim.display_capabilities
            for name in wanted:
                try:
                    fig = get_figure(name)
                except KeyError:
                    print(f"  skipping unknown figure '{name}'", file=sys.stderr)
                    continue
                save = (out_dir / f"{name}.png") if display_cfg.save else None
                fig.plot(sim, dpi=display_cfg.dpi, save_path=save)
                if save:
                    print(f"  wrote {save}", file=sys.stderr)
        return

    if figure_name is None:
        print(
            "Provide a figure name: hmp display <sim_id> <figure_name>",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)

    workspace_root = find_workspace_root(Path.cwd())
    with SimulationCatalog(workspace_root) as catalog:
        sim = catalog[target]
        out_dir = Path.cwd() / "figures"
        save = out_dir / f"{figure_name}.png"
        get_figure(figure_name).plot(sim, save_path=save)
        print(f"wrote {save}", file=sys.stderr)
