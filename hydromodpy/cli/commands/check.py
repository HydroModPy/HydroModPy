"""``hmp check`` - check a run, a calibration or a whole ``[sites]`` project.

Every fault is listed at once, one line each. A key the file does not write yet is
an error, or with ``--partial`` a ``to_fill`` that stops nothing. A calibration is
read by its preflight and says which published method it runs and where it departs
from it (``-v`` adds the stages and the references). A ``[sites]`` project is
expanded and every case is checked. ``-v`` also says which workspace the file
resolves to, with its folders. ``hydromodpy.project.api.check`` does the checking.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.cli.conventions import format_parser, verbosity_parser, workspace_parser
from hydromodpy.cli.exit_codes import EXIT_CONFIG, EXIT_NOT_FOUND, refuse
from hydromodpy.cli.output import emit
from hydromodpy.cli.refs import base_named_by_w

if TYPE_CHECKING:
    from hydromodpy.core.diagnostic import Diagnostic

NAME: str = "check"
HELP: str = "Check a run, a calibration or a whole [sites] project, every fault at once"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog=(
            "Examples:\n"
            "  hmp check run.toml\n"
            "  hmp check draft.toml --partial\n"
            "  hmp check calibration.toml -v\n"
            "  hmp check project.toml --inputs --lang fr\n"
            "Every fault is listed at once, one line each. A key the file does not write\n"
            "yet is an error, or with --partial a to_fill that stops nothing.\n"
            "A calibration is read by its preflight and says which published method it\n"
            "runs and where it departs from it (-v adds the stages and the references).\n"
            "The last one expands a [sites] project and checks every case.\n"
            "-v also says which workspace the file resolves to, with its folders."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("file", help="Path to the TOML configuration")
    parser.add_argument(
        "--partial",
        action="store_true",
        help="Check a draft: a required key not written yet is to_fill, not an error",
    )
    parser.add_argument(
        "--inputs",
        action="store_true",
        help="Also read the header of each input file, local or by its final URL (downloads nothing)",
    )
    parser.add_argument(
        "--lang",
        choices=("en", "fr"),
        default="en",
        help="Language of the phrase of each diagnostic (default: en)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    """Check a run, a calibration or a ``[sites]`` project with ``hydromodpy.project.api.check``.

    The verb gives every diagnostic at once. The file is refused, with the
    exit code of a configuration, when one of them is an ``error``. ``--partial``
    keeps a required key not written yet as ``to_fill``, which refuses nothing.
    """
    from hydromodpy.config.check import phrase
    from hydromodpy.core.config_kit.written import experimental_keys_line
    from hydromodpy.core.logging import current_verbosity
    from hydromodpy.project.api import check
    from hydromodpy.project.doctor import probe_toml_workspace

    path = Path(args.file).expanduser().resolve()
    if not path.is_file():
        refuse(f"File not found: {path}", EXIT_NOT_FOUND)

    verbosity = current_verbosity()
    verbose = verbosity in ("verbose", "debug")
    base = base_named_by_w(args.workspace)
    diagnostics = check(path, partial=args.partial, inputs=args.inputs, base=base)
    if verbosity != "quiet":
        for line in _calibration_notes(path, verbose=verbose):
            print(line, file=sys.stderr)
    where = probe_toml_workspace(path) if verbose or args.format != "table" else []
    ok = not any(item.severity == "error" for item in diagnostics)
    experimental = [item.path for item in diagnostics if item.code == "experimental_key"]
    if experimental and verbosity != "quiet":
        print(experimental_keys_line(experimental), file=sys.stderr)
    findings = [item for item in diagnostics if item.code != "experimental_key"]

    def table() -> None:
        print(
            f"OK: {path}" if ok else f"Config invalid: {path}",
            file=sys.stdout if ok else sys.stderr,
        )
        for item in findings:
            print(_diagnostic_text(item, args.lang), file=sys.stderr)
        for entry in where:
            print(f"{entry['status']:<4} {entry['name']}: {entry['detail']}", file=sys.stderr)

    emit(
        args,
        "check",
        {
            "ok": ok,
            "diagnostics": [
                {**item.to_dict(), "phrase": phrase(item.code, args.lang)} for item in diagnostics
            ],
            "workspace": where,
        },
        table=table,
    )
    if not ok:
        sys.exit(EXIT_CONFIG)


def _diagnostic_text(diagnostic: Diagnostic, lang: str) -> str:
    """Return a diagnostic as ``severity path:line: phrase``, its detail on the next line."""
    from hydromodpy.config.check import phrase

    where = diagnostic.path or "<document>"
    if diagnostic.line_number is not None:
        where = f"{where}:{diagnostic.line_number}"
    text = f"  {diagnostic.severity} {where}: {phrase(diagnostic.code, lang)}"
    return f"{text}\n    {diagnostic.detail}" if diagnostic.detail else text


def _calibration_notes(path: Path, *, verbose: bool) -> list[str]:
    """Return what a calibration file runs: its published method, its departures, its comparisons.

    These lines inform, they never refuse: a file that does not load prints
    none, its refusal is already a finding of the check. A file with no
    ``[calibration]`` prints none either.
    """
    from hydromodpy.calibration.preflight_report import comparison_lines, protocol_lines
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.core.config_kit.said import collecting
    from hydromodpy.core.exceptions import ConfigError

    try:
        with collecting():
            # The warnings of loading are findings of the check already.
            cfg = HydroModPyConfig.from_toml(path)
    except (ConfigError, ValueError, KeyError, FileNotFoundError):
        return []
    if cfg.calibration is None:
        return []
    normal, detailed = protocol_lines(cfg)
    return [*normal, *(detailed if verbose else ()), *comparison_lines(cfg, path)]
