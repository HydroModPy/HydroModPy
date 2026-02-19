"""Auto-generate commented TOML templates from Pydantic models.

Reads field names, types, defaults, descriptions, and ParamLevel metadata
directly from Pydantic model_fields. Supports filtering by module and profile.

Usage::

    from hydromodpy.config.generate_toml import generate_toml
    print(generate_toml(modules=["geographic"], profile="user"))
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from hydromodpy.watershed.geographic_config import ParamLevel


PROFILES = {"user": 0, "dev": 1, "expert": 2}

# Registry of available config modules.
# Each entry maps a TOML section name to its Pydantic model class.
_MODULE_REGISTRY: dict[str, type[BaseModel]] | None = None


def _get_registry() -> dict[str, type[BaseModel]]:
    """Lazy-load the module registry to avoid circular imports."""
    global _MODULE_REGISTRY
    if _MODULE_REGISTRY is None:
        from hydromodpy.watershed.geographic_config import GeographicConfig
        _MODULE_REGISTRY = {
            "geographic": GeographicConfig,
        }
    return _MODULE_REGISTRY


def available_modules() -> list[str]:
    """Return the list of registered config module names."""
    return list(_get_registry().keys())


def generate_toml(
    output_path: str | Path | None = None,
    modules: list[str] | None = None,
    profile: str = "expert",
) -> str:
    """Generate a commented TOML template filtered by modules and profile.

    Parameters
    ----------
    output_path : str, Path, or None
        If provided, write the template to this file.
    modules : list of str, or None
        Module sections to include (e.g. ["geographic", "modflow"]).
        None = all registered modules.
    profile : str
        Visibility profile: "user", "dev", or "expert".
        Only fields with ParamLevel <= profile are included.

    Returns
    -------
    str
        The TOML content.
    """
    if profile not in PROFILES:
        raise ValueError(f"Unknown profile '{profile}'. Choose from: {', '.join(PROFILES)}")

    registry = _get_registry()

    if modules is None:
        selected = registry
    else:
        unknown = set(modules) - set(registry)
        if unknown:
            raise ValueError(
                f"Unknown module(s): {', '.join(sorted(unknown))}. "
                f"Available: {', '.join(sorted(registry))}"
            )
        selected = {k: registry[k] for k in modules}

    threshold = PROFILES[profile]

    lines = _header(profile, list(selected.keys()))

    for section_name, model_cls in selected.items():
        lines.extend(_section(section_name, model_cls, threshold))

    content = "\n".join(lines) + "\n"
    if output_path:
        Path(output_path).write_text(content, encoding="utf-8")
    return content


# =====================================================================
# Internal helpers
# =====================================================================

def _get_param_level(field_info: FieldInfo) -> str:
    """Extract ParamLevel from Annotated metadata, default to 'user'."""
    for meta in field_info.metadata:
        if isinstance(meta, ParamLevel):
            return meta.level
    return "user"


def _fmt(val: Any) -> str:
    """Format a Python value as a TOML literal."""
    if val is None:
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, str):
        return f'"{val}"'
    return str(val)


def _type_label(field_info: FieldInfo) -> str:
    """Human-readable type string from annotation."""
    annotation = field_info.annotation
    origin = get_origin(annotation)

    if origin is not None:
        args = get_args(annotation)
        if args:
            inner = ", ".join(repr(a) if isinstance(a, str) else getattr(a, "__name__", str(a)) for a in args)
            origin_name = getattr(origin, "__name__", str(origin))
            return f"{origin_name}[{inner}]"

    if hasattr(annotation, "__name__"):
        type_map = {"str": "string", "int": "int", "float": "float", "bool": "bool"}
        return type_map.get(annotation.__name__, annotation.__name__)

    return str(annotation)


def _constraints_from_field(field_info: FieldInfo) -> list[str]:
    """Extract constraint strings from FieldInfo metadata."""
    parts = []
    for meta in field_info.metadata:
        if isinstance(meta, ParamLevel):
            continue
        # Pydantic annotated constraints (Gt, Ge, Lt, Le)
        cls_name = type(meta).__name__
        if cls_name == "Gt":
            parts.append(f"> {meta.gt}")
        elif cls_name == "Ge":
            parts.append(f">= {meta.ge}")
        elif cls_name == "Lt":
            parts.append(f"< {meta.lt}")
        elif cls_name == "Le":
            parts.append(f"<= {meta.le}")
    # Enum values from Literal
    annotation = field_info.annotation
    origin = get_origin(annotation)
    if origin is not None:
        args = get_args(annotation)
        if all(isinstance(a, str) for a in args):
            opts = ", ".join(f'"{a}"' for a in args)
            parts.append(f"one of: {opts}")
    return parts


_UNDEFINED = object()  # sentinel distinct from None


def _default_value(field_info: FieldInfo) -> Any:
    """Return the field default, or _UNDEFINED if the field is truly required."""
    from pydantic_core import PydanticUndefined
    if field_info.default is PydanticUndefined:
        return _UNDEFINED
    return field_info.default  # may be None (optional with no value)


def _header(profile: str, modules: list[str]) -> list[str]:
    return [
        "# " + "=" * 70,
        "# HydroModPy Configuration",
        f"# Profile: {profile} | Modules: {', '.join(modules)}",
        "# Auto-generated from Pydantic models.",
        "# Edit values below. Comments describe each parameter.",
        "# " + "=" * 70,
        "",
    ]


def _section(section_name: str, model_cls: type[BaseModel], threshold: int) -> list[str]:
    """Generate a [section] with filtered fields."""
    lines = []
    title = model_cls.__doc__ or section_name
    title = title.strip().split("\n")[0]

    lines.append("")
    lines.append("# " + "-" * 70)
    lines.append(f"# {title}")
    lines.append("# " + "-" * 70)
    lines.append("")
    lines.append(f"[{section_name}]")

    has_fields = False
    for name, field_info in model_cls.model_fields.items():
        level = _get_param_level(field_info)
        if PROFILES.get(level, 0) > threshold:
            continue

        has_fields = True

        # Description
        desc = field_info.description or ""
        if desc:
            for desc_line in desc.split(". "):
                desc_line = desc_line.strip()
                if desc_line:
                    if not desc_line.endswith("."):
                        desc_line += "."
                    lines.append(f"# {desc_line}")

        # Meta line: type, constraints, default
        meta_parts = [f"Type: {_type_label(field_info)}"]
        meta_parts.extend(_constraints_from_field(field_info))

        default = _default_value(field_info)
        if default is _UNDEFINED:
            meta_parts.append("REQUIRED")
        elif default is None:
            meta_parts.append("Optional")
        else:
            meta_parts.append(f"Default: {_fmt(default)}")

        lines.append(f"# {' | '.join(meta_parts)}")

        # Value line
        if default is _UNDEFINED:
            # Truly required: uncommented placeholder
            lines.append(f"# {name} =")
        elif default is None:
            # Optional with no default: commented out
            lines.append(f"# {name} =")
        else:
            # Has a real default value: write it directly
            lines.append(f"{name} = {_fmt(default)}")

        lines.append("")

    if not has_fields:
        lines.append("# (no parameters at this profile level)")
        lines.append("")

    return lines
