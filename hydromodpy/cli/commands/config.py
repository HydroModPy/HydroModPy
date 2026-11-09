"""``hmp config`` - configuration TOML template + schema + validator.

Subparsers:
  - ``hmp config template [--to FILE]``  : generate a TOML template
  - ``hmp config check FILE.toml``       : validate a run, a calibration or a [sites] project
  - ``hmp config resolve FILE.toml``     : print the file its base_config chain resolves to
  - ``hmp config schema ...``            : export the JSON Schema, with ``--editor`` the editor
                                           schema of one TOML file, with ``--bundle`` the files
                                           a frontend reads
  - ``hmp config validate-field P V``    : validate one field value
  - ``hmp config wizard``                : stdin-driven wizard
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.cli.conventions import (
    add_destination,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import (
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    project_named_by_w,
    refuse,
)
from hydromodpy.cli.output import emit

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
        parents=[workspace_parser(reads_none=True)],
        epilog="Examples:\n  hmp config template --list-modules\n  hmp config template --to run.toml --profile user --modules flow solver",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_destination(
        tpl, help="Output file (or directory); prints to stdout if omitted", metavar="FILE"
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
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog=(
            "Examples:\n"
            "  hmp config check run.toml\n"
            "  hmp config check calibration.toml -v\n"
            "  hmp config check project.toml\n"
            "A calibration is read by its preflight and says which published method it\n"
            "runs and where it departs from it (-v adds the stages and the references).\n"
            "The last one expands a [sites] project and checks every case.\n"
            "-v also says which workspace the file resolves to, with its folders."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    chk.add_argument("file", help="Path to the TOML configuration")

    res = sub.add_parser(
        "resolve",
        help="Print the TOML a base_config chain resolves to, before validation",
        parents=[workspace_parser()],
        epilog="Example:\n  hmp config resolve run.toml",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    res.add_argument("file", help="Path to the TOML configuration")

    sch = sub.add_parser(
        "schema",
        help="Export the JSON Schema",
        parents=[workspace_parser(reads_none=True)],
        epilog=(
            "Examples:\n"
            "  hmp config schema --list-sections\n"
            "  hmp config schema --section flow --to flow.schema.json\n"
            "  hmp config schema --editor --to hydromodpy-schema.json\n"
            "  hmp config schema --bundle --to schema_dir"
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
    sch.add_argument(
        "--bundle",
        action="store_true",
        help=(
            "Write three files into the folder --to names: config.json (the JSON Schema of "
            "HydroModPyConfig), config_meta.json (the root sections in order, their titles and "
            "UI groups) and field_validators.json (the validator type of each field path)"
        ),
    )
    add_destination(sch, help="Write the JSON Schema to this file", metavar="FILE")
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
        parents=[workspace_parser(), format_parser()],
        epilog="Example:\n  hmp config targets calibration.toml --format json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    tgt.add_argument("file", help="Path to the TOML configuration")

    wiz = sub.add_parser(
        "wizard",
        help="Interactive stdin-based TOML wizard",
        parents=[workspace_parser(reads_none=True)],
        epilog="Example:\n  hmp config wizard --to run.toml --profile user",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_destination(wiz, help="Output TOML file (default: <project label>.toml)", metavar="FILE")
    wiz.add_argument(
        "--profile",
        choices=profile_names,
        default="user",
        help="Parameter visibility level (default: user)",
    )

    val = sub.add_parser(
        "validate-field",
        help="Validate one field value without loading a whole config",
        parents=[workspace_parser(reads_none=True), format_parser()],
        epilog="Example:\n  hmp config validate-field mesh.engine triangle",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    val.add_argument("path", help="Dotted field path")
    val.add_argument("value", help="Candidate value")
    val.add_argument("--context", default=None, help="TOML providing form state")

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    # A bare ``hmp config`` writes a template. ``validate-field`` is parsed but has no handler.
    handlers = {
        "check": _cmd_config_check,
        "template": _cmd_config_template,
        "resolve": _cmd_config_resolve,
        "schema": _cmd_config_schema,
        "targets": _cmd_config_targets,
        "wizard": _cmd_config_wizard,
    }
    handler = handlers.get(args.config_command or "template")
    if handler is None:
        refuse("usage: hmp config {template,check,resolve,schema,targets,wizard} ...", EXIT_CONFIG)
    handler(args)


def _cmd_config_targets(args: argparse.Namespace) -> None:
    """Print what this configuration exposes to a calibration.

    The answer is derived from the resolved configuration, so it names the
    parameters and boundaries this project actually declares, with the value it
    holds today and the range the physical registry enforces where it knows one.
    Those three columns are what a bound is written from.
    """
    from hydromodpy.calibration.parameter_resolution import (
        RECHARGE_VALUES_PATH,
        replaced_recharge_rate,
    )
    from hydromodpy.calibration.targets import calibration_targets
    from hydromodpy.config import HydroModPyConfig

    path = Path(args.file).expanduser().resolve()
    if not path.is_file():
        refuse(f"File not found: {path}", EXIT_NOT_FOUND)

    try:
        with project_named_by_w(getattr(args, "workspace", None)):
            cfg = HydroModPyConfig.from_toml(path)
    except Exception as exc:  # noqa: BLE001 - any load failure says the file is invalid
        refuse(f"Config invalid: {exc}", EXIT_CONFIG, cause=exc)

    targets = calibration_targets(cfg)
    if replaced_recharge_rate(cfg) is not None:
        targets = [target for target in targets if target.path != RECHARGE_VALUES_PATH]
    _warn_about_suffix_only_parameters(path, targets)

    def table() -> None:
        if not targets:
            print(f"{path.name} declares nothing a calibration could move.", file=sys.stderr)
            return
        names = [_toml_key(target.name) for target in targets]
        name_width = max(len(name) for name in names)
        print(
            f"{'name'.ljust(name_width)}  {'current':>12}  {'unit':>9}  {'space':<8}  "
            f"{'draw':<11}  {'default bounds':<24}  {'physical range':<24}  path"
        )
        for name, target in zip(names, targets, strict=True):
            current = "-" if target.current is None else f"{target.current:g}"
            space, draw, default = (
                ("-", "-", None)
                if target.calibrable is None
                else (
                    target.calibrable.search_space,
                    target.calibrable.sampling,
                    target.calibrable.bounds,
                )
            )
            print(
                f"{name.ljust(name_width)}  {current:>12}  {(target.units or '-'):>9}  "
                f"{space:<8}  {draw:<11}  {_range_text(default):<24}  "
                f"{_range_text(target.physical_bounds):<24}  {target.path}"
            )
        print(
            f"\nWrite one as [calibration.parameters.{names[0]}] with a bounds pair. "
            "The path is resolved from the name; write it yourself only to reach "
            "something this catalogue does not list.",
            file=sys.stderr,
        )

    emit(args, "config targets", [target.to_dict() for target in targets], table=table)


def _toml_key(name: str) -> str:
    """Return ``name`` as a TOML key: quoted when it holds a dot or any other non-bare character."""
    return name if re.fullmatch(r"[A-Za-z0-9_-]+", name) else f'"{name}"'


def _range_text(bounds: tuple[float, float] | None) -> str:
    """Return a pair of bounds as ``low .. high``, or ``-`` for none."""
    return "-" if bounds is None else f"{bounds[0]:g} .. {bounds[1]:g}"


def _warn_about_suffix_only_parameters(path: Path, targets: list[CalibrationTarget]) -> None:
    """Name every declared parameter that reaches its target only by suffix.

    ``bedleak`` resolves to ``my_lake.bedleak`` today because it is the
    only target ending in ``.bedleak``. That stops the day a second lake also
    carries one, so the file is told its canonical spelling while the shortcut
    still works.
    """
    from hydromodpy.calibration.targets import targets_by_name
    from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config

    payload = load_toml_with_base_config(path, root=ROOT_CONFIG)
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
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.core.toml_io.generator import available_modules

    if modules is not None:
        return modules
    return [name for name in available_modules(HydroModPyConfig) if name != "sites"]


def _cmd_config_template(args: argparse.Namespace) -> None:
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.config.toml_examples import flow_examples
    from hydromodpy.core.toml_io.generator import available_modules, generate_toml

    if getattr(args, "list_modules", False):
        for name in available_modules(HydroModPyConfig):
            print(name)
        return

    output = args.to
    if output and Path(output).is_dir():
        output = str(Path(output) / "config.toml")

    content = generate_toml(
        output_path=output,
        modules=_run_file_modules(getattr(args, "modules", None)),
        profile=getattr(args, "profile", "user"),
        root=HydroModPyConfig,
        flow_examples=flow_examples,
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

    from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config
    from hydromodpy.core.toml_io.writer import dumps

    path = Path(args.file).expanduser().resolve()
    if not path.is_file():
        refuse(f"File not found: {path}", EXIT_NOT_FOUND)
    try:
        with project_named_by_w(args.workspace):
            payload = load_toml_with_base_config(path, root=ROOT_CONFIG)
    except tomllib.TOMLDecodeError as exc:
        refuse(f"Invalid TOML syntax: {exc}", EXIT_CONFIG, cause=exc)
    except (TypeError, ValueError) as exc:
        refuse(f"Invalid base_config chain: {exc}", EXIT_CONFIG, cause=exc)
    sys.stdout.write(dumps(payload))


def _cmd_config_check(args: argparse.Namespace) -> None:
    """Validate a run, a calibration or a ``[sites]`` project with one verb.

    The check is :func:`hydromodpy.project.check.check_project`: a run is
    loaded and goes through the checks of step 0 of ``hmp run``; a calibration
    is loaded and read by its preflight; a ``[sites]`` project is expanded
    case by case, and the errors come back grouped, each at the cell or the
    file it comes from.
    """
    from hydromodpy.cli.commands.doctor import probe_toml_workspace
    from hydromodpy.core.config_kit.written import experimental_keys_line
    from hydromodpy.core.logging import current_verbosity
    from hydromodpy.project.check import check_project, report_lines

    path = Path(args.file).expanduser().resolve()
    if not path.is_file():
        refuse(f"File not found: {path}", EXIT_NOT_FOUND)

    verbosity = current_verbosity()
    verbose = verbosity in ("verbose", "debug")
    with project_named_by_w(args.workspace):
        report = check_project(path)
        if report.kind == "calibration" and verbosity != "quiet":
            for line in _calibration_notes(path, verbose=verbose):
                print(line, file=sys.stderr)
        where = probe_toml_workspace(path) if verbose or args.format != "table" else []
    if report.experimental_keys and verbosity != "quiet":
        print(experimental_keys_line(report.experimental_keys), file=sys.stderr)
    summary, *findings = report_lines(report)

    def table() -> None:
        print(summary, file=sys.stdout if report.ok else sys.stderr)
        for line in findings:
            print(line, file=sys.stderr)
        for check in where:
            print(f"{check['status']:<4} {check['name']}: {check['detail']}", file=sys.stderr)

    emit(
        args,
        "config check",
        {
            "ok": report.ok,
            "kind": report.kind,
            "n_cases": report.n_cases,
            "summary": summary,
            "errors": list(report.errors),
            "warnings": list(report.warnings),
            "experimental_keys": list(report.experimental_keys),
            "workspace": where,
        },
        table=table,
    )
    if not report.ok:
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
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.core.config_kit.registry import root_sections
    from hydromodpy.schema.config_schema import export_schema, write_schema

    if getattr(args, "list_sections", False):
        for name in sorted(root_sections(HydroModPyConfig)):
            print(name)
        return

    section = getattr(args, "section", None)
    out_path = args.to
    profile = getattr(args, "profile", None)

    if args.bundle:
        _write_schema_bundle(args)
        return
    if getattr(args, "editor", False):
        _write_editor_schema(out_path, section=section, profile=profile)
        return

    if out_path:
        written = write_schema(out_path, HydroModPyConfig, section=section, profile=profile)
        print(f"Written to: {written}", file=sys.stderr)
        return

    schema = export_schema(HydroModPyConfig, section=section, profile=profile)
    print(json.dumps(schema, indent=2, ensure_ascii=False))


def _write_schema_bundle(args: argparse.Namespace) -> None:
    """Write the JSON Schema and the files a frontend reads with it into the folder ``--to``."""
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.schema import export_full_schema

    if args.to is None or args.editor or args.section or args.profile:
        refuse(
            "--bundle writes three files about the whole config into a folder: it needs --to "
            "and takes no --editor, --section or --profile.",
            EXIT_USAGE,
        )
    folder = Path(args.to).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    for key, path in export_full_schema(folder, root=HydroModPyConfig).items():
        print(f"{key}: {path}", file=sys.stderr)


def _cmd_config_validate_field(args: argparse.Namespace) -> None:
    """Validate one field value, for a frontend that checks a form as it is filled."""
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.schema import validate_field

    payload = validate_field(
        args.path, args.value, root=HydroModPyConfig, context=_load_context(args.context)
    ).as_dict()

    def table() -> None:
        print(f"{args.path}: {'valid' if payload['valid'] else 'invalid'}")
        if payload["error"]:
            print(f"  {payload['error']}", file=sys.stderr)
        for line in payload["warnings"]:
            print(f"  warning: {line}", file=sys.stderr)

    emit(args, "config validate-field", payload, table=table)
    if not payload["valid"]:
        sys.exit(EXIT_CONFIG)


def _load_context(ctx_path: str | None) -> dict | None:
    """Return the TOML that gives the state of the form, when ``--context`` names one."""
    import tomllib

    if not ctx_path:
        return None
    ctx_file = Path(ctx_path).expanduser().resolve()
    if not ctx_file.is_file():
        refuse(f"context TOML not found: {ctx_file}", EXIT_NOT_FOUND)
    with ctx_file.open("rb") as fh:
        return tomllib.load(fh)


def _write_editor_schema(out_path: str | None, *, section: str | None, profile: str | None) -> None:
    """Print or write the editor schema of a whole TOML file."""
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.schema.config_schema import editor_schema

    if section or profile:
        refuse(
            "--editor describes a whole TOML file: it takes no --section and no --profile.",
            EXIT_USAGE,
        )
    # Same serialization as the copy published with the documentation.
    text = json.dumps(editor_schema(HydroModPyConfig), indent=2) + "\n"
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
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.config.toml_examples import flow_examples
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
    output = args.to or _ask(
        "Output TOML path",
        f"{project}.toml",
    )

    dest = Path(output).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    generate_toml(
        output_path=str(dest),
        modules=_run_file_modules(None),
        profile=profile,
        root=HydroModPyConfig,
        flow_examples=flow_examples,
    )
    print(f"Written: {dest}", file=sys.stderr)
    print(f"Try: hmp run {dest}")
