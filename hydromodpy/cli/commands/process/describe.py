"""``hmp process describe`` - the machine-readable description of one capability.

The document is generated from the declaration and the Pydantic request model
by ``python -m tools.processes``, committed under ``hydromodpy/schema/processes/``
and compared byte for byte by a gate. This verb does not render it a second
time: it writes the bytes that ship in the wheel, so a caller who reads the
pipe and a caller who opens the package data learn the same thing.

That is why ``--format json``, the default, writes and does not print: the file
already ends with a newline, and ``print`` would add a second one.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys

from hydromodpy.cli._conventions import format_parser
from hydromodpy.cli.helpers import exit_code_for

NAME: str = "describe"
HELP: str = "Print the process description of one capability"

_COLUMNS = ("kind", "name", "detail")


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[format_parser(default="json")],
        epilog="Example:\n  hmp process describe terrain-delineate > terrain-delineate.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("capability", help="Capability id, as 'hmp process list' spells it")
    parser.add_argument(
        "--major",
        type=int,
        default=None,
        metavar="N",
        help="Pin the major version of the description (default: the one this build serves)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.process import describe_capability

    try:
        payload = describe_capability(args.capability, args.major)
    except Exception as exc:  # noqa: BLE001 - every failure leaves here as a typed code
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    if args.format == "json":
        sys.stdout.write(payload)
        return

    rows = _flatten(json.loads(payload))
    if args.format == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
        return
    for row in rows:
        print(f"{row['kind']:<8}{row['name']:<24}{row['detail']}")


def _flatten(document: dict) -> list[dict[str, str]]:
    """Render the document as flat rows, which is all a table or a CSV can carry."""
    rows = [
        {"kind": "process", "name": document["id"], "detail": document["title"]},
        {"kind": "version", "name": document["version"], "detail": document["description"]},
    ]
    rows += [
        {
            "kind": "input",
            "name": name,
            "detail": f"{entry['minOccurs']}..{entry['maxOccurs']}  {entry['title']}",
        }
        for name, entry in document["inputs"].items()
    ]
    rows += [
        {"kind": "output", "name": name, "detail": entry["hmp:path"]}
        for name, entry in document["outputs"].items()
    ]
    rows += [
        {
            "kind": "error",
            "name": entry["code"],
            "detail": f"exit {entry['exit_code']}  {entry['title']}",
        }
        for entry in document["hmp:exceptions"]
    ]
    return rows
