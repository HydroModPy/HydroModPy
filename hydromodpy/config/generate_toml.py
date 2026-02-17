"""Auto-generate commented TOML templates from Pydantic models.

Reads field names, types, defaults, descriptions, and constraints
directly from the Pydantic JSON schema. Zero manual duplication:
add a Field to the model, the TOML template updates itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def generate_toml(output_path: str | Path | None = None) -> str:
    """Generate a fully commented TOML template from HydroModPyConfig.

    Every field gets:
    - Description (from Field(description=...))
    - Type, constraints (bounds, enums), default value

    Parameters
    ----------
    output_path : str, Path, or None
        If provided, write the template to this file.

    Returns
    -------
    str
        The TOML content.
    """
    from hydromodpy.config import HydroModPyConfig

    schema = HydroModPyConfig.model_json_schema()
    defs = schema.get("$defs", {})

    lines = _header()

    for name, prop in schema.get("properties", {}).items():
        resolved = _resolve(prop, defs)
        if resolved.get("type") == "object" and "properties" in resolved:
            lines.extend(_section(name, resolved, defs))

    content = "\n".join(lines) + "\n"
    if output_path:
        Path(output_path).write_text(content, encoding="utf-8")
    return content


# =====================================================================
# Internal helpers
# =====================================================================

def _resolve(schema: dict, defs: dict) -> dict:
    """Follow $ref to get the actual schema definition."""
    if "$ref" in schema:
        name = schema["$ref"].split("/")[-1]
        base = dict(defs.get(name, {}))
        # Overlay keys from the original (default, description overrides)
        for k, v in schema.items():
            if k != "$ref":
                base[k] = v
        return base
    return schema


def _fmt(val: Any) -> str:
    """Format a Python value as a TOML literal."""
    if val is None:
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, str):
        return f'"{val}"'
    return str(val)


def _type_label(schema: dict, defs: dict) -> str:
    """Human-readable type string."""
    if "$ref" in schema:
        r = _resolve(schema, defs)
        return r.get("title", "object")

    if "anyOf" in schema or "oneOf" in schema:
        variants = schema.get("anyOf") or schema.get("oneOf", [])
        parts = []
        nullable = False
        for s in variants:
            if s.get("type") == "null":
                nullable = True
            else:
                parts.append(_type_label(s, defs))
        label = " | ".join(parts) if parts else "any"
        if nullable:
            label += " or null"
        return label

    if "const" in schema:
        return f'"{schema["const"]}"'

    t = schema.get("type", "any")
    type_map = {
        "string": "string", "number": "float", "integer": "int",
        "boolean": "bool", "array": "list",
    }
    return type_map[t] if t in type_map else t


def _constraints(schema: dict) -> list[str]:
    """Extract constraint strings from JSON schema."""
    parts = []
    if "exclusiveMinimum" in schema:
        parts.append(f"> {schema['exclusiveMinimum']}")
    if "minimum" in schema:
        parts.append(f">= {schema['minimum']}")
    if "exclusiveMaximum" in schema:
        parts.append(f"< {schema['exclusiveMaximum']}")
    if "maximum" in schema:
        parts.append(f"<= {schema['maximum']}")
    if "enum" in schema:
        opts = ", ".join(f'"{v}"' for v in schema["enum"])
        parts.append(f"one of: {opts}")
    return parts


def _all_constraints(schema: dict) -> list[str]:
    """Constraints from both top-level and inside anyOf variants."""
    parts = _constraints(schema)
    for s in schema.get("anyOf", []):
        if s.get("type") != "null":
            parts.extend(_constraints(s))
    return parts


def _meta_line(name: str, schema: dict, defs: dict, required: list) -> str:
    """Build: 'Type: float | > 0 | Default: 8.64'"""
    parts = [f"Type: {_type_label(schema, defs)}"]
    parts.extend(_all_constraints(schema))

    if "default" in schema:
        d = schema["default"]
        if d is None:
            parts.append("Default: null")
        elif isinstance(d, bool):
            parts.append(f"Default: {'true' if d else 'false'}")
        elif isinstance(d, str):
            parts.append(f'Default: "{d}"')
        elif isinstance(d, (dict, list)):
            pass  # sub-object defaults are shown in their own section
        else:
            parts.append(f"Default: {d}")
    elif name in required:
        parts.append("REQUIRED")

    return " | ".join(parts)


def _default_value(schema: dict, defs: dict) -> Any:
    """Default value suitable for TOML, or placeholder for required fields."""
    if "default" in schema:
        d = schema["default"]
        if isinstance(d, (dict, list)):
            return None  # handled as sub-table
        return d
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    t = schema.get("type", "")
    if t == "number":
        return 0.0
    if t == "integer":
        return 0
    if t == "boolean":
        return False
    if t == "string":
        return ""
    return None


def _is_sub_object(schema: dict, defs: dict) -> bool:
    r = _resolve(schema, defs)
    return r.get("type") == "object" and "properties" in r


def _field_lines(name: str, schema: dict, defs: dict, required: list) -> list[str]:
    """Comment + value lines for a single scalar field."""
    lines = []

    desc = schema.get("description", "")
    if desc:
        lines.append(f"# {desc}")

    lines.append(f"# {_meta_line(name, schema, defs, required)}")

    val = _default_value(schema, defs)
    if val is None:
        lines.append(f"# {name} =")
    else:
        lines.append(f"{name} = {_fmt(val)}")

    return lines


# -- Structure builders -----------------------------------------------

def _header() -> list[str]:
    return [
        "# " + "=" * 70,
        "# HydroModPy Configuration",
        "# Auto-generated from Pydantic models.",
        "# Edit values below. Comments describe each parameter.",
        "# " + "=" * 70,
        "",
    ]


def _section(prefix: str, schema: dict, defs: dict) -> list[str]:
    """Generate [prefix] with fields, then sub-tables."""
    lines = []
    props = schema.get("properties", {})
    required = schema.get("required", [])
    desc = schema.get("description", schema.get("title", prefix))

    # Section header
    lines.append("")
    lines.append("# " + "-" * 70)
    lines.append(f"# {desc}")
    lines.append("# " + "-" * 70)
    lines.append("")
    lines.append(f"[{prefix}]")

    # Separate simple fields from sub-objects
    deferred = []

    for name, prop in props.items():
        # Discriminated union (oneOf with discriminator)
        if "discriminator" in prop:
            deferred.append((name, "union", prop))
            continue

        # Direct sub-object
        if _is_sub_object(prop, defs):
            deferred.append((name, "object", prop))
            continue

        # anyOf / oneOf
        if "anyOf" in prop or "oneOf" in prop:
            variants = prop.get("anyOf") or prop.get("oneOf", [])
            non_null = [s for s in variants if s.get("type") != "null"]

            # Optional[sub-object]
            if len(non_null) == 1 and _is_sub_object(non_null[0], defs):
                deferred.append((name, "optional_object", prop))
                continue

        # Array of objects
        if prop.get("type") == "array" and "items" in prop:
            items = _resolve(prop["items"], defs)
            if items.get("type") == "object" and "properties" in items:
                deferred.append((name, "array", prop))
                continue

        # Simple field
        lines.extend(_field_lines(name, prop, defs, required))
        lines.append("")

    # Sub-tables
    for name, kind, prop in deferred:
        sub_prefix = f"{prefix}.{name}"

        if kind == "union":
            lines.extend(_union_section(sub_prefix, prop, defs))

        elif kind == "object":
            resolved = _resolve(prop, defs)
            lines.extend(_section(sub_prefix, resolved, defs))

        elif kind == "optional_object":
            non_null = [s for s in prop["anyOf"] if s.get("type") != "null"]
            resolved = _resolve(non_null[0], defs)
            desc = prop.get("description", "")
            lines.append("")
            if desc:
                lines.append(f"# {desc}")
            lines.append(f"# Optional — uncomment to enable:")
            lines.append(f"# [{sub_prefix}]")
            for fname, fprop in resolved.get("properties", {}).items():
                val = _default_value(fprop, defs)
                lines.append(f"# {fname} = {_fmt(val)}")
            lines.append("")

        elif kind == "array":
            lines.extend(_array_section(sub_prefix, prop, defs))

    return lines


def _union_section(prefix: str, schema: dict, defs: dict) -> list[str]:
    """Discriminated union: first variant active, others commented."""
    lines = []
    variants = []
    for s in schema.get("oneOf") or schema.get("anyOf", []):
        if s.get("type") == "null":
            continue
        variants.append(_resolve(s, defs))

    if not variants:
        return lines

    desc = schema.get("description", "")
    if desc:
        lines.append("")
        lines.append(f"# {desc}")

    # First variant (active)
    first = variants[0]
    first_props = first.get("properties", {})
    first_required = first.get("required", [])
    first_desc = first.get("description", "")

    lines.append("")
    if first_desc:
        lines.append(f"# {first_desc}")
    lines.append(f"[{prefix}]")

    for fname, fprop in first_props.items():
        lines.extend(_field_lines(fname, fprop, defs, first_required))
        lines.append("")

    # Other variants (commented)
    for variant in variants[1:]:
        title = variant.get("title", "?")
        vdesc = variant.get("description", "")
        v_props = variant.get("properties", {})

        lines.append(f"# --- Alternative: {title} ---")
        if vdesc:
            lines.append(f"# {vdesc}")
        lines.append(f"# [{prefix}]")
        for fname, fprop in v_props.items():
            val = _default_value(fprop, defs)
            if val is None:
                lines.append(f"# {fname} =")
            else:
                lines.append(f"# {fname} = {_fmt(val)}")
        lines.append("")

    return lines


def _array_section(prefix: str, schema: dict, defs: dict) -> list[str]:
    """Commented example for an array of objects (e.g. [[modflow.wells]])."""
    lines = []
    items = _resolve(schema.get("items", {}), defs)
    item_props = items.get("properties", {})
    desc = schema.get("description", items.get("description", items.get("title", "")))

    lines.append("")
    if desc:
        lines.append(f"# {desc}")
    lines.append("# Type: list of tables | Default: []")
    lines.append(f"# Example (uncomment to add):")
    lines.append(f"# [[{prefix}]]")
    for fname, fprop in item_props.items():
        d = fprop.get("description", "")
        if d:
            lines.append(f"#   # {d}")
        val = _default_value(fprop, defs)
        if val is None:
            lines.append(f"#   {fname} = 0")
        else:
            lines.append(f"#   {fname} = {_fmt(val)}")
    lines.append("")

    return lines
