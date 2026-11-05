"""``hmp catalog tag`` - add or remove tags on a run, in its ``annotations.json``."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import (
    add_sim_ref,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import EXIT_USAGE, apply_verbosity, project_root_of, refuse
from hydromodpy.cli.output import emit
from hydromodpy.core.state.layout import catalog_path_for

NAME: str = "tag"
HELP: str = "Add or remove tags on a run (reserved tag: pinned, kept out of trash and gc)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog="Example:\n  hmp catalog tag baseline.v2 pinned paper --rm draft",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_sim_ref(parser)
    parser.add_argument(
        "--site",
        default=None,
        help="Narrow an @-selector (@last, @best:nse) to the runs of one site",
    )
    parser.add_argument(
        "add_tags",
        nargs="*",
        metavar="TAG",
        help="Tags to add (a leading + is optional)",
    )
    parser.add_argument(
        "--rm",
        action="append",
        default=[],
        metavar="TAG",
        help="Tag to remove (repeatable)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.results.annotations import add_tag, read_annotations, remove_tag
    from hydromodpy.results.catalog.discovery import resolve_rel_dir

    add = tuple(dict.fromkeys(t.lstrip("+") for t in args.add_tags))
    remove = tuple(dict.fromkeys(args.rm))
    if not add and not remove:
        refuse("Nothing to do: pass tags to add or --rm TAG to remove.", EXIT_USAGE)

    root = project_root_of(args)
    rel_dir = resolve_rel_dir(root, args.sim_ref, site=args.site)
    run_dir = root / rel_dir
    before = read_annotations(run_dir).tags
    for tag in add:
        add_tag(run_dir, tag)
    for tag in remove:
        remove_tag(run_dir, tag)
    after = read_annotations(run_dir).tags
    added = [tag for tag in after if tag not in before]
    removed = [tag for tag in before if tag not in after]
    if (added or removed) and catalog_path_for(root).is_file():
        from hydromodpy.results.catalog.indexer import index_new_runs

        index_new_runs(root)

    def table() -> None:
        if added:
            print(f"added: {', '.join(added)}  [{rel_dir}]")
        if removed:
            print(f"removed: {', '.join(removed)}  [{rel_dir}]")
        if not added and not removed:
            print("no tag change (already present / absent)")

    emit(
        args,
        "catalog tag",
        {"rel_dir": rel_dir, "added": added, "removed": removed, "tags": list(after)},
        table=table,
    )
