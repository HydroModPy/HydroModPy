"""Auto-generate commented TOML templates from Pydantic models.

Reads field names, types, defaults, descriptions, and Profile metadata
directly from Pydantic model_fields. Supports filtering by module and profile.

Supports ``list[BaseModel]`` fields, rendered as TOML array-of-tables
(``[[section.field]]``).

Usage::

    from hydromodpy.core.config.generate_toml import generate_toml

    print(generate_toml(modules=["geographic"], profile="user"))

    from hydromodpy.core.config.generate_toml import generate_toml_from_instances

    generate_toml_from_instances(
        {"hydrometry": cfg_h, "piezometry": cfg_p},
        output_path="config.toml",
    )
"""

from __future__ import annotations

import os
import types as _stdlib_types
import typing
from enum import Enum
from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from hydromodpy.core.config.param_level import (
    PROFILES,  # noqa: F401 — re-exported for CLI back-compat
    ParamLevel,
)
from hydromodpy.core.config.profile import Profile
from hydromodpy.core.config.pydantic_introspect import extract_profile, resolve_profile

# Registry of available config modules.
# Each entry maps a TOML section name to its Pydantic model class.
_MODULE_REGISTRY: dict[str, type[BaseModel]] | None = None


def _get_registry() -> dict[str, type[BaseModel]]:
    """Lazy-load the module registry to avoid circular imports."""
    global _MODULE_REGISTRY
    if _MODULE_REGISTRY is None:
        from hydromodpy.core.workspace.config import WorkspaceConfig
        from hydromodpy.data.data_managers_config import DataManagersConfig
        from hydromodpy.display.config import DisplayConfig
        from hydromodpy.physics.flow.flow_config import FlowConfig
        from hydromodpy.physics.transport.transport_config import TransportConfig
        from hydromodpy.results.postprocess_config import PostprocessConfig
        from hydromodpy.simulation.planning.config import SimulationConfig
        from hydromodpy.solver.base.solver_config import SolverConfig
        from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
        from hydromodpy.solver.modflow_nwt.modflow import ModflowConfig
        from hydromodpy.spatial.domain.domain_config import DomainConfig
        from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
        from hydromodpy.spatial.mesh.config import MeshCatchmentConfig
        from hydromodpy.workflow.pipelines.overview_config import OverviewSection

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
            # ``mesh_catchment`` is optional at the aggregator level and its
            # inner schema pulls in additional required sections (geology,
            # rivers) as soon as it is emitted. It is only used for the
            # mesh-only workflow, so we leave it out of the default template;
            # users can request it explicitly via ``--modules mesh_catchment``.
            "mesh_catchment": MeshCatchmentConfig,
            "overview": OverviewSection,
            "simulation": SimulationConfig,
            "display": DisplayConfig,
            "postprocess": PostprocessConfig,
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
        Only fields with Profile <= profile are included.
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
    threshold = resolve_profile(profile)

    registry = _get_registry()

    if modules is None:
        # Default auto-selection: drop opt-in workflow-only sections that are
        # Optional at the aggregator level and would require more targeted
        # inputs to validate out-of-the-box (e.g. mesh-only workflow).
        _OPT_IN = {"mesh_catchment"}
        selected = {k: v for k, v in registry.items() if k not in _OPT_IN}
    else:
        unknown = set(modules) - set(registry)
        if unknown:
            raise ValueError(
                f"Unknown module(s): {', '.join(sorted(unknown))}. "
                f"Available: {', '.join(sorted(registry))}"
            )
        selected = {k: registry[k] for k in modules}

    lines = _header(profile, list(selected.keys()))

    for section_name, model_cls in selected.items():
        section_values = (overrides or {}).get(section_name)
        lines.extend(_section(section_name, model_cls, threshold, values=section_values))
        if section_name == "flow":
            lines.extend(_flow_dynamic_examples(threshold))

    content = "\n".join(lines) + "\n"
    if output_path:
        Path(output_path).write_text(content, encoding="utf-8")
    return content


