"""``hmp schema`` — export the JSON Schema and validate single fields."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from hydromodpy._cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND


NAME = "schema"
HELP = "Export the JSON Schema and companion files for frontend hooks"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="schema_command")

    export_p = sub.add_parser(
        "export",
        help="Write config.json + config_meta.json + field_validators.json",
    )
    export_p.add_argument(
        "--output",
        default="schema",
        help="Destination directory (default: ./schema/)",
    )

    validate_p = sub.add_parser(
        "validate-field",
        help="Validate a single field value without running the full config",
    )
    validate_p.add_argument("path", help="Dotted field path, e.g. 'flow.flow_regime'")
    validate_p.add_argument(
        "value",
        help="Candidate value (JSON if parseable, otherwise string)",
    )
    validate_p.add_argument(
        "--context",
        default=None,
        help="Optional TOML config providing the current form state",
    )

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    subcommand = getattr(args, "schema_command", None)
    if subcommand == "export":
        _cmd_export(args)
        return
    if subcommand == "validate-field":
        _cmd_validate_field(args)
        return
    print(
        "usage: hmp schema {export,validate-field} [options]",
        file=sys.stderr,
    )
    sys.exit(EXIT_CONFIG)


def _cmd_export(args: argparse.Namespace) -> None:
    from hydromodpy.schema import export_full_schema

    output = Path(getattr(args, "output", None) or "schema").expanduser().resolve()
    written = export_full_schema(output)
    for key, path in written.items():
        print(f"{key}: {path}", file=sys.stderr)


def _cmd_validate_field(args: argparse.Namespace) -> None:
    import tomllib

    from hydromodpy.schema import validate_field

    raw_value: str = args.value
    try:
        value: Any = json.loads(raw_value)
    except (ValueError, TypeError):
        value = raw_value

    context: dict | None = None
    ctx_path = getattr(args, "context", None)
    if ctx_path:
        ctx_file = Path(ctx_path).expanduser().resolve()
        if not ctx_file.is_file():
            print(f"context TOML not found: {ctx_file}", file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)
        with ctx_file.open("rb") as fh:
            context = tomllib.load(fh)

    result = validate_field(args.path, value, context=context)
    payload = result.as_dict()
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if not result.valid:
        sys.exit(EXIT_CONFIG)
