"""``hmp replay`` - copy a run with its inputs and say how to run it again.

A thin wrapper of :func:`hydromodpy.results.export.publish.publish`. The run
is published to ``--into`` as a directory, with the bytes of its inputs. The
command then prints the line that replays it, ``hmp run DIR/config.toml
--frozen -w PROJECT``, and the HydroModPy version the run was sealed with: the
replay reads its inputs from ``DIR/inputs/``, needs no workspace of the
source, and writes its run into the project the line names.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

from hydromodpy.cli._conventions import verbosity_parser, workspace_parser
from hydromodpy.cli.helpers import apply_verbosity, exit_code_for

NAME: str = "replay"
HELP: str = "Copy a run with its inputs into a directory and print how to run it again"

_EPILOG = """\
Examples:
  hmp replay baseline_monthly --into ~/replays/baseline
  hmp replay @latest --into replay -w projects/my_catchment
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
        "ref", metavar="REF", help="The run to replay: its name, its id or an @-selector"
    )
    parser.add_argument(
        "--into",
        required=True,
        metavar="DIR",
        help="Directory of the copy, absent or empty",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.catalog.share import inputs_of
    from hydromodpy.cli.commands.publish import run_dir_of
    from hydromodpy.core.state.paths import resolve_project_root
    from hydromodpy.results.export.publish import MissingInputError, publish
    from hydromodpy.results.export.run_identity import read_sealed_manifest
    from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME

    project_root = resolve_project_root(Path(args.workspace or Path.cwd()).expanduser().resolve())
    try:
        source = run_dir_of(project_root, args.ref)
        if not (source / RUN_CONFIG_FILENAME).is_file():
            raise FileNotFoundError(
                f"{source.name} has no frozen {RUN_CONFIG_FILENAME}, so it cannot be replayed."
            )
        copy = publish(
            source,
            Path(args.into).expanduser(),
            project_root=project_root,
            format="dir",
            with_=("inputs",),
            inputs=inputs_of(project_root),
        )
        seal = read_sealed_manifest(source)
    except MissingInputError as exc:
        print(f"{exc.detail} A replay carries the bytes of every input.", file=sys.stderr)
        sys.exit(exit_code_for(exc))
    except Exception as exc:  # noqa: BLE001 - mapped to a typed exit code below
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))
    # publish refuses a run without a manifest, so the seal is there.
    version = seal.identity.hydromodpy_version if seal is not None else "unknown"
    config = shlex.quote(str(copy.resolve() / RUN_CONFIG_FILENAME))
    print(f"hmp run {config} --frozen -w {shlex.quote(str(project_root))}")
    print(f"HydroModPy {version}")
    print(
        f"The run was sealed with HydroModPy {version}; replay it with that version.",
        file=sys.stderr,
    )
