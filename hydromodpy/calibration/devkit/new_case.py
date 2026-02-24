"""
Create a new calibration2 case from file templates.

This module provides one high-level function, `scaffold_case(...)`, that writes
the standard case skeleton under `calibration2/cases/<case_name>/`.

Why this exists
---------------
- New contributors should start from a working, consistent layout.
- Boilerplate should be generated once, not rewritten by hand.
- The generated case should immediately match the orchestrator contract.

Typical usage moment
--------------------
Run this when starting a brand new scientific case. The scaffold gives a
minimal but runnable structure that already fits:
- the case interface contract (`AbstractCalibrationCase`),
- TOML-driven calibration orchestration,
- calibration2 folder conventions.

What this module does not do
----------------------------
- It does not register the case automatically in any external catalog.
- It does not infer domain equations or data loading logic.
- It does not run calibration by itself; it only creates files.
"""

from __future__ import annotations

from pathlib import Path
import re


_CASE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_TOKENS = (
    "__CASE_NAME__",
    "__CASE_TITLE__",
    "__CASE_CLASS__",
)

_TEMPLATE_FILES = (
    "__init__.py.tmpl",
    "README.md.tmpl",
    "case_config.py.tmpl",
    "workflow.py.tmpl",
    "case_implementation.py.tmpl",
    "run_calibration.py.tmpl",
    "config_calibration.toml.tmpl",
)
# Mandatory templates that define the minimal runnable case skeleton.


def _calibration2_root() -> Path:
    """Return absolute path to `hydromodpy/calibration2/`."""
    return Path(__file__).resolve().parents[1]


def _templates_root() -> Path:
    """Return absolute path to the case-template directory."""
    return _calibration2_root() / "devkit" / "templates" / "case"


def _normalize_case_name(case_name: str) -> str:
    """Validate and canonicalize a case key (`snake_case`, lower-case)."""
    name = str(case_name).strip().lower()
    if not _CASE_NAME_RE.match(name):
        raise ValueError(
            "case_name must match pattern '^[a-z][a-z0-9_]*$' "
            f"(got '{case_name}')"
        )
    return name


def _to_case_class_name(case_name: str) -> str:
    """Convert a case key to a conventional class name."""
    parts = [chunk for chunk in case_name.split("_") if chunk]
    title = "".join(part.capitalize() for part in parts)
    return f"{title}CalibrationCase"


def _render_template(template_text: str, *, case_name: str, case_title: str, case_class: str) -> str:
    """Replace template tokens with concrete case identifiers."""
    rendered = str(template_text)
    replacements = {
        "__CASE_NAME__": case_name,
        "__CASE_TITLE__": case_title,
        "__CASE_CLASS__": case_class,
    }
    for token in _TOKENS:
        rendered = rendered.replace(token, replacements[token])
    return rendered


def scaffold_case(
    case_name: str,
    *,
    destination: str | Path | None = None,
    overwrite: bool = False,
) -> dict[str, object]:
    """
    Create a new case package under calibration2 using built-in templates.

    Workflow performed by this function
    -----------------------------------
    1) Validate/canonicalize case name.
    2) Resolve source templates.
    3) Create destination folder (and `outputs/` subfolder).
    4) Render each `*.tmpl` file by replacing placeholders.
    5) Write final case files and return a summary report.

    Parameters
    ----------
    case_name : str
        Canonical case key (snake_case), for example ``my_new_case``.
    destination : str | Path | None
        Target case directory. Defaults to
        ``hydromodpy/calibration2/cases/<case_name>``.
    overwrite : bool
        When ``True``, existing files may be overwritten.

    Returns
    -------
    dict
        Summary payload:
        - `case_name`: normalized case key.
        - `case_class`: generated class name used in template.
        - `case_dir`: absolute destination directory.
        - `written_files`: tuple of files created.
    """
    # Normalize naming once so both paths and generated symbols are consistent.
    normalized_name = _normalize_case_name(case_name)
    case_class = _to_case_class_name(normalized_name)
    case_title = normalized_name.replace("_", " ").title()

    # Validate template availability early for actionable error messages.
    templates_dir = _templates_root()
    missing_templates = [name for name in _TEMPLATE_FILES if not (templates_dir / name).exists()]
    if missing_templates:
        raise FileNotFoundError(
            "Missing devkit templates: " + ", ".join(missing_templates)
        )

    if destination is None:
        case_dir = _calibration2_root() / "cases" / normalized_name
    else:
        case_dir = Path(destination)

    if case_dir.exists() and not overwrite:
        raise FileExistsError(
            f"Target case directory already exists: {case_dir}. "
            "Use overwrite=True to allow replacing files."
        )

    # Keep one dedicated output folder in every generated case to match
    # existing case conventions (saved figures, local artifacts).
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "outputs").mkdir(parents=True, exist_ok=True)

    # Render each template to its final filename by dropping `.tmpl`.
    written_files: list[str] = []
    for template_name in _TEMPLATE_FILES:
        source = templates_dir / template_name
        target_name = template_name.removesuffix(".tmpl")
        target = case_dir / target_name

        if target.exists() and not overwrite:
            raise FileExistsError(
                f"Target file already exists: {target}. "
                "Use overwrite=True to allow replacing files."
            )

        template_text = source.read_text(encoding="utf-8")
        rendered = _render_template(
            template_text,
            case_name=normalized_name,
            case_title=case_title,
            case_class=case_class,
        )
        target.write_text(rendered, encoding="utf-8")
        written_files.append(str(target))

    return {
        "case_name": normalized_name,
        "case_class": case_class,
        "case_dir": str(case_dir),
        "written_files": tuple(written_files),
    }


__all__ = (
    "scaffold_case",
)
