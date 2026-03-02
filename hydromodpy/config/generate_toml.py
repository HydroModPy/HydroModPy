"""Auto-generate commented TOML templates from Pydantic models.

Reads field names, types, defaults, descriptions, and ParamLevel metadata
directly from Pydantic model_fields. Supports filtering by module and profile.

Usage::

    from hydromodpy.config.generate_toml import generate_toml
    print(generate_toml(modules=["geographic"], profile="user"))
"""

from __future__ import annotations

import types as _stdlib_types
import typing
from enum import Enum
from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from hydromodpy.config.param_level import PROFILES, ParamLevel

# Registry of available config modules.
# Each entry maps a TOML section name to its Pydantic model class.
_MODULE_REGISTRY: dict[str, type[BaseModel]] | None = None


def _get_registry() -> dict[str, type[BaseModel]]:
    """Lazy-load the module registry to avoid circular imports."""
    global _MODULE_REGISTRY
    if _MODULE_REGISTRY is None:
        from hydromodpy.data_managers.data_managers_config import DataManagersConfig
        from hydromodpy.domain.domain_config import DomainConfig
        from hydromodpy.geographic.geographic_config import GeographicConfig
        from hydromodpy.process.flow.flow_config import FlowConfig
        from hydromodpy.process.transport.transport_config import TransportConfig
        from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
        from hydromodpy.solver.modflow_nwt.modflow import ModflowConfig
        from hydromodpy.solver.solver_config import SolverConfig
        from hydromodpy.watershed.workspace_config import WorkspaceConfig
        _MODULE_REGISTRY = {
            "workspace": WorkspaceConfig,
            "geographic": GeographicConfig,
            "domain": DomainConfig,
            "data": DataManagersConfig,
            "flow": FlowConfig,
            "transport": TransportConfig,
            "solver": SolverConfig,
            "modflownwt": ModflowConfig,
            "modflow6": Modflow6Config,
        }
    return _MODULE_REGISTRY


def available_modules() -> list[str]:
    """Return the list of registered config module names."""
    return list(_get_registry().keys())


