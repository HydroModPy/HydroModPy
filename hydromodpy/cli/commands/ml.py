"""``hmp ml`` - machine learning namespace (stubs only).

The four sub-commands (``split``, ``fit-scaler``, ``export``, ``track``)
all print ``ready-to-go in v2.x`` and exit ``0``. They reserve the verb
surface so v2.x can ship the real ML utilities without breaking CLI
contracts in the wild.
"""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_OK

NAME: str = "ml"
HELP: str = "Machine learning helpers (split / fit-scaler / export / track) - stubs"

_READY_MSG = "ready-to-go in v2.x"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="ml_command")

    split = sub.add_parser("split", help="Build train/val/test splits (stub)")
    split.add_argument("--by", default=None)
    split.add_argument("--seed", type=int, default=42)
    split.add_argument("--output", "-o", default=None)

    scaler = sub.add_parser("fit-scaler", help="Fit a feature scaler on a split (stub)")
    scaler.add_argument("--strategy", default="standard")
    scaler.add_argument("--on-split", default=None)

    export = sub.add_parser("export", help="Export an ML-ready bundle (stub)")
    export.add_argument("--bundle", default="ro-crate")
    export.add_argument("--output", "-o", default=None)

    track = sub.add_parser("track", help="Track experiments on an MLflow-like backend (stub)")
    track.add_argument("--backend", default="mlflow")

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    sub = getattr(args, "ml_command", None)
    if sub in {"split", "fit-scaler", "export", "track"}:
        print(_READY_MSG)
        sys.exit(EXIT_OK)
    print(
        "Usage: hmp ml {split|fit-scaler|export|track} [options]",
        file=sys.stderr,
    )
    sys.exit(EXIT_CONFIG)


__all__ = ("NAME", "HELP", "register", "run")
