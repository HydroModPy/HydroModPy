"""``hmp example add`` - fetch one example and write it into a workspace."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli._conventions import workspace_parser
from hydromodpy.cli.helpers import EXIT_OK, exit_code_for
from hydromodpy.core.exceptions import HydroModPyError
from hydromodpy.examples.blobs import DEFAULT_BASE_URL, SOURCE_ENV, default_ref

NAME: str = "add"
HELP: str = "Fetch one example's files, verify them, and write them into a workspace"

_EPILOG = f"""\
--workspace takes a workspace root and defaults to ~/hydromodpy; the workspace
has to exist already, so run `hmp workspace init` before the first add.

Files are cached by content under <cache>/examples/blobs/, so the 90 MiB
regional DEM is downloaded once and every later example that reads it costs
nothing.

Fetched from {DEFAULT_BASE_URL}/<ref>/<path>, with <ref> defaulting to
v<version> of the installed HydroModPy. Set {SOURCE_ENV} to replace that whole
prefix with another URL or a local directory, for an offline install or a test
against a checkout; when it is set, --ref no longer applies.
"""


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[workspace_parser()],
    )
    parser.add_argument("example_id", help="Example id, as listed by 'hmp example list'")
    parser.add_argument(
        "--ref",
        default=None,
        help=f"Git ref to fetch from (default: {default_ref()})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite destination files whose content differs from the manifest",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.example import add_to_workspace, human_size
    from hydromodpy.cli.helpers import resolve_workspace

    workspace = resolve_workspace(args.workspace)
    try:
        report = add_to_workspace(
            args.example_id,
            workspace=workspace,
            ref=args.ref,
            force=args.force,
        )
    except (HydroModPyError, FileNotFoundError, OSError) as exc:
        print(f"[example add] {exc}", file=sys.stderr)
        sys.exit(exit_code_for(exc))

    if report.everything_was_cached:
        print(f"[example add] Everything already cached, nothing downloaded from {report.source}.")
    else:
        print(
            f"[example add] Downloaded {len(report.downloaded)} file(s), "
            f"{human_size(report.downloaded_bytes)}, from {report.source}."
        )
    print(f"[example add] Workspace: {report.workspace}")
    print(f"[example add] Project:   {report.project_dir}")
    print(
        f"[example add] {len(report.written)} file(s) written, "
        f"{len(report.unchanged)} already up to date."
    )
    for dest in report.kept:
        print(f"[example add] kept, differs from the manifest: {dest} (--force overwrites)")
    print()
    print(f"Read {report.project_dir}/README.md, then run the config it starts from:")
    print(f"  hmp run {report.project_dir}/{report.entry_config}")
    sys.exit(EXIT_OK)
