"""``hmp config`` - configuration TOML template + schema + validator.

Subparsers:
  - ``hmp config template [OUTPUT]``  : generate a TOML template
  - ``hmp config check FILE.toml``    : validate a TOML against the Pydantic schema
  - ``hmp config schema ...``         : export the JSON Schema (same as ``hmp dev schema``)
  - ``hmp config wizard``             : stdin-driven wizard
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND
from hydromodpy.core.exceptions import ConfigError

if TYPE_CHECKING:
    from hydromodpy.calibration.targets import CalibrationTarget

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

    chk = sub.add_parser("check", help="Validate a TOML against the Pydantic schema")
    chk.add_argument("file", help="Path to the TOML configuration")

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

    tgt = sub.add_parser(
        "targets",
        help="List what this project exposes to a calibration",
    )
    tgt.add_argument("file", help="Path to the TOML configuration")
    tgt.add_argument(
        "--json",
        action="store_true",
        help="Emit the catalogue as JSON instead of a table",
    )

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
    if sub == "targets":
        _cmd_config_targets(args)
        return
    if sub == "wizard":
        _cmd_config_wizard(args)
        return

    print(
        "usage: hmp config {template,check,schema,targets,wizard} ...",
        file=sys.stderr,
    )
    sys.exit(EXIT_CONFIG)


def _cmd_config_targets(args: argparse.Namespace) -> None:
    """Print what this configuration exposes to a calibration.

    The answer is derived from the resolved configuration, so it names the
    parameters and boundaries this project actually declares, with the value it
    holds today and the range the physical registry enforces where it knows one.
    Those three columns are what a bound is written from.
    """
    import json

    from hydromodpy.calibration.targets import calibration_targets
    from hydromodpy.config import HydroModPyConfig

    path = Path(args.file).expanduser().resolve()
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    try:
        cfg = HydroModPyConfig.from_toml(path)
    except Exception as exc:
        print(f"Config invalid: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    targets = calibration_targets(cfg)
    _warn_about_suffix_only_parameters(path, targets)

    if getattr(args, "json", False):
        print(json.dumps([target.to_dict() for target in targets], indent=2))
        return

    if not targets:
        print(f"{path.name} declares nothing a calibration could move.", file=sys.stderr)
        return

    name_width = max(len(target.name) for target in targets)
    print(f"{'name'.ljust(name_width)}  {'current':>12}  {'unit':>9}  {'physical range':<24}  path")
    for target in targets:
        bounds = (
            f"{target.physical_bounds[0]:g} .. {target.physical_bounds[1]:g}"
            if target.physical_bounds
            else "-"
        )
        current = "-" if target.current is None else f"{target.current:g}"
        print(
            f"{target.name.ljust(name_width)}  {current:>12}  "
            f"{(target.units or '-'):>9}  {bounds:<24}  {target.path}"
        )
    print(
        f"\nWrite one as [calibration.parameters.{targets[0].name}] with a bounds pair. "
        "The path is resolved from the name; write it yourself only to reach "
        "something this catalogue does not list.",
        file=sys.stderr,
    )


def _warn_about_suffix_only_parameters(path: Path, targets: list[CalibrationTarget]) -> None:
    """Name every declared parameter that reaches its target only by suffix.

    ``bedleak`` resolves to ``reservoir_cheze.bedleak`` today because it is the
    only target ending in ``.bedleak``. That stops the day a second lake also
    carries one, so the file is told its canonical spelling while the shortcut
    still works.
    """
    from hydromodpy.calibration.targets import targets_by_name
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config

    payload = load_toml_with_base_config(path)
    declared = payload.get("calibration", {}).get("parameters", {})
    if not isinstance(declared, dict) or not declared:
        return

    by_name = targets_by_name(targets)
    for name, decl in declared.items():
        if not isinstance(decl, dict) or "path" in decl or "target" in decl:
            continue
        if name in by_name:
            continue
        ending = [target for target in targets if target.name.endswith(f".{name}")]
        if len(ending) == 1:
            print(
                f"[calibration.parameters.{name}] reaches {ending[0].name!r} only "
                f"because it is the sole target ending in '.{name}'. Write "
                f"[calibration.parameters.{ending[0].name}] to keep resolving it "
                "once a second one also answers to this name.",
                file=sys.stderr,
            )


def _cmd_config_template(args: argparse.Namespace) -> None:
    from hydromodpy.core.toml_io.generator import available_modules, generate_toml

    if getattr(args, "list_modules", False):
        for name in available_modules():
            print(name)
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

    Dispatches on ``[workflow] mode`` so comparison TOMLs are validated by
    ``SimulationComparisonConfig`` and testbed TOMLs by ``TestbedConfig``
    (or ``RegionalLabConfig`` for the ``regional_lab`` profile) instead of
    ``HydroModPyConfig``.
    """
    import tomllib

    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config

    path = Path(args.file).expanduser().resolve()
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    try:
        raw_toml = load_toml_with_base_config(path)
    except tomllib.TOMLDecodeError as exc:
        print(f"Invalid TOML syntax: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    except ValueError as exc:
        print(f"Invalid base_config chain: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    workflow_section = raw_toml.get("workflow") if isinstance(raw_toml, dict) else None
    mode = workflow_section.get("mode") if isinstance(workflow_section, dict) else None

    try:
        if mode == "comparison":
            from hydromodpy.analysis.comparison.experiment_config import (
                SimulationComparisonConfig,
            )

            SimulationComparisonConfig.from_toml(raw_toml, config_path=path)
        elif mode == "testbed":
            from hydromodpy.analysis.testbed.config import TestbedConfig
            from hydromodpy.analysis.testbed.profiles import (
                GENERIC_TESTBED_PROFILE,
                REGIONAL_LAB_PROFILE,
                resolve_testbed_profile,
            )

            profile = resolve_testbed_profile(raw_toml)
            if profile == REGIONAL_LAB_PROFILE:
                from hydromodpy.analysis.testbed.regional_lab_config import (
                    RegionalLabConfig,
                )

                RegionalLabConfig.from_toml(raw_toml, config_path=path)
            elif profile == GENERIC_TESTBED_PROFILE:
                TestbedConfig.from_toml(raw_toml, config_path=path)
            else:
                raise ValueError(f"Unsupported testbed profile: {profile}")
        elif mode == "site_selection":
            from hydromodpy.workflow.site_selection import (
                load_hydrometry_config_for_site_selection,
                load_site_selection_config,
            )

            load_site_selection_config(path)
            if "hydrometry" in raw_toml:
                load_hydrometry_config_for_site_selection(path)
        else:
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
    except (KeyError, FileNotFoundError) as exc:
        print(f"Config invalid: {path}", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    except ValueError as exc:
        # base_config is already resolved above; a ValueError here is the
        # validation error that from_toml wraps (its message carries the
        # file:line:key detail), not a base_config chain failure.
        print(f"Config invalid: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    except ConfigError as exc:
        # A typed config refusal is an invalid config, not a crashed check: it
        # already carries the TOML path and the key to change.
        print(f"Config invalid: {exc}", file=sys.stderr)
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
    from hydromodpy.cli.helpers import EXIT_SIGINT
    from hydromodpy.core.toml_io.generator import generate_toml

    def _ask(label: str, default: str | None = None) -> str:
        hint = f" [{default}]" if default else ""
        if not sys.stdin.isatty():
            return default or ""
        try:
            ans = input(f"{label}{hint}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            sys.exit(EXIT_SIGINT)
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
