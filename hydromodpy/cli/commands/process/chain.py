"""``hmp process chain`` - run several capabilities in a row, in one command.

The verb that makes two capabilities compose. ``run`` executes one job whose
``request.json`` the caller wrote; ``chain`` reads one document describing
several, writes each ``request.json`` itself, and fills the file inputs of a
step from the artefacts of an earlier one. Asking for a variable over a
watershed -- delineate, then fetch against the mask that came out -- is one
command and no glue script.

It keeps the three promises of ``run``, at the scale of the chain:

- **stdout carries exactly one JSON document and nothing else**, byte for byte
  the content of ``DIR/chain-outcome.json``. Everything human goes to stderr.
- **the exit code is the typed one of the step that stopped it**, and 0 when
  every step succeeded.
- **a refused chain document writes nothing at all**: no step directory, no
  report, the root exactly as the caller staged it.
"""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.commands.process.run_job import ignore_termination
from hydromodpy.cli.helpers import EXIT_SIGINT, exit_code_for

NAME: str = "chain"
HELP: str = "Run several capabilities in a row, each feeding the next by file"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        epilog=("Example:\n  hmp process chain --root /scratch/chains/17 > out.json 2> err.log"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--root",
        required=True,
        metavar="DIR",
        help="Chain directory carrying chain.json, where each step directory is created",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.process import run_capability_chain

    try:
        exit_code, payload = run_capability_chain(args.root)
    except KeyboardInterrupt:
        # Cancelled before the first step had a directory to report into.
        # Nothing on stdout, because the promise is one document or none.
        sys.exit(EXIT_SIGINT)
    except Exception as exc:  # noqa: BLE001 - every failure leaves here as a typed code
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    ignore_termination()
    # Written and not printed, for the reason ``run`` gives: the document
    # already ends with a newline, and "byte-identical" has to stay true.
    sys.stdout.write(payload)
    sys.exit(exit_code)
