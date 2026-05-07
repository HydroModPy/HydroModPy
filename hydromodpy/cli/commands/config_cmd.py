"""``hmp config`` - configuration TOML template + schema + validator.

Subparsers:
  - ``hmp config template [OUTPUT]``  : generate a TOML template
  - ``hmp config check FILE.toml``    : validate a TOML against the Pydantic schema
  - ``hmp config schema ...``         : export the JSON Schema (alias of ``hmp schema``)
  - ``hmp config wizard``             : stdin-driven wizard
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from pydantic import ValidationError

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND

NAME: str = "config"
HELP: str = "Generate a TOML template, validate a config, or export the JSON Schema"


def register(subparsers) -> argparse.ArgumentParser:
    from hydromodpy.core.config_kit.profile import Profile

    profile_names = [profile.name.lower() for profile in Profile]

    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="config_command", required=False)

    tpl = sub.add_parser("template", help="Generate a TOML configuration template")
    tpl.add_argument(
        "output",
        nargs="?",
        help="Output file (or directory); prints to stdout if omitted",
    )
    tpl.add_argument(
        "--profile",
        choices=profile_names,
        default="user",
        help="Parameter visibility level (default: user)",
    )
    tpl.add_argument(
        "--modules",
        nargs="+",
        help="Module sections to include (default: all)",
    )
    tpl.add_argument(
        "--list-modules",
        action="store_true",
        help="List available module names and exit",
    )
    tpl.add_argument(
        "--ui",
        action="store_true",
        help="Launch interactive Streamlit configuration editor",
    )

    chk = sub.add_parser("check", help="Validate a TOML against the Pydantic schema")
    chk.add_argument("file", help="Path to the TOML configuration")
    chk.add_argument(
        "--strict",
        action="store_true",
        help="Fail on warnings in addition to errors",
    )

    sch = sub.add_parser("schema", help="Export the JSON Schema")
    sch.add_argument(
        "--section", default=None, help="Export a single root TOML section (e.g. 'flow')"
    )
    sch.add_argument("--out", default=None, help="Write the JSON Schema to this file")
    sch.add_argument(
        "--profile",
        choices=profile_names,
        default=None,
        help="Filter the exported schema by profile (drops fields above the level)",
    )
    sch.add_argument("--list-sections", action="store_true", help="List available section names")

    wiz = sub.add_parser("wizard", help="Interactive stdin-based TOML wizard")
    wiz.add_argument("output", nargs="?")
    wiz.add_argument(
        "--profile",
        choices=profile_names,
        default="user",
    )

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    sub = getattr(args, "config_command", None) or "template"

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

    print(
        "usage: hmp config {template,check,schema,wizard} ...",
        file=sys.stderr,
    )
    sys.exit(EXIT_CONFIG)


def _cmd_config_template(args: argparse.Namespace) -> None:
    from hydromodpy.core.toml_io.generator import available_modules, generate_toml

    if getattr(args, "list_modules", False):
        for name in available_modules():
            print(name)
        return

    if getattr(args, "ui", False):
        ui_module = Path(__file__).resolve().parents[2] / "display" / "streamlit_config.py"
        cmd = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(ui_module),
            "--server.headless",
            "true",
        ]
        if args.output:
            cmd.extend(["--", "--load", str(args.output)])
        print("Launching interactive config editor...")
        subprocess.run(cmd)
        return

    output = getattr(args, "output", None)
    if output and Path(output).is_dir():
        output = str(Path(output) / "config.toml")

    content = generate_toml(
        output_path=output,
        modules=getattr(args, "modules", None),
        profile=getattr(args, "profile", "user"),
    )

    if output:
        print(f"Written to: {Path(output).resolve()}", file=sys.stderr)
    else:
        print(content)


def _cmd_config_check(args: argparse.Namespace) -> None:
    """Validate a TOML file against the HydroModPy Pydantic schema.

    Honours ``base_config`` inheritance: overlay files are merged with their
    base before validation so ``hmp config check`` sees the same resolved
    payload as ``hmp run``.
    """
    import tomllib

    from hydromodpy.config import HydroModPyConfig

    path = Path(args.file).expanduser().resolve()
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    try:
        HydroModPyConfig.from_toml(path)
    except tomllib.TOMLDecodeError as exc:
        print(f"Invalid TOML syntax: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    except ValidationError as exc:
        print(f"Config invalid: {path}", file=sys.stderr)
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()))
            msg = err.get("msg", "")
            if "input" in err:
                print(f"  {loc}: {msg} (input={err.get('input')!r})", file=sys.stderr)
            else:
                print(f"  {loc}: {msg}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    except ValueError as exc:
        print(f"Invalid base_config chain: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    except Exception as exc:
        print(f"Config check failed: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    print(f"OK: {path}")


def _cmd_config_schema(args: argparse.Namespace) -> None:
    """Export the JSON Schema for the HydroModPy configuration."""
    from hydromodpy.config.schema_export import (
        _ensure_root_sections,
        export_schema,
        write_schema,
    )

    if getattr(args, "list_sections", False):
        for name in sorted(_ensure_root_sections()):
            print(name)
        return

    section = getattr(args, "section", None)
    out_path = getattr(args, "out", None)
    profile = getattr(args, "profile", None)

    if out_path:
        written = write_schema(out_path, section=section, profile=profile)
        print(f"Written to: {written}", file=sys.stderr)
        return

    schema = export_schema(section=section, profile=profile)
    print(json.dumps(schema, indent=2, ensure_ascii=False))


def _cmd_config_wizard(args: argparse.Namespace) -> None:
    """Minimal stdin-based wizard to scaffold a TOML config."""
    from hydromodpy.cli.helpers import EXIT_USER_ABORT
    from hydromodpy.core.toml_io.generator import generate_toml

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
    profile = (
        _ask(
            "Profile (user/dev/expert)",
            getattr(args, "profile", None) or "user",
        )
        or "user"
    )
    output = getattr(args, "output", None) or _ask(
        "Output TOML path",
        f"{project}.toml",
    )

    dest = Path(output).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    generate_toml(output_path=str(dest), modules=None, profile=profile)
    print(f"Written: {dest}", file=sys.stderr)
    print(f"Try: hmp run {dest}")