def generate_toml(
    output_path: str | Path | None = None,
    modules: list[str] | None = None,
    profile: str = "expert",
    overrides: dict[str, dict] | None = None,
) -> str:
    """Generate a commented TOML template filtered by modules and profile.

    Parameters
    ----------
    output_path : str, Path, or None
        If provided, write the template to this file.
    modules : list of str, or None
        Module sections to include (e.g. ["geographic", "modflownwt"]).
        None = all registered modules.
    profile : str
        Visibility profile: "user", "dev", or "expert".
        Only fields with ParamLevel <= profile are included.
    overrides : dict of {section_name: {field_name: value}}, or None
        Concrete values to write instead of model defaults.
        Fields present in overrides with a non-None value are written
        uncommented; fields set to None follow the default commented-out
        behaviour for optional fields.

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
        section_values = (overrides or {}).get(section_name)
        lines.extend(_section(section_name, model_cls, threshold, values=section_values))

    content = "\n".join(lines) + "\n"
    if output_path:
        Path(output_path).write_text(content, encoding="utf-8")
    return content


def generate_toml_from_instances(
    instances: dict[str, "BaseModel"],
    output_path: str | Path | None = None,
    profile: str = "user",
) -> str:
    """Generate a fully-filled commented TOML from instantiated Pydantic models.

    Each model's actual field values are written into the TOML alongside the
    usual description and type comments.  Optional fields left as ``None`` are
    commented out (same as the template behaviour).

    Parameters
    ----------
    instances : dict of {section_name: model_instance}
        E.g. ``{"workspace": workspace_cfg, "geographic": geo_cfg}``.
    output_path : str, Path, or None
        If provided, write the result to this file.
    profile : str
        Visibility profile controlling which fields are included.

    Returns
    -------
    str
        The TOML content.

    Example
    -------
    ::

        from hydromodpy.config.generate_toml import generate_toml_from_instances
        content = generate_toml_from_instances(
            {"workspace": workspace_cfg, "geographic": geo_cfg},
            output_path="examples/01S_short/config.toml",
        )
    """
    overrides = {
        section: model.model_dump()
        for section, model in instances.items()
    }
    return generate_toml(
        output_path=output_path,
        modules=list(instances.keys()),
        profile=profile,
        overrides=overrides,
    )


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
    if isinstance(val, Enum):
        return _fmt(val.value)
    if isinstance(val, Path):
        return f'"{ val}"'
    if isinstance(val, str):
        return f'"{ val}"'
    if isinstance(val, (list, tuple)):
        inner = ", ".join(_fmt(item) for item in val)
        return f"[{inner}]"
    return str(val)


_FRIENDLY_TYPES = {
    "str": "string", "int": "int", "float": "float",
    "bool": "bool", "Path": "path",
}


def _type_label(field_info: FieldInfo) -> str:
    """Human-readable type string from annotation."""
    annotation = field_info.annotation
    origin = get_origin(annotation)

    if origin is not None:
        args = get_args(annotation)
        if args:
            non_none = [a for a in args if a is not type(None)]
            has_none = type(None) in args
            # Optional[X] -> "X (optional)" for common scalar/path types
            if len(non_none) == 1 and has_none:
                name = getattr(non_none[0], "__name__", str(non_none[0]))
                friendly = _FRIENDLY_TYPES.get(name, name)
                return f"{friendly} (optional)"
            inner = ", ".join(
                repr(a) if isinstance(a, str)
                else getattr(a, "__name__", str(a))
                for a in args
            )
            origin_name = getattr(origin, "__name__", str(origin))
            return f"{origin_name}[{inner}]"

    if hasattr(annotation, "__name__"):
        return _FRIENDLY_TYPES.get(annotation.__name__, annotation.__name__)

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
    # Enum values
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        opts = ", ".join(f'"{ e.value}"' for e in annotation)
        parts.append(f"one of: {opts}")
    return parts


_UNDEFINED = object()  # sentinel distinct from None


def _default_value(field_info: FieldInfo) -> Any:
    """Return the field default, or _UNDEFINED if the field is truly required."""
    from pydantic_core import PydanticUndefined
    if field_info.default is PydanticUndefined:
        return _UNDEFINED
    return field_info.default  # may be None (optional with no value)


def _is_union_origin(origin: Any) -> bool:
    """Return True if *origin* represents a Union type."""
    if origin is typing.Union:
        return True
    if hasattr(_stdlib_types, "UnionType") and origin is _stdlib_types.UnionType:
        return True
    return False


def _placeholder(field_info: FieldInfo) -> str:
    """Return a TOML-safe placeholder value for a field with no set default.

    For Literal types the first allowed value is used; for scalars a
    zero-equivalent is returned; everything else falls back to ``""``.

    Numeric constraints (``gt``, ``ge``) are respected so that the
    placeholder never violates the validation rule.
    """
    annotation = field_info.annotation
    origin = get_origin(annotation)

    # Unwrap Optional[X] / Union[X, None] to get the inner type
    inner = annotation
    if _is_union_origin(origin):
        args = get_args(annotation)
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            inner = non_none[0]
            inner_origin = get_origin(inner)
            # Literal inside Optional
            if inner_origin is not None:
                inner_args = get_args(inner)
                if inner_args and all(isinstance(a, (str, int, float)) for a in inner_args):
                    return _fmt(inner_args[0])
        else:
            # Bare Literal at top level
            if all(isinstance(a, (str, int, float)) for a in args):
                return _fmt(args[0])
    elif origin is not None:
        # Non-union parameterised type (list, dict, etc.) — check for Literal
        args = get_args(annotation)
        if args and all(isinstance(a, (str, int, float)) for a in args):
            return _fmt(args[0])

    # Bare Literal at top level (origin is typing.Literal)
    top_args = get_args(annotation)
    if top_args and all(isinstance(a, (str, int, float)) for a in top_args):
        return _fmt(top_args[0])

    # Container types (list, dict, including parameterised forms)
    inner_origin = get_origin(inner)
    inner_name = getattr(inner, "__name__", "")
    if inner_origin is list or inner is list or inner_name == "list":
        return "[]"
    if inner_origin is dict or inner is dict or inner_name == "dict":
        return "{}"

    # Extract numeric lower-bound constraints from metadata
    min_bound: float | None = None
    min_exclusive = False
    for meta in field_info.metadata:
        cls_name = type(meta).__name__
        if cls_name == "Gt":
            min_bound = meta.gt
            min_exclusive = True
        elif cls_name == "Ge":
            min_bound = meta.ge
            min_exclusive = False

    if inner_name == "str":
        return '""'
    if inner_name == "int":
        if min_bound is not None and min_exclusive:
            return str(int(min_bound) + 1)
        if min_bound is not None:
            return str(int(min_bound))
        return "0"
    if inner_name == "float":
        if min_bound is not None and min_exclusive:
            return str(float(min_bound) + 1.0)
        if min_bound is not None:
            return str(float(min_bound))
        return "0.0"
    if inner_name == "bool":
        return "false"
    return '""'


def _resolve_basemodel_type(field_info: FieldInfo) -> type[BaseModel] | None:
    """Return the concrete BaseModel subclass if the field holds one, else None.

    Container fields (``list[M]``, ``dict[str, M]``) are **not** considered
    nested model fields — only direct ``M`` or ``Optional[M]`` / ``Union[M, N]``.
    """
    annotation = field_info.annotation

    # Direct BaseModel subclass
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation

    origin = get_origin(annotation)
    if origin is None:
        return None

    # Skip container types (list, dict, set, tuple, …)
    if isinstance(origin, type) and issubclass(origin, (list, dict, set, tuple, frozenset)):
        return None

    # Handle Union types (typing.Union, types.UnionType)
    args = get_args(annotation)
    if not args:
        return None

    non_none = [a for a in args if a is not type(None)]
    base_models = [a for a in non_none if isinstance(a, type) and issubclass(a, BaseModel)]

    if not base_models:
        return None

    # Prefer the default_factory's concrete type for discriminated unions
    if field_info.default_factory is not None:
        try:
            instance = field_info.default_factory()
            if isinstance(instance, BaseModel):
                return type(instance)
        except Exception:
            pass
    if isinstance(field_info.default, BaseModel):
        return type(field_info.default)
    return base_models[0]


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


def _render_field_comment(
    lines: list[str],
    field_info: FieldInfo,
) -> None:
    """Append description + meta comment lines for a single field."""
    desc = field_info.description or ""
    if desc:
        for desc_line in desc.split(". "):
            desc_line = desc_line.strip()
            if desc_line:
                if not desc_line.endswith("."):
                    desc_line += "."
                lines.append(f"# {desc_line}")

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


def _section(
    section_name: str,
    model_cls: type[BaseModel],
    threshold: int,
    values: dict | None = None,
    _depth: int = 0,
) -> list[str]:
    """Generate a [section] with filtered fields.

    Parameters
    ----------
    values : dict or None
        When provided, these values override defaults for the value line.
        A ``None`` entry means the field is left commented out.
    _depth : int
        Recursion depth (0 = top-level section header with banner).
    """
    lines: list[str] = []

    # ----- classify fields ------------------------------------------------
    scalar_fields: list[tuple[str, FieldInfo, str]] = []   # (name, info, level)
    nested_fields: list[tuple[str, FieldInfo, str, type[BaseModel]]] = []

    for name, field_info in model_cls.model_fields.items():
        # Skip fields explicitly excluded from serialisation (e.g. Transport)
        if getattr(field_info, "exclude", False):
            continue

        level = _get_param_level(field_info)
        if PROFILES.get(level, 0) > threshold:
            continue

        nested_cls = _resolve_basemodel_type(field_info)
        if nested_cls is not None:
            nested_fields.append((name, field_info, level, nested_cls))
        else:
            scalar_fields.append((name, field_info, level))

    # ----- section header -------------------------------------------------
    if _depth == 0:
        title = (model_cls.__doc__ or section_name).strip().split("\n")[0]
        lines.append("")
        lines.append("# " + "-" * 70)
        lines.append(f"# {title}")
        lines.append("# " + "-" * 70)

    # Emit [section_name] when there are scalar fields (or nothing at all)
    if scalar_fields:
        lines.append("")
        lines.append(f"[{section_name}]")

        for name, field_info, level in scalar_fields:
            _render_field_comment(lines, field_info)

            default = _default_value(field_info)

            # Value line — prefer override value when provided
            if values is not None and name in values and values[name] is not None:
                lines.append(f"{name} = {_fmt(values[name])}")
            elif default is not _UNDEFINED and default is not None:
                lines.append(f"{name} = {_fmt(default)}")
            elif level == "user":
                lines.append(f"{name} = {_placeholder(field_info)}")
            else:
                lines.append(f"# {name} =")

            lines.append("")

    elif not nested_fields:
        # No fields at all at this profile level
        lines.append("")
        lines.append(f"[{section_name}]")
        lines.append("# (no parameters at this profile level)")
        lines.append("")

    # ----- nested sub-tables ----------------------------------------------
    for name, field_info, level, nested_cls in nested_fields:
        sub_section = f"{section_name}.{name}"

        # Resolve override values for the sub-section
        sub_values = None
        if values is not None and name in values:
            raw = values[name]
            if isinstance(raw, dict):
                sub_values = raw
            elif isinstance(raw, BaseModel):
                sub_values = raw.model_dump()

        default = _default_value(field_info)
        has_factory = field_info.default_factory is not None
        is_truly_optional = (default is None and not has_factory)

        # Description comment before the sub-table
        desc = field_info.description or ""
        if desc:
            lines.append("")
            for desc_line in desc.split(". "):
                desc_line = desc_line.strip()
                if desc_line:
                    if not desc_line.endswith("."):
                        desc_line += "."
                    lines.append(f"# {desc_line}")

        if is_truly_optional and sub_values is None:
            # Optional with no default and no override: comment out
            lines.append(f"# [{sub_section}]")
            lines.append("")
        else:
            # Has a default_factory or concrete override: expand recursively
            lines.extend(
                _section(
                    sub_section, nested_cls, threshold,
                    values=sub_values, _depth=_depth + 1,
                )
            )

    return lines
