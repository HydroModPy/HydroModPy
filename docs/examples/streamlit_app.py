"""Minimal Streamlit example that consumes ``schema/config.json``.

Run with::

    hmp schema export --output ./schema/
    streamlit run docs/examples/streamlit_app.py

The goal is to demonstrate that a frontend can render a form without
importing HydroModPy directly — only the three JSON files produced by
``hmp schema export`` are read. ``streamlit`` is **not** part of the
HydroModPy dependencies; install it separately if you want to try the
example (``pip install streamlit``).

The script is importable even when ``streamlit`` is missing: it checks
the import lazily so unit tests can ``python docs/examples/streamlit_app.py``
without failing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


DEFAULT_SCHEMA_DIR = Path("schema")


def load_schema(schema_dir: Path) -> dict[str, Any]:
    """Return the parsed ``config.json`` (Pydantic JSON Schema)."""
    schema_path = schema_dir / "config.json"
    if not schema_path.is_file():
        raise FileNotFoundError(
            f"{schema_path} is missing; run 'hmp schema export --output {schema_dir}' first."
        )
    return json.loads(schema_path.read_text(encoding="utf-8"))


def load_meta(schema_dir: Path) -> dict[str, Any]:
    meta_path = schema_dir / "config_meta.json"
    if not meta_path.is_file():
        return {"sections": [], "groups": {}}
    return json.loads(meta_path.read_text(encoding="utf-8"))


def iter_section_fields(
    schema: dict[str, Any],
    section_name: str,
) -> list[tuple[str, dict[str, Any]]]:
    """Flatten a section into ``(field_name, field_schema)`` tuples."""
    section_ref = schema.get("properties", {}).get(section_name, {})
    ref = section_ref.get("$ref") or (section_ref.get("allOf", [{}])[0].get("$ref"))
    if not ref or not ref.startswith("#/$defs/"):
        return []
    def_name = ref.split("/")[-1]
    target = schema.get("$defs", {}).get(def_name, {})
    props = target.get("properties", {})
    return sorted(props.items(), key=lambda item: item[1].get("x-order", 0))


def render_field(st, name: str, info: dict[str, Any]) -> Any:
    """Render a single field based on its ``widget_type`` annotation."""
    label = info.get("display_name_fr") or info.get("title", name)
    help_text = info.get("help_text_fr") or info.get("description")
    widget = info.get("widget_type", "input")
    unit = info.get("unit")
    suffix = f" [{unit}]" if unit else ""

    if widget == "slider" and {"display_min", "display_max"} <= info.keys():
        default = info.get("default", info["display_min"])
        return st.slider(
            label + suffix,
            min_value=float(info["display_min"]),
            max_value=float(info["display_max"]),
            value=float(default),
            help=help_text,
        )
    if widget == "checkbox":
        return st.checkbox(label, value=bool(info.get("default", False)), help=help_text)
    if widget == "select" and "enum" in info:
        return st.selectbox(label, info["enum"], help=help_text)
    return st.text_input(label + suffix, value=str(info.get("default", "")), help=help_text)


def main(schema_dir: Path = DEFAULT_SCHEMA_DIR) -> None:  # pragma: no cover - UI
    try:
        import streamlit as st
    except ImportError:
        print(
            "streamlit is not installed. Run 'pip install streamlit' before "
            "'streamlit run docs/examples/streamlit_app.py'.",
            file=sys.stderr,
        )
        return

    st.set_page_config(page_title="HydroModPy config", layout="wide")
    st.title("HydroModPy — schema-driven form")

    try:
        schema = load_schema(schema_dir)
    except FileNotFoundError as exc:
        st.error(str(exc))
        return

    meta = load_meta(schema_dir)
    sections = meta.get("sections") or [{"name": name} for name in schema.get("properties", {})]

    tabs = st.tabs([s["name"] for s in sections])
    values: dict[str, dict[str, Any]] = {}
    for tab, section in zip(tabs, sections):
        with tab:
            st.subheader(section.get("title", section["name"]))
            if section.get("description"):
                st.caption(section["description"])
            values[section["name"]] = {}
            for field_name, field_info in iter_section_fields(schema, section["name"]):
                values[section["name"]][field_name] = render_field(st, field_name, field_info)

    if st.button("Show payload"):
        st.json(values)


if __name__ == "__main__":
    main()
