"""The --profile flag: where the report goes and the pyinstrument wrapper."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from hydromodpy.cli.exit_codes import EXIT_CONFIG, refuse


def profile_output_of(
    args: argparse.Namespace, raw_toml: Mapping[str, Any], target: Path
) -> Path | None:
    """Return where ``--profile``, else ``[workflow] profile``, writes its report, or ``None``."""
    profile_arg = getattr(args, "profile", None)
    if profile_arg is None and raw_toml:
        profile_arg = profile_arg_from_toml(raw_toml)
    return resolve_profile_output(profile_arg, target)


# ---------------------------------------------------------------------------
# Profiling (--profile flag, pyinstrument)
# ---------------------------------------------------------------------------


def _require_pyinstrument() -> None:
    """Exit with :data:`EXIT_CONFIG` when pyinstrument is not installed."""
    try:
        import pyinstrument  # noqa: F401
    except ImportError:
        refuse(
            "pyinstrument is required for --profile. Install it with: pip install pyinstrument",
            EXIT_CONFIG,
        )


def profile_arg_from_toml(raw_toml: Mapping[str, Any]) -> str | None:
    """Map ``[workflow].profile`` to the ``--profile`` argument convention."""
    workflow_section = raw_toml.get("workflow")
    if not isinstance(workflow_section, dict):
        return None
    value = workflow_section.get("profile")
    if value is True:
        return ""
    if isinstance(value, str) and value:
        return value
    return None


def resolve_profile_output(profile_arg: str | None, config_path: Path) -> Path | None:
    """Resolve the ``--profile`` argument to an HTML report path.

    ``None`` means profiling is disabled. An empty string (bare ``--profile``)
    defaults to ``<config>.profile.html`` next to the config. Fails fast when
    profiling is requested but pyinstrument is missing.
    """
    if profile_arg is None:
        return None
    _require_pyinstrument()
    if profile_arg:
        return Path(profile_arg).expanduser().resolve()
    return config_path.with_suffix(".profile.html")


@contextmanager
def profile_run(output: Path | None, *, description: str | None = None) -> Iterator[None]:
    """Profile the wrapped block with pyinstrument.

    No-op when ``output`` is None. ``description`` labels the report header
    (defaults to pyinstrument's call-site text). Writes the HTML report to
    ``output`` and prints the call-tree summary to stderr, even when the
    block raises or is interrupted. Exits with :data:`EXIT_CONFIG` when
    pyinstrument is missing.
    """
    if output is None:
        yield
        return
    _require_pyinstrument()
    from pyinstrument import Profiler

    profiler = Profiler()
    profiler.start(target_description=description)
    try:
        yield
    finally:
        profiler.stop()
        # Best-effort emission: a report failure must never mask the run
        # outcome or replace its typed exit code.
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(profiler.output_html(), encoding="utf-8")
            print(profiler.output_text(unicode=True, color=sys.stderr.isatty()), file=sys.stderr)
            print(f"  Profile report: {output}", file=sys.stderr)
        except Exception as exc:
            print(f"  WARNING: profile report write failed: {exc}", file=sys.stderr)


__all__ = (
    "profile_arg_from_toml",
    "profile_output_of",
    "profile_run",
    "resolve_profile_output",
)
