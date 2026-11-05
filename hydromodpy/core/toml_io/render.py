"""Value formatting, field defaults and comment lines of the TOML template.

Everything the section walker needs to turn one field, or one free-form
mapping, into text: TOML literals, the # Type: ... | Default: ... comment,
the placeholder of a required key, and what a field declares by itself.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from hydromodpy.core.config_kit.introspect import is_union_origin
from hydromodpy.core.config_kit.profile import Profile

_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_BASIC_STRING_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\b": "\\b",
    "\f": "\\f",
}


def _quote(text: str) -> str:
    """Return *text* as a TOML basic string.

    A quote, a backslash or a newline written raw ends the string early or is
    read as an escape that is not one. A Windows path and a multi-line field
    description both reach here.
    """
    escaped = "".join(_BASIC_STRING_ESCAPES.get(char, char) for char in text)
    return f'"{escaped}"'


def fmt_key(key: Any) -> str:
    """Format a mapping key as a TOML key.

    A key carrying anything but letters, digits, ``_`` and ``-`` is quoted:
    ``simulation.time.step_unit`` left bare is a dotted path into three nested
    tables, not the one key a calibration override means.
    """
    text = str(key)
    return text if _BARE_KEY_RE.match(text) else _quote(text)


def fmt(val: Any) -> str:
    """Format a Python value as a TOML literal."""
    if val is None:
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, Enum):
        return fmt(val.value)
    if isinstance(val, Path):
        return _quote(str(val))
    if hasattr(val, "magnitude") and hasattr(val, "units"):
        return _quote(f"{val.magnitude} {val.units:~}")
    if isinstance(val, str):
        return _quote(val)
    if hasattr(val, "isoformat"):
        return _quote(val.isoformat())
    if isinstance(val, (list, tuple)):
        inner = ", ".join(fmt(item) for item in val)
        return f"[{inner}]"
    if isinstance(val, dict):
        # An inline table, because the only caller left is a value inside an
        # array-of-tables entry, where a sub-table header would belong to the
        # entry rather than to the key. Python's own repr is not TOML.
        # A None drops out: TOML has no null, and an absent key reloads as the
        # None the field already defaults to.
        inner = ", ".join(
            f"{fmt_key(key)} = {fmt(item)}" for key, item in val.items() if item is not None
        )
        return "{" + inner + "}"
    return str(val)


def render_mapping_value(
    section_name: str,
    values: dict[str, Any],
    *,
    _commented: bool = False,
) -> list[str]:
    """Render a free-form TOML mapping as nested tables."""
    lines: list[str] = []
    scalar_items: list[tuple[str, Any]] = []
    nested_items: list[tuple[str, dict[str, Any]]] = []
    array_items: list[tuple[str, list[dict[str, Any]]]] = []

    for raw_key, raw_value in values.items():
        key = str(raw_key)
        if isinstance(raw_value, BaseModel):
            nested_items.append((key, raw_value.model_dump(exclude_none=True)))
        elif isinstance(raw_value, dict):
            nested_items.append((key, raw_value))
        elif (
            isinstance(raw_value, list)
            and raw_value
            and all(isinstance(item, dict) for item in raw_value)
        ):
            array_items.append((key, raw_value))
        else:
            scalar_items.append((key, raw_value))

    def _line(text: str) -> str:
        return f"# {text}" if _commented else text

    if scalar_items:
        lines.append("")
        lines.append(_line(f"[{section_name}]"))
        for key, value in scalar_items:
            if value is None:
                # A None scalar has no TOML literal; comment it out rather
                # than emit ``key =`` (which is invalid TOML). Reload restores
                # None as the optional-field default.
                lines.append(_line(f"# {key} ="))
            else:
                lines.append(_line(f"{key} = {fmt(value)}"))

    for key, nested in nested_items:
        lines.extend(
            render_mapping_value(
                f"{section_name}.{key}",
                nested,
                _commented=_commented,
            )
        )

    for key, items in array_items:
        sub_section = f"{section_name}.{key}"
        for item in items:
            lines.append("")
            lines.append(_line(f"[[{sub_section}]]"))
            for item_key, item_value in item.items():
                if isinstance(item_value, dict):
                    lines.extend(
                        render_mapping_value(
                            f"{sub_section}.{item_key}",
                            item_value,
                            _commented=_commented,
                        )
                    )
                elif item_value is None:
                    lines.append(_line(f"# {item_key} ="))
                else:
                    lines.append(_line(f"{item_key} = {fmt(item_value)}"))
    return lines


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
        if isinstance(meta, Profile):
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


UNDEFINED = object()  # sentinel distinct from None


def default_value(field_info: FieldInfo) -> Any:
    """Return the field default, or UNDEFINED if the field is truly required."""
    if field_info.default is PydanticUndefined:
        return UNDEFINED
    return field_info.default  # may be None (optional with no value)


def _declared_default(field_info: FieldInfo) -> Any:
    """Return the value a field holds on its own, running a ``default_factory``.

    ``default_value`` reports ``UNDEFINED`` for a factory field, because
    ``FieldInfo.default`` is unset there. A factory still gives the model a
    value without the reader writing one, so a caller asking what the model
    declares by itself needs that value, not the required sentinel.
    Returns ``UNDEFINED`` for a field that really is required, and for a
    factory that reads sibling values and so has no standalone answer.
    """
    factory = field_info.default_factory
    if factory is None:
        return default_value(field_info)
    if getattr(field_info, "default_factory_takes_validated_data", False):
        return UNDEFINED
    try:
        return factory()
    except Exception:  # pragma: no cover - a factory needing context is required
        return UNDEFINED


def factory_value(field_info: FieldInfo) -> Any:
    """Return what a ``default_factory`` gives on its own, ``None`` for any other field."""
    if field_info.default_factory is None:
        return None
    declared = _declared_default(field_info)
    return None if declared is UNDEFINED else declared


def is_disabled(model_cls: type[BaseModel], values: dict | None) -> bool:
    """Return True when the section has an ``enabled`` switch that is off."""
    field_info = model_cls.model_fields.get("enabled")
    if field_info is None:
        return False
    if values is not None and values.get("enabled") is not None:
        return values["enabled"] is False
    return default_value(field_info) is False


def declares_nothing(field_info: FieldInfo) -> bool:
    """Return True when the model leaves this repeated table empty by itself."""
    declared = _declared_default(field_info)
    if declared is UNDEFINED:
        return False
    return declared is None or (isinstance(declared, (list, tuple)) and not declared)


def toml_excluded(field_info: FieldInfo) -> bool:
    extra = field_info.json_schema_extra
    return bool(
        getattr(field_info, "exclude", False)
        or (isinstance(extra, dict) and extra.get("toml_exclude") is True)
    )


def placeholder(field_info: FieldInfo) -> str:
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
    if is_union_origin(origin):
        args = get_args(annotation)
        # A union always holds a member other than ``None``: ``None | None`` is ``None``.
        inner = next(a for a in args if a is not type(None))
        # Literal inside Optional
        if get_origin(inner) is not None:
            inner_args = get_args(inner)
            if inner_args and all(isinstance(a, (str, int, float)) for a in inner_args):
                return fmt(inner_args[0])
    elif origin is not None:
        # A Literal, or any other parameterized type (list, dict, ...)
        args = get_args(annotation)
        if args and all(isinstance(a, (str, int, float)) for a in args):
            return fmt(args[0])

    # Container types (list, dict, including parameterized forms)
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


def render_field_comment(
    lines: list[str],
    field_info: FieldInfo,
) -> None:
    """Append description + meta comment lines for a single field."""
    desc = field_info.description or ""
    if desc:
        append_comment_text(lines, desc)

    meta_parts = [f"Type: {_type_label(field_info)}"]
    meta_parts.extend(_constraints_from_field(field_info))

    default = default_value(field_info)
    from_factory = factory_value(field_info)
    if default is UNDEFINED and from_factory is not None:
        meta_parts.append(f"Default: {fmt(from_factory)}")
    elif default is UNDEFINED:
        meta_parts.append("REQUIRED")
    elif default is None:
        meta_parts.append("Optional")
    else:
        meta_parts.append(f"Default: {fmt(default)}")
    examples = getattr(field_info, "examples", None) or []
    if examples:
        rendered = ", ".join(fmt(item) for item in examples[:3])
        meta_parts.append(f"Examples: {rendered}")

    lines.append(f"# {' | '.join(meta_parts)}")


def append_comment_text(lines: list[str], text: str) -> None:
    """Append text as TOML comment lines."""
    for raw_line in text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            lines.append("#")
            continue
        for desc_line in raw_line.split(". "):
            desc_line = desc_line.strip()
            if desc_line:
                if not desc_line.endswith("."):
                    desc_line += "."
                lines.append(f"# {desc_line}")