def generate_toml_from_instances(
    instances: dict[str, BaseModel],
    output_path: str | Path | None = None,
    profile: str = "user",
    *,
    exclude_defaults: bool = False,
    exclude_none: bool = False,
    comment: str | None = None,
) -> str:
    """Generate a fully-filled TOML from instantiated Pydantic models.

    Works with **any** Pydantic model -- not limited to registered modules.
    Supports ``list[BaseModel]`` fields (rendered as ``[[section.sources]]``).

    When *output_path* is given, ``Path`` values are automatically
    relativised to the output directory.

    Parameters
    ----------
    instances : dict of {section_name: model_instance}
        E.g. ``{"hydrometry": cfg_h, "piezometry": cfg_p}``.
    output_path : str, Path, or None
        If provided, write the result to this file.
    profile : str
        Visibility profile controlling which fields are included.
    exclude_defaults : bool
        Omit fields that equal their default value (cleaner output).
    exclude_none : bool
        Omit fields whose value is ``None``.
    comment : str or None
        Optional header comment (may be multi-line).

    Returns
    -------
    str
        The TOML content.

    Example
    -------
    ::

        from hydromodpy.core.config.generate_toml import generate_toml_from_instances

        generate_toml_from_instances(
            {"hydrometry": cfg_h, "piezometry": cfg_p},
            output_path="config.toml",
            exclude_defaults=True,
            exclude_none=True,
            comment="My project config",
        )
    """
    threshold = resolve_profile(profile)
    toml_dir = Path(output_path).resolve().parent if output_path else None

    lines: list[str] = []
    if comment:
        lines.append("# " + "=" * 70)
        for cline in comment.split("\n"):
            lines.append(f"# {cline}")
        lines.append("# " + "=" * 70)
        lines.append("# Generated from Pydantic config export.")
        lines.append("")
    else:
        lines.extend(_header(profile, list(instances.keys())))

    for section_name, model in instances.items():
        values = model.model_dump(
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
        )
        if toml_dir:
            _relativize_paths_in_dict(values, toml_dir)
        lines.extend(_section(section_name, type(model), threshold, values=values))

    content = "\n".join(lines) + "\n"
    if output_path:
        Path(output_path).write_text(content, encoding="utf-8")
    return content


# =====================================================================
# Internal helpers
# =====================================================================


def _get_param_level(field_info: FieldInfo) -> str:
    """Legacy helper — return the profile name as a string.

    Prefer :func:`hydromodpy.core.config.pydantic_introspect.extract_profile`
    which returns the :class:`Profile` enum directly. Kept here because some
    external tooling (notebook snippets, docs) still imports this name.
    """
    return extract_profile(field_info).name.lower()


def _fmt(val: Any) -> str:
    """Format a Python value as a TOML literal."""
    if val is None:
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, Enum):
        return _fmt(val.value)
    if isinstance(val, Path):
        return f'"{val}"'
    if isinstance(val, str):
        return f'"{val}"'
    if isinstance(val, (list, tuple)):
        inner = ", ".join(_fmt(item) for item in val)
        return f"[{inner}]"
    return str(val)


