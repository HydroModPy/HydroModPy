"""``hmp process verify`` - re-check a finished job directory against its seal.

Pointed at directories this process did not write, including ones a transfer
truncated: it reports what it found and never crashes on them. An unsealed
directory is not an error of this verb, it is a fact about the job, and it is
reported as one.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys

from hydromodpy.cli._conventions import format_parser
from hydromodpy.cli.helpers import EXIT_VALIDATION, exit_code_for

NAME: str = "verify"
HELP: str = "Re-check a finished job directory against its own seal"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[format_parser()],
        epilog="Example:\n  hmp process verify --job /scratch/jobs/4711",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--job",
        required=True,
        metavar="DIR",
        help="Job directory to re-check",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.process import verify_capability_job

    try:
        verification = verify_capability_job(args.job)
    except Exception as exc:  # noqa: BLE001 - map resolver errors to typed exit codes
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    problems = list(verification.problems)
    if args.format == "json":
        print(
            json.dumps(
                {"sealed": verification.sealed, "ok": verification.ok, "problems": problems},
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.format == "csv":
        writer = csv.writer(sys.stdout)
        writer.writerow(["problem"])
        writer.writerows([problem] for problem in problems)
    elif verification.ok:
        print(f"{args.job}: sealed, and every artefact still hashes to what the seal recorded")
    else:
        print(f"{args.job}: {len(problems)} problem(s)")
        for problem in problems:
            print(f"  - {problem}")

    if not verification.ok:
        sys.exit(EXIT_VALIDATION)
