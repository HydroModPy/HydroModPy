"""``hmp catalog rerun`` - launch a run again from its frozen configuration."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.conventions import add_sim_ref, verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_USAGE, apply_verbosity, exit_code_for
from hydromodpy.core.state.paths import catalog_path_for, resolve_project_root
from hydromodpy.core.toml_io.overrides import parse_override_value

NAME: str = "rerun"
HELP: str = "Launch a run again from its frozen config.toml, with --set path=value overrides"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), verbosity_parser()],
        epilog=(
            "The new run keeps the name of its source and takes the next version;\n"
            "its manifest names the source in lineage (parent_sim_id, kind = rerun).\n"
            "A key that differs from config.resolved.toml of the source gets a warning\n"
            "and is recorded in lineage.drift.\n"
            "\n"
            "Example:\n"
            "  hmp catalog rerun baseline --set flow.param.K.field.value=2e-4"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_sim_ref(parser)
    parser.add_argument(
        "--site",
        default=None,
        help="Narrow an @-selector (@last, @best:nse) to the runs of one site",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="PATH=VALUE",
        dest="overrides",
        help="Dotted config path override, repeatable (e.g. flow.param.K.field.value=2e-4)",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Name of the new run (default: the name of the source, next version)",
    )
    parser.set_defaults(_handler=run)
    return parser


def _parse_overrides(items: list[str]) -> dict:
    """Read ``--set PATH=VALUE`` items the way ``hmp run --set`` reads them: values are TOML.

    A path under an old name reads under its current one, since the frozen config
    the overrides apply to has the current names.
    """
    from hydromodpy.config.config_migration import rewrite_dotted_path
    from hydromodpy.core.config_kit.base import warn_old_form
    from hydromodpy.core.toml_io.overrides import SET_SOURCE

    overrides: dict = {}
    for item in items:
        if "=" not in item:
            print(f"Invalid --set {item!r}; expected PATH=VALUE.", file=sys.stderr)
            sys.exit(EXIT_USAGE)
        path, _, raw = item.partition("=")
        current = rewrite_dotted_path(path.strip())
        if current != path.strip():
            warn_old_form(SET_SOURCE, f"{path.strip()} -> {current}", rewritable=False)
        overrides[current] = parse_override_value(raw)
    return overrides


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    import tomllib

    from hydromodpy.core.state.paths import parse_rel_dir
    from hydromodpy.results.catalog.discovery import resolve_rel_dir
    from hydromodpy.results.catalog.registration import run_dir_holding, split_stem_version
    from hydromodpy.results.run.rerun_contract import get_rerun_provider
    from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME
    from hydromodpy.results.trash import identity_of

    overrides = _parse_overrides(args.overrides)
    root = resolve_project_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    try:
        rel_dir = resolve_rel_dir(root, args.sim_ref, site=args.site)
        source = root / rel_dir
        frozen = source / RUN_CONFIG_FILENAME
        if not frozen.is_file():
            raise FileNotFoundError(f"{rel_dir} holds no {RUN_CONFIG_FILENAME}: nothing to rerun")
        snapshot = tomllib.loads(frozen.read_text(encoding="utf-8"))
        # The frozen config names no machine: it is read from this project.
        snapshot.setdefault("workspace", {})["project_root"] = str(root)
        name = args.name or split_stem_version(parse_rel_dir(rel_dir).name)[0]
        new_sid = str(
            get_rerun_provider().rerun(
                snapshot,
                overrides=overrides,
                name=name,
                source_sim_id=identity_of(source),
                source_dir=source,
            )
        )
    except Exception as exc:  # noqa: BLE001 - map resolver and launch errors to exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    if catalog_path_for(root).is_file():
        from hydromodpy.results.catalog.indexer import index_new_runs

        index_new_runs(root)
    print(f"reran {rel_dir} as {run_dir_holding(root, new_sid) or new_sid[:8]}  [{new_sid[:8]}]")
