"""``hmp publish`` - copy a run, the summary or a whole project out of the tree.

A thin wrapper of :func:`hydromodpy.project.api.publish`. The
reference is a run (its directory name under ``runs/``, an id or an
@-selector), ``summary``, or ``.`` for the project: every sealed run and the
summary, each in its own folder under ``--to``, written all at once by
the same verb. ``--container tar``
writes the same copy as an archive, which ``hmp catalog import`` reads back.
A copy takes along its results (``fields.zarr``, ``tables.parquet``,
``final_state/``) and every file the run read with its install index
(:func:`hydromodpy.project.exchange.share.run_bundle`), and the command then says how to
replay the copy. ``--without results`` or ``--without inputs`` leaves one out.
``--with`` goes with ``--package`` only. A replay not classed ``bit`` is
refused; ``hmp publish .`` leaves it out and names it under ``left_out``.

``--package`` writes a project with its data in one package instead
(:func:`hydromodpy.results.export.project_package.export_project`), which
``hmp project import`` installs: the reference is a project name or a path.

``--verify DEST`` compares a copy with its ``PUBLICATION.json``. The folder
``hmp publish .`` writes carries one of kind ``project`` that lists its
members: each member is verified, a member gone or an entry not listed is
named. A folder without any ``PUBLICATION.json`` whose entries are copies
is verified member by member, an entry that is not a copy being named.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.conventions import (
    dry_run_parser,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.exit_codes import (
    EXIT_GENERIC,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    exit_code_for,
    refuse,
)
from hydromodpy.cli.output import emit
from hydromodpy.cli.refs import project_root_of, resolve_project_ref

NAME: str = "publish"
HELP: str = "Copy a run, the summary or the project out of the tree, with PUBLICATION.json"

PROJECT_REF = "."
"""The reference that publishes the whole project."""

COPY_EXTRAS: tuple[str, ...] = ("results", "inputs")
PACKAGE_EXTRAS: tuple[str, ...] = ("runs", "sessions", "mesh", "fetched")

_EPILOG = """\
Examples:
  hmp publish calibration --to ~/deliverables/my_catchment
  hmp publish baseline_monthly --to baseline.tar --container tar
  hmp publish baseline_monthly --to light --without results
  hmp publish . --to /srv/deliverables/bretagne --public
  hmp publish my_catchment --package --to my_catchment.tar --with runs --with mesh
  hmp publish --verify ~/deliverables/my_catchment
