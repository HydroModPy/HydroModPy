"""``hmp example add`` - fetch one, several or every example into a workspace."""

from __future__ import annotations

import argparse

from hydromodpy.cli.conventions import format_parser, workspace_parser
from hydromodpy.cli.exit_codes import EXIT_USAGE, exit_code_for, refuse
from hydromodpy.cli.output import emit
from hydromodpy.core.exceptions import HydroModPyError
from hydromodpy.project.examples.blobs import DEFAULT_BASE_URL, SOURCE_ENV, default_ref

NAME: str = "add"
HELP: str = "Fetch one, several or every example, verify the files, and write them into a workspace"

_EPILOG = f"""\
Each example becomes a project of the workspace, projects/<NN>_<name>/, with its
TOML files, its Python script and its README. Its data go to the shared data/
folder of the workspace. Every id is checked before the first download.

-w takes a workspace root or a project inside it; without it, the workspace that
holds the current directory. It has to exist: run `hmp workspace init` first.

Files are cached by content under <cache>/examples/blobs/, so the 90 MiB
regional DEM is downloaded once and every later example that reads it costs
nothing. A command stopped halfway can be run again: it fetches only what is
still missing.

Fetched from {DEFAULT_BASE_URL}/<ref>/<path>, with <ref> defaulting to
v<version> of the installed HydroModPy. Set {SOURCE_ENV} to replace that whole
prefix with another URL or a local directory, for an offline install or a test
against a checkout; when it is set, --ref no longer applies.

Examples:
  hmp example add 04
  hmp example add 00 07 08 -w ~/hydromodpy
  hmp example add --all
"""


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[workspace_parser(), format_parser()],
    )
    parser.add_argument(
        "example_id",
        nargs="*",
        help="One or more example ids, as listed by 'hmp example list'",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Install every example this build ships",
    )
    parser.add_argument(
        "--ref",
        default=None,
        help=f"Git ref to fetch from (default: {default_ref()})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Go past the refusal: overwrite files whose content differs from the manifest",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli.refs import resolve_workspace
    from hydromodpy.project.api import example
    from hydromodpy.project.examples.rows import human_size

    if args.all == bool(args.example_id):
        refuse(
            "[example add] Name one or more examples, as 'hmp example add 04 07', "
            "or ask for all of them with --all.",
            EXIT_USAGE,
        )

    workspace = resolve_workspace(args.workspace)
    try:
        reports = example(
            None if args.all else args.example_id,
            add=True,
            workspace=workspace,
            ref=args.ref,
            force=args.force,
        )
    except (HydroModPyError, FileNotFoundError, OSError) as exc:
        refuse(f"[example add] {exc}", exit_code_for(exc), cause=exc)

    def table() -> None:
        for report in reports:
            tag = f"[example add {report.example_id}]"
            if report.everything_was_cached:
                print(f"{tag} Everything already cached, nothing downloaded.")
            else:
                print(
                    f"{tag} Downloaded {len(report.downloaded)} file(s), "
                    f"{human_size(report.downloaded_bytes)}, from {report.source}."
                )
            print(
                f"{tag} {len(report.written)} file(s) written, "
                f"{len(report.unchanged)} already up to date, in {report.project_dir}"
            )
            for label in report.stations_written:
                print(f"{tag} station registry updated: {label}")
            for dest in report.kept:
                print(f"{tag} kept, differs from the manifest: {dest} (--force overwrites)")
        print()
        print("Read the README.md of a project, then run the config it starts from:")
        for report in reports:
            print(f"  hmp run {report.project_dir}/{report.entry_config}")

    emit(args, "example add", [report.to_dict() for report in reports], table=table)