_FRIENDLY_TYPES = {
    "str": "string",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "Path": "path",
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
                repr(a) if isinstance(a, str) else getattr(a, "__name__", str(a)) for a in args
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
        if isinstance(meta, (Profile, ParamLevel)):
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
        opts = ", ".join(f'"{e.value}"' for e in annotation)
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
        # Non-union parameterised type (list, dict, etc.) -- check for Literal
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


def _resolve_list_basemodel_type(field_info: FieldInfo) -> type[BaseModel] | None:
    """If field is ``list[SomeBaseModel]``, return the item class, else None."""
    origin = get_origin(field_info.annotation)
    if origin is not list:
        return None
    args = get_args(field_info.annotation)
    if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
        return args[0]
    return None


def _relativize_paths_in_dict(d: dict, toml_dir: Path) -> None:
    """In-place: convert absolute Path/str paths to relative strings."""
    for key, val in d.items():
        if isinstance(val, Path):
            d[key] = os.path.relpath(str(val), str(toml_dir))
        elif isinstance(val, str) and os.path.isabs(val):
            d[key] = os.path.relpath(val, str(toml_dir))
        elif isinstance(val, dict):
            _relativize_paths_in_dict(val, toml_dir)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    _relativize_paths_in_dict(item, toml_dir)


def _resolve_basemodel_type(field_info: FieldInfo) -> type[BaseModel] | None:
    """Return the concrete BaseModel subclass if the field holds one, else None.

    Container fields (``list[M]``, ``dict[str, M]``) are **not** considered
    nested model fields -- only direct ``M`` or ``Optional[M]`` / ``Union[M, N]``.
    """
    annotation = field_info.annotation

    # Direct BaseModel subclass
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation

    origin = get_origin(annotation)
    if origin is None:
        return None

    # Skip container types (list, dict, set, tuple, ...)
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


# --------------------------------------------------------------------------
# Dynamic flow examples (parameters / BC / sinks-sources)
# --------------------------------------------------------------------------

_FLOW_PARAM_EXAMPLES = (
    ("K", "homogeneous", "m/s"),
    ("Sy", "homogeneous", "-"),
    ("Ss", "homogeneous", "m-1"),
)


def _flow_dynamic_examples(threshold: int) -> list[str]:
    """Emit commented template blocks for the dynamic [flow.param.<id>.*],
    [flow.bc.<type>.<id>] and [flow.sinks_sources.recharge] payloads.

    These sections are driven by runtime user choices (the ``param_list``
    and ``active_bc`` declarations in [flow]), so the main generator cannot
    know their names in advance. We therefore emit documented examples for
    the canonical MODFLOW triplet K / Sy / Ss, the Cauchy drainage BC, and
    a recharge sinks-sources block.
    """
    from hydromodpy.physics.flow.boundary_conditions import (
        FlowBoundaryConditionConfig,
    )
    from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig
    from hydromodpy.spatial.field.core.field_param_config import (
        FieldBaseSection,
        FieldHomogeneousSection,
    )

    out: list[str] = []
    out.append("")
    out.append("# " + "-" * 70)
    out.append("# Flow field parameters — one [flow.param.<id>.field] + one")
    out.append("# [flow.param.<id>.field_homogeneous] per id declared in")
    out.append("# [flow].param_list. Example block below for K, Sy, Ss.")
    out.append("# " + "-" * 70)
    for pid, kind, unit in _FLOW_PARAM_EXAMPLES:
        out.extend(
            _section(
                f"flow.param.{pid}.field",
                FieldBaseSection,
                threshold,
                values={"id": pid, "kind": kind, "unit": unit},
                _depth=0,
            )
        )
        out.extend(
            _section(
                f"flow.param.{pid}.field_homogeneous",
                FieldHomogeneousSection,
                threshold,
                _depth=0,
            )
        )

    out.append("")
    out.append("# " + "-" * 70)
    out.append("# Flow boundary conditions — one block per id listed in")
    out.append("# [flow].active_bc. Supported keys: [flow.bc.dirichlet.<side>],")
    out.append("# [flow.bc.cauchy.drainage], [flow.bc.robin.drainage].")
    out.append("# Example: a top-domain Cauchy drainage BC.")
    out.append("# " + "-" * 70)
    out.extend(
        _section(
            "flow.bc.cauchy.drainage",
            FlowBoundaryConditionConfig,
            threshold,
            values={"application_domain": "top", "type": "cauchy", "unit": "m2/s"},
            _depth=0,
        )
    )

    out.append("")
    out.append("# " + "-" * 70)
    out.append("# Flow diffuse recharge — emitted when 'recharge' is listed in")
    out.append("# [flow].active_sinks_sources. Values are taken from the data")
    out.append("# layer ([data.recharge]) unless overridden here.")
    out.append("# " + "-" * 70)
    out.extend(
        _section(
            "flow.sinks_sources.recharge",
            FlowRechargeConfig,
            threshold,
            _depth=0,
        )
    )

    return out


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
    _commented: bool = False,
) -> list[str]:
    """Generate a [section] with filtered fields.

    Parameters
    ----------
    values : dict or None
        When provided, these values override defaults for the value line.
        A ``None`` entry means the field is left commented out.
    _depth : int
        Recursion depth (0 = top-level section header with banner).
    _commented : bool
        When True, all output (headers and values) are prefixed with ``# ``.
        Used for Optional sub-tables with no override values.
    """
    lines: list[str] = []

    # ----- flatten single-field containers --------------------------------
    # When a model has ``toml_flatten = True`` (ClassVar), skip one nesting
    # level: output the inner model's fields directly at *section_name* so
    # that e.g. ``FlowInitialConditions.h`` renders as ``[flow.ic]`` instead
    # of ``[flow.ic.h]``.
    if getattr(model_cls, "toml_flatten", False):
        for _name, _finfo in model_cls.model_fields.items():
            inner_cls = _resolve_basemodel_type(_finfo)
            if inner_cls is not None:
                inner_values = None
                if values is not None and _name in values:
                    raw = values[_name]
                    inner_values = (
                        raw
                        if isinstance(raw, dict)
                        else (raw.model_dump() if isinstance(raw, BaseModel) else None)
                    )
                return _section(
                    section_name,
                    inner_cls,
                    threshold,
                    values=inner_values,
                    _depth=_depth,
                    _commented=_commented,
                )

    # ----- classify fields ------------------------------------------------
    scalar_fields: list[tuple[str, FieldInfo, Profile]] = []  # (name, info, level)
    nested_fields: list[tuple[str, FieldInfo, Profile, type[BaseModel]]] = []
    array_fields: list[tuple[str, FieldInfo, Profile, type[BaseModel]]] = []

    for name, field_info in model_cls.model_fields.items():
        # Skip fields explicitly excluded from serialisation (e.g. Transport)
        if getattr(field_info, "exclude", False):
            continue

        level = extract_profile(field_info)
        if level > threshold:
            continue

        # list[BaseModel] -> array of tables [[section.name]]
        list_cls = _resolve_list_basemodel_type(field_info)
        if list_cls is not None:
            array_fields.append((name, field_info, level, list_cls))
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

    has_content = scalar_fields or nested_fields or array_fields

    # Helper: optionally prefix a line with "# " when in commented mode
    def _line(text: str) -> str:
        return f"# {text}" if _commented else text

    # Emit [section_name] when there are scalar fields (or nothing at all)
    if scalar_fields:
        lines.append("")
        lines.append(_line(f"[{section_name}]"))

        for name, field_info, level in scalar_fields:
            _render_field_comment(lines, field_info)

            default = _default_value(field_info)

            # Value line -- prefer override value when provided
            if values is not None and name in values and values[name] is not None:
                lines.append(_line(f"{name} = {_fmt(values[name])}"))
            elif default is not _UNDEFINED and default is not None:
                lines.append(_line(f"{name} = {_fmt(default)}"))
            elif level == Profile.USER and default is _UNDEFINED:
                # User-level *required* field — emit an uncommented
                # placeholder so the user knows to fill it in.
                lines.append(_line(f"{name} = {_placeholder(field_info)}"))
            else:
                # Optional field with default=None, or non-user level field
                # without a concrete default: emit commented-out placeholder.
                lines.append(
                    f"# {name} = {_placeholder(field_info)}" if default is None else f"# {name} ="
                )

            lines.append("")

    elif not has_content:
        # No fields at all at this profile level
        lines.append("")
        lines.append(_line(f"[{section_name}]"))
        lines.append("# (no parameters at this profile level)")
        lines.append("")

    # ----- nested sub-tables ----------------------------------------------
    for name, field_info, _level, nested_cls in nested_fields:
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
        is_truly_optional = default is None and not has_factory

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
            # Optional with no override: expand commented out
            lines.extend(
                _section(
                    sub_section,
                    nested_cls,
                    threshold,
                    values=None,
                    _depth=_depth + 1,
                    _commented=True,
                )
            )
        else:
            # Has a default_factory or concrete override: expand recursively
            lines.extend(
                _section(
                    sub_section,
                    nested_cls,
                    threshold,
                    values=sub_values,
                    _depth=_depth + 1,
                    _commented=_commented,
                )
            )

    # ----- array-of-tables ([[section.name]]) --------------------------------
    for name, field_info, _level, item_cls in array_fields:
        sub_section = f"{section_name}.{name}"

        # Description comment
        desc = field_info.description or ""
        if desc:
            lines.append("")
            for desc_line in desc.split(". "):
                desc_line = desc_line.strip()
                if desc_line:
                    if not desc_line.endswith("."):
                        desc_line += "."
                    lines.append(f"# {desc_line}")

        items: list[dict] | None = None
        if values is not None and name in values:
            raw = values[name]
            if isinstance(raw, list):
                items = raw

        if items:
            for item_dict in items:
                lines.append(_line(f"[[{sub_section}]]"))
                for key, val in item_dict.items():
                    # Add field description from the item model class
                    if key in item_cls.model_fields:
                        _render_field_comment(lines, item_cls.model_fields[key])
                    lines.append(_line(f"{key} = {_fmt(val)}"))
                    lines.append("")
        else:
            # Template mode: show an example entry with defaults
            lines.append(_line(f"[[{sub_section}]]"))
            for fname, finfo in item_cls.model_fields.items():
                if getattr(finfo, "exclude", False):
                    continue
                flevel = extract_profile(finfo)
                if flevel > threshold:
                    continue
                _render_field_comment(lines, finfo)
                default = _default_value(finfo)
                if default is not _UNDEFINED and default is not None:
                    lines.append(_line(f"{fname} = {_fmt(default)}"))
                else:
                    lines.append(_line(f"{fname} = {_placeholder(finfo)}"))
                lines.append("")

    return lines
