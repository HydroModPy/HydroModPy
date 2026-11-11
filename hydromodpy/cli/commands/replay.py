"""``hmp replay REF`` - play a sealed run or a published copy again, and class its values.

The verb reads the configuration the run sealed, migrates it under today's names
and defaults, pins every input at the digest of its record and writes a new
version of the run into the project. The seal of the new run carries the class of
the replay: ``bit`` when every value reproduces, ``deviation`` when one moved,
appeared or left, with the size of each move. ``--strict`` refuses a deviation
before the seal, and the attempt keeps its fields and tables with no seal.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.environment import add_environment_arguments
from hydromodpy.cli.exit_codes import exit_code_for, refuse
from hydromodpy.cli.output import emit
from hydromodpy.cli.refs import base_named_by_w

NAME: str = "replay"
HELP: str = "Play a sealed run or a published copy again, and class the values it computes"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog=(
            "The new run keeps the name of its source and takes the next version;\n"
            "its seal carries lineage.replay, with the class, the keys that moved and\n"
            "the build drift. A moved input is refused before anything runs.\n"
            "\n"
            "Examples:\n"
            "  hmp replay runs/baseline.v2\n"
            "  hmp replay copies/baseline --strict -w ."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "ref",
        metavar="REF",
        help=(
            "A sealed run directory or its config.toml, a bare run name under runs/ when "
            "-w is given, or a published copy."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Refuse a value that does not reproduce the source, before the seal. The "
            "attempt keeps its fields and tables, sealed as neither."
        ),
    )
    parser.set_defaults(_handler=run)
    add_environment_arguments(parser)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli.environment import environment_from_args
    from hydromodpy.core.exceptions import HydroModPyError
    from hydromodpy.project.api import replay
    from hydromodpy.project.replay import replay_target

    base = base_named_by_w(args.workspace)
    try:
        target = replay_target(args.ref, base=base)
        outcome = replay(
            args.ref,
            workspace=base,
            strict=bool(args.strict),
            environment=environment_from_args(args),
        )
        payload = _payload(args, target, outcome)
    except (HydroModPyError, OSError, ValueError) as exc:
        refuse(str(exc), exit_code_for(exc), cause=exc)
    emit(args, "replay", payload, table=lambda: _print(payload))


def _payload(args: argparse.Namespace, target: Any, outcome: Any) -> dict[str, Any]:
    """Return what the command writes: the outcome of the new run, and the class its seal carries."""
    from hydromodpy.results.catalog.registration import run_dir_holding
    from hydromodpy.results.record.manifest import read_seal

    rel_dir = run_dir_holding(Path(target.project_root), str(outcome.sim_id))
    replay = read_seal(Path(target.project_root) / rel_dir).lineage.replay
    return {
        "ref": str(args.ref),
        "source": target.source.name,
        "sim_id": str(outcome.sim_id),
        "name": outcome.name,
        "rel_dir": rel_dir,
        "class": None if replay is None else replay.class_,
        "basis": None if replay is None else replay.basis,
        "differs": (
            {}
            if replay is None
            else {key: value.model_dump(mode="json") for key, value in replay.differs.items()}
        ),
        "added": [] if replay is None else replay.added,
        "removed": [] if replay is None else replay.removed,
        "changes": [] if replay is None else replay.changes,
        "strict": bool(args.strict),
    }


def _print(payload: dict[str, Any]) -> None:
    """Say which run the replay wrote, and what its values did."""
    label = payload["rel_dir"] or payload["sim_id"][:8]
    print(f"replayed {payload['source']} as {label}  [{payload['sim_id'][:8]}]")
    kind = payload["class"]
    if kind is None:
        print("  values : no comparison, the source keeps none this replay can read")
        return
    detail = ""
    if kind == "deviation":
        parts = []
        if payload["differs"]:
            parts.append(f"{len(payload['differs'])} value(s) moved")
        if payload["added"]:
            parts.append(f"{len(payload['added'])} added")
        if payload["removed"]:
            parts.append(f"{len(payload['removed'])} removed")
        detail = f" ({', '.join(parts)})"
    print(f"  values : {kind}{detail}, basis {payload['basis']}")
    if payload["changes"]:
        print(f"  changes: {', '.join(payload['changes'])}")
