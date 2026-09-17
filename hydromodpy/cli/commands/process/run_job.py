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
import sys

from hydromodpy.cli.helpers import exit_code_for

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
    except Exception as exc:  # noqa: BLE001 - every failure leaves here as a typed code
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    # Written and not printed: ``print`` would append a newline to a document
    # that already ends with one, and "byte-identical" would stop being true.
    sys.stdout.write(payload)
    sys.exit(exit_code)
