"""``hmp process run`` - run one capability in one job directory.

Three rules this verb exists to keep, each of them a promise a shim relies on:

- **stdout carries exactly one JSON document and nothing else**, byte for byte
  the content of ``outcome.json``. No banner, no progress, no warning, no
  traceback. Everything human goes to stderr.
- **the exit code is the typed one of the outcome**, so a caller that tests
  ``$?`` and a caller that reads the document agree.
- **SIGTERM unwinds**, the outcome says ``dismissed``, nothing is sealed, and
  the process exits 130.
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading

from hydromodpy.cli.helpers import EXIT_SIGINT, exit_code_for

NAME: str = "run"
HELP: str = "Run one capability in a job directory that already carries its request"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        epilog=(
            "Example:\n"
            "  hmp process run terrain-delineate --job /scratch/jobs/4711 "
            "> out.json 2> err.log"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("capability", help="Capability id, as 'hmp process list' spells it")
    parser.add_argument(
        "--job",
        required=True,
        metavar="DIR",
        help="Job directory carrying request.json, and nothing else yet",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.process import run_capability

    try:
        exit_code, payload = run_capability(args.capability, args.job)
    except KeyboardInterrupt:
        # Cancelled before there was a job to write an outcome into. Nothing on
        # stdout, because the promise is one document or none, never half of one.
        sys.exit(EXIT_SIGINT)
    except Exception as exc:  # noqa: BLE001 - every failure leaves here as a typed code
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    ignore_termination()
    # Written and not printed: ``print`` would append a newline to a document
    # that already ends with one, and "byte-identical" would stop being true.
    sys.stdout.write(payload)
    sys.exit(exit_code)


def ignore_termination() -> None:
    """Ignore SIGTERM from here to the exit.

    ``terminate_as_interrupt`` puts the previous handler back when its block
    ends, which leaves a window between "the outcome is decided and written"
    and "the process exits with its code". A SIGTERM landing in that window
    killed a sealed, successful job at 143, so the shell read a failure while
    the document on disk and on stdout said ``successful`` and 0. Nothing this
    process can still do would make that true, so it stops listening.
    """
    if threading.current_thread() is not threading.main_thread():
        return
    try:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    except (OSError, ValueError):
        # A host that will not let this process install a handler still exits
        # with the right code on every path but this race.
        return
