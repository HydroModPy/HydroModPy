"""``hmp config`` - configuration TOML template + schema + validator.

Subparsers:
  - ``hmp config template [OUTPUT]``  : generate a TOML template
  - ``hmp config check FILE.toml``    : validate a run, a calibration or a [sites] project
  - ``hmp config resolve FILE.toml``  : print the file its base_config chain resolves to
  - ``hmp config schema ...``         : export the JSON Schema, or with ``--editor``
                                        the editor schema of one TOML file
  - ``hmp config wizard``             : stdin-driven wizard
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.cli._conventions import verbosity_parser
from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, EXIT_USAGE, apply_verbosity

if TYPE_CHECKING:
    from hydromodpy.calibration.targets import CalibrationTarget

NAME: str = "config"
HELP: str = "Generate a TOML template, validate a config, or export the JSON Schema"


def register(subparsers) -> argparse.ArgumentParser:
    from hydromodpy.core.config_kit.profile import Profile

    profile_names = [profile.name.lower() for profile in Profile]

    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="config_command", required=False)

    tpl = sub.add_parser(
        "template",
        help="Generate a TOML configuration template",
        epilog="Examples:\n  hmp config template --list-modules\n  hmp config template run.toml --profile user --modules flow solver",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
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
        help="Module sections to include (default: all but sites, a campaign section)",
    )
    tpl.add_argument(
        "--list-modules",
        action="store_true",
        help="List available module names and exit",
    )

    chk = sub.add_parser(
        "check",
        help="Validate a run, a calibration or a whole [sites] project",
        parents=[verbosity_parser()],
        epilog=(
            "Examples:\n"
            "  hmp config check run.toml\n"
            "  hmp config check calibration.toml -v\n"
            "  hmp config check project.toml\n"
            "A calibration is read by its preflight and says which published method it\n"
            "runs and where it departs from it (-v adds the stages and the references).\n"
            "The last one expands a [sites] project and checks every case."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    chk.add_argument("file", help="Path to the TOML configuration")

    res = sub.add_parser(
        "resolve",
        help="Print the TOML a base_config chain resolves to, before validation",
        epilog="Example:\n  hmp config resolve run.toml",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    res.add_argument("file", help="Path to the TOML configuration")

    sch = sub.add_parser(
        "schema",
        help="Export the JSON Schema",
        epilog=(
            "Examples:\n"
            "  hmp config schema --list-sections\n"
            "  hmp config schema --section flow --out flow.schema.json\n"
            "  hmp config schema --editor --out hydromodpy-schema.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sch.add_argument(
        "--editor",
        action="store_true",
        help=(
            "Export the editor schema, the one published with the documentation: "
            "it checks one TOML file as written (base_config, __append, __delete, "
            "quantities with a unit) and requires no key"
        ),
    )
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
        epilog="Example:\n  hmp config targets calibration.toml --json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    tgt.add_argument("file", help="Path to the TOML configuration")
    tgt.add_argument(
        "--json",
        action="store_true",
        help="Emit the catalogue as JSON instead of a table",
    )

    wiz = sub.add_parser(
        "wizard",
        help="Interactive stdin-based TOML wizard",
        epilog="Example:\n  hmp config wizard run.toml --profile user",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    wiz.add_argument("output", nargs="?", help="Output TOML file (default: <project label>.toml)")
    wiz.add_argument(
        "--profile",
        choices=profile_names,
        default="user",
        help="Parameter visibility level (default: user)",
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
    if sub == "resolve":
        _cmd_config_resolve(args)
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
        "usage: hmp config {template,check,resolve,schema,targets,wizard} ...",
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

    from hydromodpy.calibration.parameter_resolution import (
        RECHARGE_VALUES_PATH,
        replaced_recharge_rate,
    )
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
    if replaced_recharge_rate(cfg) is not None:
        targets = [target for target in targets if target.path != RECHARGE_VALUES_PATH]
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

    ``bedleak`` resolves to ``my_lake.bedleak`` today because it is the
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


def _run_file_modules(modules: list[str] | None) -> list[str]:
    """Return *modules*, or every module a run file can carry when none is named.

    ``[sites]`` is the section of a campaign ``project.toml``: a run file that
    holds it is read as a project. It is written only when asked for.
    """
    from hydromodpy.core.toml_io.generator import available_modules

    if modules is not None:
        return modules
    return [name for name in available_modules() if name != "sites"]


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
        modules=_run_file_modules(getattr(args, "modules", None)),
        profile=getattr(args, "profile", "user"),
    )

    if output:
        print(f"Written to: {Path(output).resolve()}", file=sys.stderr)
    else:
        print(content)


def _cmd_config_resolve(args: argparse.Namespace) -> None:
    """Print the payload a ``base_config`` chain resolves to.

    This is what ``hmp config check`` validates: every file of the chain
    merged, the merge directives applied. Defaults of the model are not
    added, so the output shows only what the files say.
    """
    import tomllib

    from hydromodpy.core.toml_io.loader import load_toml_with_base_config
    from hydromodpy.core.toml_io.writer import dumps

    path = Path(args.file).expanduser().resolve()
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    try:
        payload = load_toml_with_base_config(path)
    except tomllib.TOMLDecodeError as exc:
        print(f"Invalid TOML syntax: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    except (TypeError, ValueError) as exc:
        print(f"Invalid base_config chain: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    sys.stdout.write(dumps(payload))


def _cmd_config_check(args: argparse.Namespace) -> None:
    """Validate a run, a calibration or a ``[sites]`` project with one verb.

    The check is :func:`hydromodpy.config.sites.check.check_project`: a run is
    loaded and goes through the checks of step 0 of ``hmp run``; a calibration
    is loaded and read by its preflight; a ``[sites]`` project is expanded
    case by case, and the errors come back grouped, each at the cell or the
    file it comes from.
    """
    from hydromodpy.config.sites.check import check_project, report_lines

    path = Path(args.file).expanduser().resolve()
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    verbosity = apply_verbosity(args, {})
    report = check_project(path)
    if report.kind == "calibration" and verbosity != "quiet":
        for line in _calibration_notes(path, verbose=verbosity in ("verbose", "debug")):
            print(line, file=sys.stderr)
    summary, *findings = report_lines(report)
    if report.ok:
        print(summary)
        for line in findings:
            print(line, file=sys.stderr)
        return
    print(summary, file=sys.stderr)
    for line in findings:
        print(line, file=sys.stderr)
    sys.exit(EXIT_CONFIG)


def _calibration_notes(path: Path, *, verbose: bool) -> list[str]:
    """Return what a calibration file runs: its published method, its departures, its comparisons.

    These lines inform, they never refuse: a file that does not load prints
    none, its refusal is already a finding of the check.
    """
    import warnings

    from hydromodpy.calibration.preflight import comparison_lines, protocol_lines
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.core.exceptions import ConfigError

    try:
        with warnings.catch_warnings():
            # The warnings of loading are findings of the check already.
            warnings.simplefilter("ignore")
            cfg = HydroModPyConfig.from_toml(path)
    except (ConfigError, ValueError, KeyError, FileNotFoundError):
        return []
    normal, detailed = protocol_lines(cfg)
    return [*normal, *(detailed if verbose else ()), *comparison_lines(cfg, path)]


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

    if getattr(args, "editor", False):
        _write_editor_schema(out_path, section=section, profile=profile)
        return

    if out_path:
        written = write_schema(out_path, section=section, profile=profile)
        print(f"Written to: {written}", file=sys.stderr)
        return

    schema = export_schema(section=section, profile=profile)
    print(json.dumps(schema, indent=2, ensure_ascii=False))


def _write_editor_schema(out_path: str | None, *, section: str | None, profile: str | None) -> None:
    """Print or write the editor schema of a whole TOML file."""
    from hydromodpy.config.schema_export import editor_schema

    if section or profile:
        print(
            "--editor describes a whole TOML file: it takes no --section and no --profile.",
            file=sys.stderr,
        )
        sys.exit(EXIT_USAGE)
    # Same serialization as the copy published with the documentation.
    text = json.dumps(editor_schema(), indent=2) + "\n"
    if not out_path:
        sys.stdout.write(text)
        return
    dest = Path(out_path).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    print(f"Written to: {dest}", file=sys.stderr)


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
    generate_toml(output_path=str(dest), modules=_run_file_modules(None), profile=profile)
    print(f"Written: {dest}", file=sys.stderr)
    print(f"Try: hmp run {dest}")
