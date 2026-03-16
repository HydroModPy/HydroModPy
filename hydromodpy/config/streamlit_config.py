"""Interactive TOML configuration editor — auto-generated from Pydantic models.

Launch with::

    streamlit run hydromodpy/config/streamlit_config.py [-- --load config.toml]

Or via the CLI::

    hmp config --ui

The interface is **entirely derived** from Pydantic model metadata (types,
defaults, descriptions, ParamLevel, VisibleWhen).  Adding or modifying a
field in a config model automatically updates the UI — no widget code to
maintain.

Features:
- Auto-generated widgets for every field type
- Conditional visibility via ``VisibleWhen`` metadata (no rule duplication)
- Real-time Pydantic validation with inline error display
- Load an existing TOML for editing
- Export to TOML file
"""

from __future__ import annotations

import json
import sys
import types as _stdlib_types
import typing
from pathlib import Path
from typing import Any, get_args, get_origin

try:
    import streamlit as st
except ImportError:
    sys.exit(
        "streamlit is required for the config UI.\n"
        "Install it with:  pip install streamlit"
    )

from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo

from hydromodpy.config.generate_toml import (
    _default_value,
    _get_param_level,
    _get_registry,
    _UNDEFINED,
)
from hydromodpy.config.param_level import PROFILES, ParamLevel, VisibleWhen


# ── Type introspection helpers ───────────────────────────────────────────


def _is_union_origin(origin: Any) -> bool:
    if origin is typing.Union:
        return True
    if hasattr(_stdlib_types, "UnionType") and origin is _stdlib_types.UnionType:
        return True
    return False


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    """Return (inner_type, is_optional)."""
    origin = get_origin(annotation)
    if _is_union_origin(origin):
        args = get_args(annotation)
        non_none = [a for a in args if a is not type(None)]
        if type(None) in args and non_none:
            return non_none[0], True
    return annotation, False


def _get_literal_choices(annotation: Any) -> list | None:
    inner, _ = _unwrap_optional(annotation)
    args = get_args(inner)
    if args and all(isinstance(a, (str, int, float)) for a in args):
        return list(args)
    return None


def _get_visible_when(field_info: FieldInfo) -> VisibleWhen | None:
    """Extract VisibleWhen from Annotated metadata, or None."""
    for meta in field_info.metadata:
        if isinstance(meta, VisibleWhen):
            return meta
    return None


def _resolve_basemodel(field_info: FieldInfo) -> type[BaseModel] | None:
    annotation = field_info.annotation
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    origin = get_origin(annotation)
    if origin is None:
        return None
    if isinstance(origin, type) and issubclass(origin, (list, dict, set, tuple)):
        return None
    args = get_args(annotation)
    non_none = [a for a in args if a is not type(None)]
    for a in non_none:
        if isinstance(a, type) and issubclass(a, BaseModel):
            return a
    return None


def _resolve_list_basemodel(field_info: FieldInfo) -> type[BaseModel] | None:
    if get_origin(field_info.annotation) is not list:
        return None
    args = get_args(field_info.annotation)
    if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
        return args[0]
    return None


# ── Widget renderer ──────────────────────────────────────────────────────


def _render_scalar(
    key: str,
    field_info: FieldInfo,
    values: dict[str, Any],
    widget_key: str,
) -> None:
    """Render one scalar Pydantic field as a Streamlit widget."""
    annotation = field_info.annotation
    inner, is_optional = _unwrap_optional(annotation)
    default = _default_value(field_info)
    current = values.get(key, default if default is not _UNDEFINED else None)

    desc = field_info.description or ""
    label = key
    help_text = desc or None

    is_required = default is _UNDEFINED
    if is_required:
        label = f"{key} *"

    # Literal → selectbox
    choices = _get_literal_choices(annotation)
    if choices:
        str_choices = [str(c) for c in choices]
        idx = 0
        if current is not None and str(current) in str_choices:
            idx = str_choices.index(str(current))
        if is_optional:
            str_choices = ["(none)"] + str_choices
            idx = (idx + 1) if current is not None else 0
        picked = st.selectbox(label, str_choices, index=idx, help=help_text, key=widget_key)
        if picked == "(none)":
            values[key] = None
        else:
            # Return original type
            orig = [c for c in choices if str(c) == picked]
            values[key] = orig[0] if orig else picked
        return

    inner_name = getattr(inner, "__name__", str(inner))

    # bool
    if inner is bool or inner_name == "bool":
        values[key] = st.checkbox(label, value=bool(current or False), help=help_text, key=widget_key)
        return

    # int
    if inner is int or inner_name == "int":
        values[key] = st.number_input(
            label, value=int(current or 0), step=1, help=help_text, key=widget_key,
        )
        return

    # float
    if inner is float or inner_name == "float":
        values[key] = st.number_input(
            label, value=float(current or 0.0), format="%g", help=help_text, key=widget_key,
        )
        return

    # list
    if inner is list or get_origin(inner) is list or inner_name == "list":
        raw = current if isinstance(current, list) else []
        txt = st.text_input(label, value=json.dumps(raw), help=help_text, key=widget_key)
        try:
            values[key] = json.loads(txt)
        except Exception:
            values[key] = raw
        return

    # dict
    if inner is dict or get_origin(inner) is dict or inner_name == "dict":
        raw = current if isinstance(current, dict) else {}
        txt = st.text_area(label, value=json.dumps(raw, indent=2), help=help_text, key=widget_key, height=80)
        try:
            values[key] = json.loads(txt)
        except Exception:
            values[key] = raw
        return

    # Path → text_input (treated as string in UI)
    if inner is Path or inner_name == "Path":
        val = str(current) if current is not None else ""
        values[key] = st.text_input(label, value=val, help=help_text, key=widget_key)
        return

    # str or anything else → text_input
    val = str(current) if current is not None else ""
    values[key] = st.text_input(label, value=val, help=help_text, key=widget_key)


