"""``hmp publish`` - copy a run, the summary or a whole project out of the tree.

A thin wrapper of :func:`hydromodpy.results.export.publish.publish`. The
reference is a run (its directory name under ``runs/``, an id or an
@-selector), ``summary``, or ``.`` for the project: every sealed run and the
summary, each in its own folder under ``--to``, written all at once by
:func:`hydromodpy.results.export.publish.publish_project`. ``--format tar`` writes the
same copy as an archive, which ``hmp catalog import`` reads back. ``--with
inputs`` takes along every file the run read with its install index
(:func:`hydromodpy.catalog.share.run_bundle`).
``--verify DEST`` compares a copy with its ``PUBLICATION.json``. The folder
``hmp publish .`` writes carries one of kind ``project`` that lists its
members: each member is verified, a member gone or an entry not listed is
named. A folder without any ``PUBLICATION.json`` whose entries are copies
is verified member by member, an entry that is not a copy being named.
"""

from __future__ import annotations

import argparse
import sys
import tarfile
from pathlib import Path

from hydromodpy.cli.conventions import verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import (
    EXIT_GENERIC,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    apply_verbosity,
    exit_code_for,
)

NAME: str = "publish"
HELP: str = "Copy a run, the summary or the project out of the tree, with PUBLICATION.json"

PROJECT_REF = "."
"""The reference that publishes the whole project."""

_EPILOG = """\
Examples:
  hmp publish calibration --to ~/deliverables/my_catchment
  hmp publish baseline_monthly --to baseline.tar --format tar --with results --with inputs
  hmp publish . --to /srv/deliverables/bretagne --public
  hmp publish --verify ~/deliverables/my_catchment
"""


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), verbosity_parser()],
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "ref",
        nargs="?",
        default=None,
        metavar="REF",
        help="A run (name, id or @-selector), 'summary', or '.' for the whole project",
    )
    parser.add_argument("--to", default=None, help="Destination: a new directory, or a .tar file")
    parser.add_argument(
        "--format",
        choices=("dir", "tar"),
        default="dir",
        help="Write a directory (default) or a tar archive",
    )
    parser.add_argument(
        "--with",
        dest="with_",
        action="append",
        choices=("results", "inputs"),
        default=[],
        help=(
            "Take along 'results' (fields.zarr, tables.parquet, mesh) or 'inputs' (every file "
            "the run read, with INSTALL.toml, which 'hmp catalog import' installs); repeatable"
        ),
    )
    parser.add_argument(
        "--public",
        action="store_true",
        help="Refuse to publish unless [publication] license is declared",
    )
    parser.add_argument(
        "--verify",
        default=None,
        metavar="DEST",
        help="Compare a published copy with its PUBLICATION.json and write nothing",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    if args.verify is not None:
        _verify(Path(args.verify))
        return
    if args.ref is None or args.to is None:
        print("Name what to publish and where: hmp publish <ref> --to DEST", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    from hydromodpy.catalog.share import inputs_of
    from hydromodpy.core.state.paths import resolve_project_root
    from hydromodpy.results.export.publish import publish, publish_project

    project_root = resolve_project_root(Path(args.workspace or Path.cwd()).expanduser().resolve())
    destination = Path(args.to).expanduser()
    try:
        if args.ref == PROJECT_REF:
            written = publish_project(
                project_root,
                destination,
                format=args.format,
                with_=tuple(args.with_),
                public=args.public,
                inputs=inputs_of(project_root),
            )
        else:
            written = [
                publish(
                    _source(project_root, args.ref),
                    destination,
                    project_root=project_root,
                    format=args.format,
                    with_=tuple(args.with_),
                    public=args.public,
                    inputs=inputs_of(project_root),
                )
            ]
    except Exception as exc:  # noqa: BLE001 - mapped to a typed exit code below
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    for path in written:
        print(path)
    print(f"Published {len(written)} copy(ies)", file=sys.stderr)


def _source(project_root: Path, ref: str) -> Path:
    """Return the directory one reference publishes: the summary or a run."""
    from hydromodpy.core.state.paths import SUMMARY_DIRNAME

    summary = project_root / SUMMARY_DIRNAME
    if ref == SUMMARY_DIRNAME:
        if not summary.is_dir():
            raise FileNotFoundError(f"{summary} does not exist: run 'hmp project collect' first.")
        return summary
    return run_dir_of(project_root, ref)


def run_dir_of(project_root: Path, ref: str) -> Path:
    """Return the directory of one run: its name under ``runs/``, else an id or @-selector."""
    from hydromodpy.core.state.paths import runs_dir_for

    on_disk = runs_dir_for(project_root) / ref
    if on_disk.is_dir():
        return on_disk
    from hydromodpy.results.catalog import Catalog

    with Catalog(project_root) as catalog:
        return Path(catalog.run_dir_for(catalog.resolve(ref)))


def _verify(copy: Path) -> None:
    """Print the differences between a copy and its PUBLICATION.json; exit 1 on any.

    A project copy is verified through its own ``PUBLICATION.json``. A
    folder without one whose entries are copies is a campaign copy: every
    member is verified, each difference prefixed with its member.
    """
    from hydromodpy.results.export.publish import verify
    from hydromodpy.results.storage.contract import PUBLICATION_FILENAME

    target = copy.expanduser()
    members: list[Path] = [target]
    strays: list[str] = []
    if target.is_dir() and not (target / PUBLICATION_FILENAME).is_file():
        members, strays = _campaign_members(target)
        if not members:
            print(
                f"{target} holds no {PUBLICATION_FILENAME} and no published copy: not a copy "
                "written by hmp publish.",
                file=sys.stderr,
            )
            sys.exit(EXIT_NOT_FOUND)
        print(f"{target}: a campaign copy: verifying its {len(members)} members", file=sys.stderr)
    elif not target.exists():
        print(f"{target} does not exist: name a copy written by hmp publish.", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    problems = [f"{name}: not a published copy" for name in strays]
    for member in members:
        try:
            found = verify(member)
        except Exception as exc:  # noqa: BLE001 - mapped to a typed exit code below
            print(f"{member}: {exc}", file=sys.stderr)
            sys.exit(exit_code_for(exc))
        prefix = "" if member == target else f"{member.name}/"
        problems += [f"{prefix}{problem}" for problem in found]
    for problem in problems:
        print(problem)
    if problems:
        print(f"{target}: {len(problems)} difference(s) with PUBLICATION.json", file=sys.stderr)
        sys.exit(EXIT_GENERIC)
    print(f"{target}: every file matches PUBLICATION.json", file=sys.stderr)


def _campaign_members(folder: Path) -> tuple[list[Path], list[str]]:
    """Return the copies a campaign folder holds, and the names of its other entries."""
    from hydromodpy.results.storage.contract import PUBLICATION_FILENAME

    members: list[Path] = []
    strays: list[str] = []
    for entry in sorted(folder.iterdir()):
        if (entry.is_dir() and (entry / PUBLICATION_FILENAME).is_file()) or (
            entry.is_file() and tarfile.is_tarfile(entry)
        ):
            members.append(entry)
        else:
            strays.append(entry.name)
    return members, strays
