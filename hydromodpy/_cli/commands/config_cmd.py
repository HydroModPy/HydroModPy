"""``hmp config`` — configuration TOML template + schema + validator.

Subparsers:
  - ``hmp config template [OUTPUT]``  : generate a TOML template (default action)
  - ``hmp config check FILE.toml``    : validate a TOML against the Pydantic schema
  - ``hmp config schema ...``         : export the JSON Schema (legacy, now via ``hmp schema``)
  - ``hmp config wizard``             : stdin-driven wizard

Backwards-incompatible change in v0.5: ``hmp config FILE.toml`` (bare form) still
works but the canonical invocation is ``hmp config template FILE.toml``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from hydromodpy._cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND


NAME = "config"
HELP = "Generate a TOML template, validate a config, or export the JSON Schema"


def register(subparsers) -> argparse.ArgumentParser:
    from hydromodpy.core.config.generate_toml import PROFILES

    parser = subparsers.add_parser(NAME, help=HELP)
    # Legacy top-level arguments: kept for back-compat with ``hmp config FILE`` form.
    parser.add_argument("output", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument(
        "--profile", choices=list(PROFILES.keys()), default="expert",
        help="Parameter visibility level (default: expert)",
    )
    parser.add_argument(
        "--modules", nargs="+",
        help="Module sections to include (default: all).",
    )
    parser.add_argument(
        "--list-modules", action="store_true",
        help="List available module names and exit",
    )
    parser.add_argument(
        "--ui", action="store_true",
        help="Launch interactive Streamlit configuration editor",
    )
    parser.add_argument("--section", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--out", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--list-sections", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--wizard", action="store_true",
        help="Launch the stdin-based TOML wizard",
    )

    sub = parser.add_subparsers(dest="config_command")

    tpl = sub.add_parser("template", help="Generate a TOML configuration template")
    tpl.add_argument("output", nargs="?",
                     help="Output file (or directory); prints to stdout if omitted")
    tpl.add_argument("--profile", choices=list(PROFILES.keys()), default="expert",
                     help="Parameter visibility level (default: expert)")
    tpl.add_argument("--modules", nargs="+",
                     help="Module sections to include (default: all)")
    tpl.add_argument("--list-modules", action="store_true",
                     help="List available module names and exit")

    chk = sub.add_parser("check", help="Validate a TOML against the Pydantic schema")
    chk.add_argument("file", help="Path to the TOML configuration")
    chk.add_argument("--strict", action="store_true",
                     help="Fail on warnings in addition to errors")

    # Legacy aliases preserved for back-compat
    sch = sub.add_parser("schema", help="Export the JSON Schema (alias of 'hmp schema export')")
    sch.add_argument("--section", default=None)
    sch.add_argument("--out", default=None)
    sch.add_argument("--list-sections", action="store_true")

    wiz = sub.add_parser("wizard", help="Interactive stdin-based TOML wizard")
    wiz.add_argument("output", nargs="?")
    wiz.add_argument("--profile", choices=list(PROFILES.keys()), default="user")

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    sub = getattr(args, "config_command", None)

    if sub == "check":
        _cmd_config_check(args)
        return
    if sub == "template":
        _cmd_config_template(args)
        return
    if sub == "schema":
        _cmd_config_schema(args)
        return
    if sub == "wizard":
        _cmd_config_wizard(args)
        return

    # Legacy / bare ``hmp config [OUTPUT]`` behaviour.
    if args.output == "schema":
        _cmd_config_schema(args)
        return
    if args.output == "wizard" or getattr(args, "wizard", False):
        if args.output == "wizard":
            args.output = None
        _cmd_config_wizard(args)
        return
    _cmd_config_template(args)


def _cmd_config_template(args: argparse.Namespace) -> None:
    from hydromodpy.core.config.generate_toml import generate_toml, available_modules

    if getattr(args, "list_modules", False):
        for name in available_modules():
            print(name)
        return

    if getattr(args, "ui", False):
        ui_module = (
            Path(__file__).resolve().parents[2]
            / "core" / "config" / "streamlit_config.py"
        )
        cmd = [sys.executable, "-m", "streamlit", "run", str(ui_module),
               "--server.headless", "true"]
        if args.output:
            cmd.extend(["--", "--load", str(args.output)])
        print("Launching interactive config editor...")
        subprocess.run(cmd)
        return

    if args.output and Path(args.output).is_dir():
        args.output = str(Path(args.output) / "config.toml")

    content = generate_toml(
        output_path=args.output,
        modules=getattr(args, "modules", None),
        profile=args.profile,
    )

    if args.output:
        print(f"Written to: {Path(args.output).resolve()}", file=sys.stderr)
    else:
        print(content)


def _cmd_config_check(args: argparse.Namespace) -> None:
    """Validate a TOML file against the HydroModPy Pydantic schema."""
    import tomllib

    from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig

    path = Path(args.file).expanduser().resolve()
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        print(f"Invalid TOML syntax: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    try:
        HydroModPyConfig.model_validate(raw)
    except Exception as exc:
        if type(exc).__name__ == "ValidationError":
            print(f"Config invalid: {path}", file=sys.stderr)
            for err in exc.errors():  # type: ignore[attr-defined]
                loc = ".".join(str(p) for p in err.get("loc", ()))
                msg = err.get("msg", "")
                print(f"  {loc}: {msg}", file=sys.stderr)
            sys.exit(EXIT_CONFIG)
        print(f"Config check failed: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    print(f"OK: {path}")


def _cmd_config_schema(args: argparse.Namespace) -> None:
    """Export the JSON Schema for the HydroModPy configuration."""
    from hydromodpy.core.config.schema_export import (
        export_schema,
        write_schema,
        _ensure_root_sections,
    )

    if getattr(args, "list_sections", False):
        for name in sorted(_ensure_root_sections()):
            print(name)
        return

    section = getattr(args, "section", None)
    out_path = getattr(args, "out", None)

    if out_path:
        written = write_schema(out_path, section=section)
        print(f"Written to: {written}", file=sys.stderr)
        return

    schema = export_schema(section=section)
    print(json.dumps(schema, indent=2, ensure_ascii=False))


def _cmd_config_wizard(args: argparse.Namespace) -> None:
    """Minimal stdin-based wizard to scaffold a TOML config."""
    from hydromodpy._cli.helpers import EXIT_USER_ABORT
    from hydromodpy.core.config.generate_toml import generate_toml

    def _ask(label: str, default: str | None = None) -> str:
        hint = f" [{default}]" if default else ""
        if not sys.stdin.isatty():
            return default or ""
        try:
            ans = input(f"{label}{hint}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            sys.exit(EXIT_USER_ABORT)
        return ans or (default or "")

    print("HydroModPy configuration wizard (non-interactive-safe)", file=sys.stderr)
    project = _ask("Project label", "my_project")
    profile = _ask("Profile (user/dev/expert)", getattr(args, "profile", None) or "user") or "user"
    output = args.output or _ask("Output TOML path", f"{project}.toml")

    dest = Path(output).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    generate_toml(output_path=str(dest), modules=None, profile=profile)
    print(f"Written: {dest}", file=sys.stderr)
    print(f"Try: hmp run {dest}")