def render_model(
    section_name: str,
    model_cls: type[BaseModel],
    threshold: int,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Render all visible fields of a Pydantic model."""
    result = dict(values)

    scalar_fields = []
    nested_fields = []
    array_fields = []

    for name, field_info in model_cls.model_fields.items():
        if getattr(field_info, "exclude", False):
            continue
        level = _get_param_level(field_info)
        if PROFILES.get(level, 0) > threshold:
            continue

        list_cls = _resolve_list_basemodel(field_info)
        if list_cls is not None:
            array_fields.append((name, field_info, list_cls))
            continue
        nested_cls = _resolve_basemodel(field_info)
        if nested_cls is not None:
            nested_fields.append((name, field_info, nested_cls))
        else:
            scalar_fields.append((name, field_info))

    # ── Scalar fields with conditional visibility ────────────────────
    for name, field_info in scalar_fields:
        vw = _get_visible_when(field_info)
        if vw is not None:
            sibling_val = result.get(vw.field)
            if not vw.matches(sibling_val):
                # Field hidden — keep existing value but don't show widget
                continue

        widget_key = f"{section_name}.{name}"
        _render_scalar(name, field_info, result, widget_key)

    # ── Nested sub-models → expander ────────────────────────────────
    for name, field_info, nested_cls in nested_fields:
        sub_section = f"{section_name}.{name}"
        vw = _get_visible_when(field_info)
        if vw is not None and not vw.matches(result.get(vw.field)):
            continue

        desc = field_info.description or name
        first_line = desc.split(".")[0].strip()
        with st.expander(f"{sub_section} — {first_line}", expanded=False):
            sub_values = result.get(name, {})
            if not isinstance(sub_values, dict):
                sub_values = {}
            result[name] = render_model(sub_section, nested_cls, threshold, sub_values)

    # ── Array-of-tables ─────────────────────────────────────────────
    for name, field_info, item_cls in array_fields:
        sub_section = f"{section_name}.{name}"
        st.markdown(f"**{sub_section}**")

        items = result.get(name, [])
        if not isinstance(items, list):
            items = []

        new_items = []
        to_remove = set()
        for i, item in enumerate(items):
            cols = st.columns([10, 1])
            with cols[0]:
                with st.expander(f"[{i}]", expanded=True):
                    if not isinstance(item, dict):
                        item = {}
                    new_items.append(render_model(f"{sub_section}[{i}]", item_cls, threshold, item))
            with cols[1]:
                if st.button("✕", key=f"rm_{sub_section}_{i}"):
                    to_remove.add(i)

        new_items = [it for idx, it in enumerate(new_items) if idx not in to_remove]

        if st.button(f"+ Ajouter", key=f"add_{sub_section}"):
            new_items.append({})

        result[name] = new_items

    return result


# ── Pydantic validation ─────────────────────────────────────────────────


def validate_section(
    module_name: str,
    model_cls: type[BaseModel],
    values: dict[str, Any],
) -> list[str]:
    """Try to validate values against the model, return error messages."""
    # Strip empty strings (same as the TOML loader does)
    from hydromodpy.config.toml_loader import _strip_empty_strings
    cleaned = _strip_empty_strings(values)
    try:
        model_cls.model_validate(cleaned)
        return []
    except ValidationError as exc:
        return [
            f"**{'.'.join(str(l) for l in err['loc'])}** — {err['msg']}"
            for err in exc.errors()
        ]


# ── TOML serialization ──────────────────────────────────────────────────


def _fmt_toml(val: Any) -> str:
    if val is None:
        return '""'
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, str):
        return f'"{val}"'
    if isinstance(val, Path):
        return f'"{val}"'
    if isinstance(val, (list, tuple)):
        inner = ", ".join(_fmt_toml(i) for i in val)
        return f"[{inner}]"
    return str(val)


def _dict_to_toml(data: dict[str, Any], prefix: str = "") -> list[str]:
    """Minimal dict → TOML lines."""
    lines: list[str] = []
    scalars = {}
    tables = {}

    for key, val in data.items():
        if isinstance(val, dict):
            tables[key] = val
        elif isinstance(val, list) and val and isinstance(val[0], dict):
            tables[key] = val
        else:
            scalars[key] = val

    if scalars:
        if prefix:
            lines.append(f"\n[{prefix}]")
        for k, v in scalars.items():
            lines.append(f"{k} = {_fmt_toml(v)}")

    for k, v in tables.items():
        sub = f"{prefix}.{k}" if prefix else k
        if isinstance(v, list):
            for item in v:
                lines.append(f"\n[[{sub}]]")
                for ik, iv in item.items():
                    if not isinstance(iv, dict):
                        lines.append(f"{ik} = {_fmt_toml(iv)}")
        else:
            lines.extend(_dict_to_toml(v, prefix=sub))

    return lines


# ── TOML loading ─────────────────────────────────────────────────────────


def _load_existing_toml(path: Path) -> dict[str, dict[str, Any]]:
    """Load an existing config.toml into per-module dicts."""
    from hydromodpy.config.toml_loader import load_toml_with_base_config
    raw = load_toml_with_base_config(path)
    return raw


# ── Main app ─────────────────────────────────────────────────────────────


def main() -> None:
    st.set_page_config(page_title="HydroModPy Config", layout="wide")
    st.title("HydroModPy — Configuration interactive")
    st.caption("Interface auto-générée depuis les modèles Pydantic. Les champs marqués * sont requis.")

    registry = _get_registry()

    # ── Sidebar ──────────────────────────────────────────────────────
    with st.sidebar:
        st.header("Options")
        profile = st.selectbox("Profil", list(PROFILES.keys()), index=0)
        threshold = PROFILES[profile]

        all_modules = list(registry.keys())
        default_modules = ["workspace", "geographic", "domain", "data", "flow", "transport", "modflownwt"]
        selected = st.multiselect(
            "Modules",
            all_modules,
            default=[m for m in default_modules if m in all_modules],
        )

        st.divider()
        st.subheader("Charger un TOML existant")
        load_path = st.text_input("Chemin du fichier", value="", placeholder="config.toml")
        if st.button("Charger") and load_path:
            p = Path(load_path)
            if p.exists():
                try:
                    loaded = _load_existing_toml(p)
                    st.session_state.config_values = loaded
                    st.success(f"Chargé : {p}")
                except Exception as exc:
                    st.error(f"Erreur : {exc}")
            else:
                st.error(f"Fichier introuvable : {p}")

        st.divider()
        export_path = st.text_input("Fichier de sortie", value="config.toml", key="export_path")

    # ── State ────────────────────────────────────────────────────────
    if "config_values" not in st.session_state:
        st.session_state.config_values = {}

    # ── Module tabs ──────────────────────────────────────────────────
    if selected:
        tabs = st.tabs(selected)
        for tab, module_name in zip(tabs, selected):
            with tab:
                model_cls = registry[module_name]
                existing = st.session_state.config_values.get(module_name, {})
                if not isinstance(existing, dict):
                    existing = {}

                # Render the form
                updated = render_model(module_name, model_cls, threshold, existing)
                st.session_state.config_values[module_name] = updated

                # Live validation
                st.divider()
                errors = validate_section(module_name, model_cls, updated)
                if errors:
                    st.warning(f"{len(errors)} erreur(s) de validation")
                    for err in errors:
                        st.markdown(f"- {err}")
                else:
                    st.success("Validation OK")

    # ── Export ────────────────────────────────────────────────────────
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Exporter TOML", type="primary"):
            lines = [
                "# " + "=" * 70,
                "# HydroModPy Configuration",
                f"# Profile: {profile} | Modules: {', '.join(selected)}",
                "# " + "=" * 70,
                "",
            ]
            for module_name in selected:
                vals = st.session_state.config_values.get(module_name, {})
                lines.extend(_dict_to_toml(vals, prefix=module_name))

            content = "\n".join(lines) + "\n"

            if export_path:
                Path(export_path).write_text(content, encoding="utf-8")
                st.success(f"Exporté vers {export_path}")

            st.download_button(
                "Télécharger",
                data=content,
                file_name=Path(export_path).name if export_path else "config.toml",
                mime="text/plain",
            )

    with col2:
        if st.toggle("Aperçu TOML"):
            preview_lines = []
            for module_name in selected:
                vals = st.session_state.config_values.get(module_name, {})
                preview_lines.extend(_dict_to_toml(vals, prefix=module_name))
            st.code("\n".join(preview_lines), language="toml")


if __name__ == "__main__":
    main()
