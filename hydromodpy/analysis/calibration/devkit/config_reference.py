"""
Generate markdown documentation directly from calibration Pydantic schemas.

This module avoids hand-maintained config tables by introspecting schema
definitions in core and case modules. The output is meant for users editing
TOML files and for developers reviewing schema changes.

When to run it
--------------
- after changing Pydantic schemas in `core/engine_config.py`,
- after changing method kwargs schemas in `core/methods_config.py`,
- after updating case chronicle schemas.

Who launches it
---------------
- maintainers updating docs in pull requests,
- contributors wanting a quick "source of truth" for accepted config keys.

What it guarantees
------------------
- generated tables reflect current schema code (no stale manual copy),
- stable ordering of method sections (sorted iteration),
- explicit default/required field display.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic import BaseModel

from hydromodpy.analysis.calibration.core.engine_config import (
    CalibrationSectionSchema,
    CalibrationTomlSchema,
    ObjectiveSectionSchema,
    OutputSectionSchema,
)
from hydromodpy.analysis.calibration.core.methods_config import METHOD_KWARGS_MODELS
from hydromodpy.analysis.calibration.cases.recession_brutsaert.case_config import (
    BrutsaertChronicleSchema,
)
from hydromodpy.analysis.calibration.cases.reservoir.case_config import ReservoirChronicleSchema


def _calibration_root() -> Path:
    """Return absolute path to `hydromodpy/analysis/calibration/`."""
    return Path(__file__).resolve().parents[1]


def _type_label(annotation: Any) -> str:
    """
    Convert Python typing annotations to concise markdown-friendly labels.

    Examples:
    - `list[int]` -> `list[int]`
    - `dict[str, float]` -> `dict[str, float]`
    - `float | None` -> `float | None`
    """
    origin = get_origin(annotation)
    if origin is None:
        if hasattr(annotation, "__name__"):
            return str(annotation.__name__)
        return str(annotation).replace("typing.", "")

    args = get_args(annotation)
    if origin is list:
        return f"list[{_type_label(args[0])}]" if args else "list"
    if origin is tuple:
        return "tuple[" + ", ".join(_type_label(arg) for arg in args) + "]"
    if origin is dict:
        if len(args) == 2:
            return f"dict[{_type_label(args[0])}, {_type_label(args[1])}]"
        return "dict"
    if origin is set:
        return f"set[{_type_label(args[0])}]" if args else "set"
    if origin is type(None):
        return "None"

    origin_name = getattr(origin, "__name__", str(origin))
    if origin_name in ("UnionType", "Union"):
        return " | ".join(_type_label(arg) for arg in args)
    return str(annotation).replace("typing.", "")


def _default_label(field_info) -> str:
    """Return a compact textual representation of a Pydantic field default."""
    if field_info.is_required():
        return "required"
    if field_info.default_factory is not None:
        return "<factory>"
    value = field_info.default
    if value is None:
        return "None"
    return repr(value)


def _model_markdown_table(model_cls: type[BaseModel]) -> str:
    """Render one schema class as a 3-column markdown table."""
    lines = [
        "| Field | Type | Default |",
        "|---|---|---|",
    ]
    for field_name, field_info in model_cls.model_fields.items():
        field_type = _type_label(field_info.annotation)
        default = _default_label(field_info)
        lines.append(f"| `{field_name}` | `{field_type}` | `{default}` |")
    return "\n".join(lines)


def build_config_reference_markdown() -> str:
    """
    Build markdown documentation for calibration config schemas.

    Content includes:
    - shared calibration schema,
    - per-method kwargs schemas,
    - chronicle schemas for built-in cases.
    """
    # Build the page as ordered sections so generated output is deterministic.
    sections: list[str] = []
    sections.append("# Calibration Config Reference")
    sections.append("")
    sections.append(
        "This page is generated from Pydantic schemas used by calibration."
    )
    sections.append("")

    sections.append("## Core TOML Schema")
    sections.append("")
    sections.append("### `[calibration]`")
    sections.append("")
    sections.append(_model_markdown_table(CalibrationSectionSchema))
    sections.append("")

    sections.append("### Top-level sections")
    sections.append("")
    sections.append(_model_markdown_table(CalibrationTomlSchema))
    sections.append("")

    sections.append("### `[output]`")
    sections.append("")
    sections.append(_model_markdown_table(OutputSectionSchema))
    sections.append("")

    sections.append("### `[objective]`")
    sections.append("")
    sections.append(_model_markdown_table(ObjectiveSectionSchema))
    sections.append("")

    sections.append("## Built-in Method Kwargs")
    sections.append("")
    # One subsection per calibration method schema (sorted for stable output).
    for method_name in sorted(METHOD_KWARGS_MODELS):
        model_cls = METHOD_KWARGS_MODELS[method_name]
        sections.append(f"### `[calibration_method.{method_name}]`")
        sections.append("")
        sections.append(_model_markdown_table(model_cls))
        sections.append("")

    sections.append("## Case Chronicle Schemas")
    sections.append("")
    sections.append("### `cases/reservoir` chronicle")
    sections.append("")
    sections.append(_model_markdown_table(ReservoirChronicleSchema))
    sections.append("")
    sections.append("### `cases/recession_brutsaert` chronicle")
    sections.append("")
    sections.append(_model_markdown_table(BrutsaertChronicleSchema))
    sections.append("")

    sections.append("## Notes")
    sections.append("")
    sections.append(
        "- For `da_mh_gp`, per-parameter keys (`proposal_scale`, `prior_mean`, "
        "`prior_std`, `gp_length_scale`) accept either:"
    )
    sections.append("  - a scalar (same value for all parameters), or")
    sections.append("  - a mapping keyed by model parameter names.")
    sections.append(
        "- Unknown keys are rejected by all schemas (`extra=\"forbid\"`)."
    )

    return "\n".join(sections).strip() + "\n"


def write_config_reference_markdown(
    output_path: str | Path | None = None,
) -> Path:
    """
    Write generated config reference markdown and return target path.

    Parameters
    ----------
    output_path : str | Path | None
        Destination markdown file. Uses `analysis/calibration/docs/config_reference.md`
        when omitted.
    """
    # Keep default location close to other calibration docs.
    if output_path is None:
        output_path = _calibration_root() / "docs" / "config_reference.md"
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_config_reference_markdown(), encoding="utf-8")
    return target


__all__ = (
    "build_config_reference_markdown",
    "write_config_reference_markdown",
)

