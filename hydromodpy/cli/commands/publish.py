"""``hmp publish`` - copy a run, the summary or a whole project out of the tree.

A thin wrapper of :func:`hydromodpy.results.export.publish.publish`. The
reference is a run (its directory name under ``runs/``, an id or an
@-selector), ``summary``, or ``.`` for the project: every sealed run and the
summary, each in its own folder under ``--to``, written all at once by
:func:`hydromodpy.results.export.publish.publish_project`. ``--container tar``
writes the same copy as an archive, which ``hmp catalog import`` reads back.
``--with inputs`` takes along every file the run read with its install index
(:func:`hydromodpy.project.share.run_bundle`), and the command then says how to
run the copy again.

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
import shlex
import sys
import tarfile
from pathlib import Path

from hydromodpy.cli.conventions import (
    dry_run_parser,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import (
    EXIT_GENERIC,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    apply_verbosity,
    exit_code_for,
    project_root_of,
    refuse,
    resolve_project_ref,
)
from hydromodpy.cli.output import emit

NAME: str = "publish"
HELP: str = "Copy a run, the summary or the project out of the tree, with PUBLICATION.json"

PROJECT_REF = "."
"""The reference that publishes the whole project."""

COPY_EXTRAS: tuple[str, ...] = ("results", "inputs")
PACKAGE_EXTRAS: tuple[str, ...] = ("runs", "sessions", "mesh", "fetched")

_EPILOG = """\
Examples:
  hmp publish calibration --to ~/deliverables/my_catchment
  hmp publish baseline_monthly --to baseline.tar --container tar --with results --with inputs
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
        "--with",
        dest="with_",
        action="append",
        choices=(*COPY_EXTRAS, *PACKAGE_EXTRAS),
        default=[],
        help=(
            "Take along 'results' (fields.zarr, tables.parquet, mesh) or 'inputs' (every file "
            "the run read, with INSTALL.toml, which 'hmp catalog import' installs); repeatable. "
            "With --package: 'runs' (the sealed runs with their results), 'sessions', 'mesh' "
            "(the mesh cache entries the runs read) or 'fetched' (the files a provider "
            "delivered to the runs)"
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
        _verify(args, Path(args.verify))
        return
    if args.to is None or (args.ref is None and not args.package):
        refuse("Name what to publish and where: hmp publish <ref> --to DEST", EXIT_USAGE)
    extras = PACKAGE_EXTRAS if args.package else COPY_EXTRAS
    wrong = [name for name in args.with_ if name not in extras]
    if wrong:
        refuse(
            f"--with {wrong[0]} does not go with {'--package' if args.package else 'a copy'}: "
            f"it takes {', '.join(extras)}.",
            EXIT_USAGE,
        )
    if args.package:
        _publish_package(args)
    else:
        _publish_copy(args)


def _publish_copy(args: argparse.Namespace) -> None:
    """Copy a run, the summary or every sealed run of the project under ``--to``."""
    from hydromodpy.project.share import inputs_of
    from hydromodpy.results.export.publish import publish, publish_project

    project_root = project_root_of(args)
    destination = Path(args.to).expanduser()
    container = args.container or "dir"
    source = None if args.ref == PROJECT_REF else _source(project_root, args.ref)
    if source is None:
        written = publish_project(
            project_root,
            destination,
            format=container,
            with_=tuple(args.with_),
            public=args.public,
            inputs=inputs_of(project_root),
            dry_run=args.dry_run,
        )
    else:
        written = [
            publish(
                source,
                destination,
                project_root=project_root,
                format=container,
                with_=tuple(args.with_),
                public=args.public,
                inputs=inputs_of(project_root),
                dry_run=args.dry_run,
            )
        ]
    replay = None
    if source is not None and container == "dir" and "inputs" in args.with_ and not args.dry_run:
        replay = _how_to_run_it_again(source, written[0], project_root)

    def table() -> None:
        for path in written:
            print(path)
        done = "Would publish" if args.dry_run else "Published"
        print(f"{done} {len(written)} copy(ies)", file=sys.stderr)
        if replay is not None:
            print(f"next: {replay[0]}", file=sys.stderr)
            print(f"The run was sealed with HydroModPy {replay[1]}.", file=sys.stderr)

    emit(
        args,
        "publish",
        {
            "applied": not args.dry_run,
            "copies": written,
            "package": False,
            "next": None if replay is None else replay[0],
        },
        table=table,
    )


def _how_to_run_it_again(source: Path, copy: Path, project_root: Path) -> tuple[str, str] | None:
    """Return the line that replays a copy and the version the run was sealed with.

    A copy of a run with its inputs replays from its own bytes. A summary, or a
    run without a frozen configuration, has no such line.
    """
    from hydromodpy.results.export.run_identity import read_sealed_manifest
    from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME

    seal = read_sealed_manifest(source)
    if seal is None or not (source / RUN_CONFIG_FILENAME).is_file():
        return None
    config = shlex.quote(str(copy.resolve() / RUN_CONFIG_FILENAME))
    line = f"hmp run {config} --frozen -w {shlex.quote(str(project_root))}"
    return line, seal.identity.hydromodpy_version


def _publish_package(args: argparse.Namespace) -> None:
    """Write the project with its data in one package, which ``hmp project import`` installs."""
    from hydromodpy.project.share import inputs_of
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
    from hydromodpy.core.state.paths import SUMMARY_DIRNAME

    summary = project_root / SUMMARY_DIRNAME
    if ref == SUMMARY_DIRNAME:
        if not summary.is_dir():
            raise FileNotFoundError(f"{summary} does not exist: run 'hmp campaign collect' first.")
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


def _verify(args: argparse.Namespace, copy: Path) -> None:
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