"""


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[
            workspace_parser(),
            dry_run_parser(),
            format_parser(not_for="The container of a copy is --container."),
            verbosity_parser(),
        ],
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "ref",
        nargs="?",
        default=None,
        metavar="REF",
        help=(
            "A run (name, id or @-selector), 'summary', or '.' for the whole project. "
            "With --package, a project name or a path (default: the project of -w or of the cwd)"
        ),
    )
    parser.add_argument("--to", default=None, help="Destination: a new directory, or a .tar file")
    parser.add_argument(
        "--container",
        choices=("dir", "tar"),
        default=None,
        help="Write a directory or a tar archive (default: dir, tar with --package)",
    )
    parser.add_argument(
        "--package",
        action="store_true",
        help="Write the project with its data in one package, which 'hmp project import' installs",
    )
    parser.add_argument(
        "--without",
        action="append",
        choices=COPY_EXTRAS,
        default=[],
        help=(
            "Leave 'results' (fields.zarr, tables.parquet, final_state/) or 'inputs' (every "
            "file the run read, with INSTALL.toml) out of a copy; repeatable. A copy takes "
            "both by default"
        ),
    )
    parser.add_argument(
        "--with",
        dest="with_",
        action="append",
        choices=(*COPY_EXTRAS, *PACKAGE_EXTRAS),
        default=[],
        help=(
            "With --package only: take along 'runs' (the sealed runs with their results), "
            "'sessions', 'mesh' (the mesh products the runs cite) or 'fetched' (the files a "
            "provider delivered to the runs); repeatable"
        ),
    )
    parser.add_argument(
        "--public",
        action="store_true",
        help=(
            "Mark the copy public. Warn when the project declares no [publication] license "
            "or an input has no known licence."
        ),
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
    if args.verify is not None:
        _verify(args, Path(args.verify))
        return
    if args.to is None or (args.ref is None and not args.package):
        refuse("Name what to publish and where: hmp publish <ref> --to DEST", EXIT_USAGE)
    if args.with_ and not args.package:
        refuse(
            "a copy takes its results and its inputs by default. Write --without results or "
            "--without inputs to leave one out; --with goes with --package only.",
            EXIT_USAGE,
        )
    if args.without and args.package:
        refuse(
            "--without leaves something out of a copy; a package takes what --with names.",
            EXIT_USAGE,
        )
    wrong = [name for name in args.with_ if name not in PACKAGE_EXTRAS]
    if wrong:
        refuse(
            f"--with {wrong[0]} does not go with --package: it takes {', '.join(PACKAGE_EXTRAS)}.",
            EXIT_USAGE,
        )
    if args.package:
        _publish_package(args)
    else:
        _publish_copy(args)


def _publish_copy(args: argparse.Namespace) -> None:
    """Copy a run, the summary or every sealed run of the project under ``--to``."""
    from hydromodpy.project.api import publish
    from hydromodpy.results.export.publish import replay_line

    project_root = project_root_of(args)
    destination = Path(args.to).expanduser()
    container = args.container or "dir"
    carried = tuple(name for name in COPY_EXTRAS if name not in args.without)
    source = None if args.ref == PROJECT_REF else _source(project_root, args.ref)
    left_out: list[tuple[str, str]] = []
    published = publish(
        args.ref,
        to=destination,
        format=container,
        with_=carried,
        public=args.public,
        dry_run=args.dry_run,
        workspace=project_root,
    )
    if source is None:
        written, left_out = published.copies, published.left_out
    else:
        written = [published]
    replay = None
    if source is not None and container == "dir" and "inputs" in carried and not args.dry_run:
        replay = replay_line(source, written[0], project_root)

    def table() -> None:
        for path in written:
            print(path)
        done = "Would publish" if args.dry_run else "Published"
        print(f"{done} {len(written)} copy(ies)", file=sys.stderr)
        for rel_dir, reason in left_out:
            print(f"left out {rel_dir}: {reason}", file=sys.stderr)
        if replay is not None:
            print(f"next: {replay[0]}", file=sys.stderr)
            print(f"The run was sealed with HydroModPy {replay[1]}.", file=sys.stderr)

    emit(
        args,
        "publish",
        {
            "applied": not args.dry_run,
            "copies": written,
            "left_out": [{"rel_dir": rel_dir, "reason": reason} for rel_dir, reason in left_out],
            "package": False,
            "next": None if replay is None else replay[0],
        },
        table=table,
    )


def _publish_package(args: argparse.Namespace) -> None:
    """Write the project with its data in one package, which ``hmp project import`` installs."""
    from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
    from hydromodpy.project.exchange.share import inputs_of
    from hydromodpy.results.export.project_package import export_project

    if args.public:
        refuse("--public checks a copy of a run. A package is not published.", EXIT_USAGE)
    ref = None if args.ref == PROJECT_REF else args.ref
    project = resolve_project_ref(args.workspace, ref)
    written = export_project(
        project,
        Path(args.to).expanduser(),
        format=args.container or "tar",
        with_=tuple(args.with_),
        bundle_of=inputs_of(project),
        dry_run=args.dry_run,
        root_config=ROOT_CONFIG,
    )
    following = f"hmp project import {written} -w <workspace>"

    def table() -> None:
        print(written)
        if not args.dry_run:
            print(f"Install it elsewhere with: {following}", file=sys.stderr)

    emit(
        args,
        "publish",
        {"applied": not args.dry_run, "copies": [written], "package": True, "next": following},
        table=table,
    )


def _source(project_root: Path, ref: str) -> Path:
    """Return the directory one reference publishes: the summary or a run."""
    from hydromodpy.core.state.layout import SUMMARY_DIRNAME

    summary = project_root / SUMMARY_DIRNAME
    if ref == SUMMARY_DIRNAME:
        if not summary.is_dir():
            raise FileNotFoundError(f"{summary} does not exist: run 'hmp campaign collect' first.")
        return summary
    from hydromodpy.results.catalog.discovery import resolve_rel_dir

    return project_root / resolve_rel_dir(project_root, ref)


def _verify(args: argparse.Namespace, copy: Path) -> None:
    """Print the differences between a copy and its PUBLICATION.json; exit 1 on any.

    A project copy is verified through its own ``PUBLICATION.json``. A
    folder without one whose entries are copies is a campaign copy: every
    member is verified, each difference prefixed with its member.
    """
    from hydromodpy.results.export.publish import campaign_members, verify
    from hydromodpy.results.storage.contract import PUBLICATION_FILENAME

    target = copy.expanduser()
    members: list[Path] = [target]
    strays: list[str] = []
    if target.is_dir() and not (target / PUBLICATION_FILENAME).is_file():
        members, strays = campaign_members(target)
        if not members:
            refuse(
                f"{target} holds no {PUBLICATION_FILENAME} and no published copy: not a copy "
                "written by hmp publish.",
                EXIT_NOT_FOUND,
            )
        print(f"{target}: a campaign copy: verifying its {len(members)} members", file=sys.stderr)
    elif not target.exists():
        refuse(f"{target} does not exist: name a copy written by hmp publish.", EXIT_NOT_FOUND)
    problems = [f"{name}: not a published copy" for name in strays]
    for member in members:
        try:
            found = verify(member)
        except Exception as exc:  # noqa: BLE001 - the message names the member
            refuse(f"{member}: {exc}", exit_code_for(exc), cause=exc)
        prefix = "" if member == target else f"{member.name}/"
        problems += [f"{prefix}{problem}" for problem in found]

    def table() -> None:
        for problem in problems:
            print(problem)
        if problems:
            print(f"{target}: {len(problems)} difference(s) with PUBLICATION.json", file=sys.stderr)
        else:
            print(f"{target}: every file matches PUBLICATION.json", file=sys.stderr)

    emit(
        args,
        "publish verify",
        {"copy": target, "members": members, "problems": problems},
        table=table,
    )
    if problems:
        sys.exit(EXIT_GENERIC)
