"""JSON Schema export for HydroModPy Pydantic configuration models.

Exports the JSON Schema describing ``HydroModPyConfig`` (or any sub-model)
so that IDEs (VS Code + ``even-better-toml``, JSON-Schema-aware UIs) can
provide autocompletion, validation, and documentation for HydroModPy TOML
configurations.

The exporter preserves the rich ``json_schema_extra`` annotations attached
to fields (``widget_type``, ``unit``, ``display_name_fr``, ``help_text_fr``,
``display_min``, ``display_max``) which a front-end (Streamlit, React, ...)
can consume to render tailored widgets.

Profile filtering
-----------------
Use ``profile="user"`` (or ``"dev"``, ``"expert"``) to drop fields whose
``x-hmp-profile`` exceeds the requested level. Frontends targeted at
hydrogeologists can then receive a pre-trimmed schema instead of filtering
every property themselves.

Usage
-----
Python API::

    from hydromodpy.config.schema_export import export_schema, ROOT_SECTIONS
    from hydromodpy.physics.flow.flow_config import FlowConfig

    schema = export_schema(FlowConfig)
    # full root schema:
    schema = export_schema()

    # by section name (e.g. "flow", "workspace", ...)
    schema = export_schema(section="flow")

    # filtered by profile
    schema = export_schema(profile="user")

CLI::

    hmp config schema                     # full root schema to stdout
    hmp config schema --section flow      # one section
    hmp config schema --profile user      # filtered to user-level fields
    hmp config schema --out schema.json   # write to file
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from hydromodpy.core.config_kit.introspect import read_profile_from_schema
from hydromodpy.core.config_kit.profile import Profile, ProfileName
from hydromodpy.core.config_kit.registry import root_sections as _root_sections


def _ensure_root_sections() -> dict[str, type]:
    """Return the map of root-level TOML sections to Pydantic model classes."""
    return _root_sections()


def _resolve_profile(profile: ProfileName | Profile | None) -> Profile | None:
    if profile is None:
        return None
    if isinstance(profile, Profile):
        return profile
    try:
        return Profile[profile.upper()]
    except KeyError as exc:
        allowed = ", ".join(p.name.lower() for p in Profile)
        raise ValueError(f"unknown profile {profile!r} (allowed: {allowed})") from exc


def _filter_properties_by_profile(
    schema_node: dict[str, Any],
    threshold: Profile,
) -> None:
    """Drop properties whose ``x-hmp-profile`` exceeds *threshold* (in place)."""
    properties = schema_node.get("properties")
    if not isinstance(properties, dict):
        return
    required = schema_node.get("required")
    required_list = list(required) if isinstance(required, list) else None

    drop: list[str] = []
    for name, field_schema in properties.items():
        if not isinstance(field_schema, dict):
            continue
        level = read_profile_from_schema(field_schema)
        if level is None:
            continue
        if level > threshold:
            drop.append(name)

    for name in drop:
        properties.pop(name, None)
        if required_list is not None and name in required_list:
            required_list.remove(name)

    if required_list is not None:
        schema_node["required"] = required_list


def _walk_and_filter(node: Any, threshold: Profile) -> None:
    if isinstance(node, dict):
        if "properties" in node:
            _filter_properties_by_profile(node, threshold)
        for value in node.values():
            _walk_and_filter(value, threshold)
    elif isinstance(node, list):
        for item in node:
            _walk_and_filter(item, threshold)


_DEF_REF_PREFIX = "#/$defs/"


def _collect_referenced_defs(node: Any, sink: set[str]) -> None:
    """Recursively collect every ``$defs/<name>`` reference reachable from *node*."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(_DEF_REF_PREFIX):
            sink.add(ref[len(_DEF_REF_PREFIX) :])
        for key, value in node.items():
            if key == "$defs":
                continue
            _collect_referenced_defs(value, sink)
    elif isinstance(node, list):
        for item in node:
            _collect_referenced_defs(item, sink)


def _prune_orphan_defs(schema: dict[str, Any]) -> None:
    """Remove ``$defs`` entries no longer reachable after profile filtering."""
    defs = schema.get("$defs")
    if not isinstance(defs, dict):
        return

    while True:
        reachable: set[str] = set()
        _collect_referenced_defs(schema, reachable)
        for name in list(defs):
            inner_refs: set[str] = set()
            if name in reachable:
                _collect_referenced_defs(defs[name], inner_refs)
                reachable |= inner_refs
        orphans = [name for name in defs if name not in reachable]
        if not orphans:
            break
        for name in orphans:
            defs.pop(name, None)
    if not defs:
        schema.pop("$defs", None)


@cache
def _cached_full_schema(model_cls: type) -> dict[str, Any]:
    return model_cls.model_json_schema()


def export_schema(
    model_cls: type | None = None,
    *,
    section: str | None = None,
    profile: ProfileName | Profile | None = None,
) -> dict[str, Any]:
    """Export a JSON Schema dict for a HydroModPy configuration model.

    Parameters
    ----------
    model_cls
        A Pydantic ``BaseModel`` subclass. If ``None``, the root
        ``HydroModPyConfig`` model is used.
    section
        Name of a root TOML section (see :func:`_ensure_root_sections`). When
        given, overrides ``model_cls``.
    profile
        Optional ``"user"``, ``"dev"``, or ``"expert"`` filter. Fields whose
        ``x-hmp-profile`` exceeds the requested level are removed (recursively,
        including ``$defs`` entries).

    Returns
    -------
    dict
        JSON Schema document (draft 2020-12 compatible, as emitted by
        Pydantic v2).
    """
    if section is not None:
        sections = _ensure_root_sections()
        if section not in sections:
            allowed = ", ".join(sorted(sections))
            raise ValueError(f"unknown config section {section!r} (allowed: {allowed})")
        model_cls = sections[section]

    if model_cls is None:
        from hydromodpy.config import HydroModPyConfig

        model_cls = HydroModPyConfig

    threshold = _resolve_profile(profile)
    schema = json.loads(json.dumps(_cached_full_schema(model_cls)))
    if threshold is not None:
        _walk_and_filter(schema, threshold)
        _prune_orphan_defs(schema)
    schema.setdefault("$comment", "Generated by hydromodpy.config.schema_export")
    return schema


def write_schema(
    path: str | Path,
    *,
    model_cls: type | None = None,
    section: str | None = None,
    profile: ProfileName | Profile | None = None,
    indent: int = 2,
) -> Path:
    """Serialize an exported schema to a JSON file.

    Returns the resolved :class:`Path` of the written file.
    """
    schema = export_schema(model_cls, section=section, profile=profile)
    out_path = Path(path).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(schema, indent=indent, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out_path


__all__ = ["export_schema", "write_schema"]
