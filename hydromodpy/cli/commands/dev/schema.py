"""``hmp dev schema`` - thin wrapper around :func:`hydromodpy.export_schema`."""

from __future__ import annotations

import argparse
import json
import sys

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND

NAME: str = "schema"
HELP: str = "Export the JSON Schema and companion files for frontend hooks"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="schema_command")

    export_p = sub.add_parser("export", help="Write config.json + config_meta.json")
    export_p.add_argument("--output", default="schema", help="Destination directory")

    validate_p = sub.add_parser("validate-field", help="Validate one field value")
    validate_p.add_argument("path", help="Dotted field path")
    validate_p.add_argument("value", help="Candidate value")
    validate_p.add_argument("--context", default=None, help="TOML providing form state")

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.dev import export_schema, validate_field

    sub = getattr(args, "schema_command", None)
    if sub == "export":
        written = export_schema(args.output)
        for key, path in written.items():
            print(f"{key}: {path}", file=sys.stderr)
        return
    if sub == "validate-field":
        context = _load_context(args.context)
        payload = validate_field(args.path, args.value, context=context)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        if not payload.get("valid", False):
            sys.exit(EXIT_CONFIG)
        return
    print("usage: hmp dev schema {export,validate-field} [options]", file=sys.stderr)
    sys.exit(EXIT_CONFIG)


def _load_context(ctx_path: str | None) -> dict | None:
    import tomllib
    from pathlib import Path

    if not ctx_path:
        return None
    ctx_file = Path(ctx_path).expanduser().resolve()
    if not ctx_file.is_file():
        print(f"context TOML not found: {ctx_file}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    with ctx_file.open("rb") as fh:
        return tomllib.load(fh)
