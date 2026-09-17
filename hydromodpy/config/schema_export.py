"""JSON Schema export for HydroModPy Pydantic configuration models.

Exports the JSON Schema describing ``HydroModPyConfig`` (or any sub-model)
so that IDEs (VS Code + ``even-better-toml``, JSON-Schema-aware UIs) can
provide autocompletion, validation, and documentation for HydroModPy TOML
configurations.

The exporter preserves the rich ``json_schema_extra`` annotations attached
to fields (``widget_type``, ``unit``, ``display_name_fr``, ``help_text_fr``,
``display_min``, ``display_max``) which a front-end (React, ...)
can consume to render tailored widgets.

Profile filtering
-----------------
Use ``profile="user"`` (or ``"dev"``, ``"expert"``) to drop fields whose
``x-hmp-profile`` exceeds the requested level. Frontends targeted at
hydrogeologists can then receive a pre-trimmed schema instead of filtering
every property themselves.

Identity
--------
Every exported document carries a ``$id``, a ``urn:`` that resolves to nothing
on purpose: no domain is registered, and a ``https://`` identifier that 404s is
worse than one that never promised to resolve. The scope after the version says
which model was exported, and a profile-filtered document takes a scope of its
own -- it is a different document, so it may not claim the identity of the full
one.

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

    # by dotted path into a section
    schema = export_schema(section="flow.properties")

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

from hydromodpy.core.config_kit.introspect import iter_basemodels, read_profile_from_schema
from hydromodpy.core.config_kit.profile import Profile, ProfileName
from hydromodpy.core.config_kit.registry import root_sections as _root_sections
from hydromodpy.core.version import __version__

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
"""The dialect Pydantic v2 emits, declared so an external validator stops guessing."""

SCHEMA_URN_PREFIX = "urn:hmp:schema"
"""Namespace of an exported schema. Resolves to nothing, by design."""

ROOT_SCOPE = "config"
"""The scope of the full ``HydroModPyConfig`` document."""


def schema_urn(scope: str, *, version: str | None = None) -> str:
    """Return the ``urn:`` identity of the schema exported under *scope*."""
    return f"{SCHEMA_URN_PREFIX}:{version or __version__}:{scope}"


def model_scope(model_cls: type) -> str:
    """Return the scope naming *model_cls*, qualified by where it is declared.

    The bare class name is not unique in this tree: ``DemConfig`` exists in
    ``data.variables.dem.config`` and in ``spatial.site_selection.config.models``,
    with different properties. Two documents that accept different payloads may
    not answer to one identity, so the scope carries the import path, minus the
    ``hydromodpy.`` prefix every one of them shares.
    """
    module = getattr(model_cls, "__module__", "")
    dotted = f"{module}.{model_cls.__qualname__}" if module else model_cls.__qualname__
    return dotted.removeprefix("hydromodpy.")


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


def _resolve_section_model(section: str) -> type:
    """Return the model a root section name or a dotted path under one names.

    The first segment is a root TOML section. Every further segment is a field
    of the model resolved so far, and it must reach exactly one model: a field
    that reaches none names a value and not a section, and one that reaches
    several is a union whose variant the caller has to pick by class.
    """
    segments = section.split(".")
    if any(not part for part in segments):
        # Refused and not silently dropped: ``simulation..time`` resolves to the
        # same model as ``simulation.time``, and swallowing the empty segment
        # would mint two identities for one document.
        raise ValueError(f"config section {section!r} carries an empty segment")

    sections = _ensure_root_sections()
    head, *rest = segments
    if head not in sections:
        allowed = ", ".join(sorted(sections))
        raise ValueError(f"unknown config section {head!r} (allowed: {allowed})")

    model = sections[head]
    walked = head
    for name in rest:
        info = model.model_fields.get(name)
        if info is None:
            raise ValueError(f"unknown field {name!r} under {walked!r} in {model.__name__}")
        nested = iter_basemodels(info.annotation)
        if not nested:
            raise ValueError(f"{walked}.{name} names a value, not a section")
        if len(nested) > 1:
            variants = ", ".join(cls.__name__ for cls in nested)
            raise ValueError(
                f"{walked}.{name} names a union of {len(nested)} models ({variants}); "
                "export one of them by passing its class"
            )
        model = nested[0]
        walked = f"{walked}.{name}"
    return model


def extract_property_schema(schema: dict[str, Any], name: str) -> dict[str, Any]:
    """Return one top-level property of *schema* as a document of its own.

    The returned document carries the ``$defs`` entries its ``$ref`` members
    reach, and only those, so it validates without the schema it came from.
    """
    properties = schema.get("properties")
    if not isinstance(properties, dict) or name not in properties:
        available = ", ".join(sorted(properties)) if isinstance(properties, dict) else "none"
        raise KeyError(f"{name!r} is not a property of this schema (has: {available})")

    node: dict[str, Any] = json.loads(json.dumps(properties[name]))
    defs = schema.get("$defs")
    if not isinstance(defs, dict):
        return node

    reachable: set[str] = set()
    _collect_referenced_defs(node, reachable)
    frontier = list(reachable)
    while frontier:
        target = defs.get(frontier.pop())
        if target is None:
            continue
        nested: set[str] = set()
        _collect_referenced_defs(target, nested)
        for extra in nested - reachable:
            reachable.add(extra)
            frontier.append(extra)

    carried = {key: json.loads(json.dumps(defs[key])) for key in sorted(reachable) if key in defs}
    if carried:
        node["$defs"] = carried
    return node


@cache
def _cached_full_schema(model_cls: type) -> dict[str, Any]:
    return model_cls.model_json_schema()


def schema_sha256(model_cls: type | None = None) -> str:
    """Return the SHA-256 of the canonical JSON Schema for *model_cls*.

    Defaults to the full ``HydroModPyConfig`` schema. Used by the lockfile
    writer to record the schema fingerprint at freeze time so consumers can
    detect when the configuration schema has changed between freeze and
    replay.
    """
    import hashlib

    if model_cls is None:
        from hydromodpy.config import HydroModPyConfig

        model_cls = HydroModPyConfig
    payload = json.dumps(_cached_full_schema(model_cls), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def export_schema(
    model_cls: type | None = None,
    *,
    section: str | None = None,
    profile: ProfileName | Profile | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """Export a JSON Schema dict for a HydroModPy configuration model.

    Parameters
    ----------
    model_cls
        A Pydantic ``BaseModel`` subclass. If ``None``, the root
        ``HydroModPyConfig`` model is used.
    section
        Name of a root TOML section (see :func:`_ensure_root_sections`), or a
        dotted path under one such as ``"flow.properties"``. When given,
        overrides ``model_cls``.
    profile
        Optional ``"user"``, ``"dev"``, or ``"expert"`` filter. Fields whose
        ``x-hmp-profile`` exceeds the requested level are removed (recursively,
        including ``$defs`` entries).
    scope
        Overrides the scope of the ``$id``. Defaults to the section path, or
        the model name, and carries the profile when one filtered the document.

    Returns
    -------
    dict
        JSON Schema document (draft 2020-12 as emitted by Pydantic v2),
        carrying its dialect and its ``urn:`` identity.
    """
    if section is not None:
        model_cls = _resolve_section_model(section)
        default_scope = section
    elif model_cls is None:
        default_scope = ROOT_SCOPE
    else:
        default_scope = model_scope(model_cls)

    if model_cls is None:
        from hydromodpy.config import HydroModPyConfig

        model_cls = HydroModPyConfig

    threshold = _resolve_profile(profile)
    schema = json.loads(json.dumps(_cached_full_schema(model_cls)))
    if threshold is not None:
        _walk_and_filter(schema, threshold)
        _prune_orphan_defs(schema)
        default_scope = f"{default_scope}:{threshold.name.lower()}"

    schema.setdefault("$comment", "Generated by hydromodpy.config.schema_export")
    # Assigned after the merge, not before it: a model that carried its own
    # ``$id`` would otherwise win, and two documents would claim one identity.
    document = {"$schema": None, "$id": None, "x-hmp-version": None, **schema}
    document["$schema"] = JSON_SCHEMA_DIALECT
    document["$id"] = schema_urn(scope or default_scope)
    document["x-hmp-version"] = __version__
    return document


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


__all__ = [
    "JSON_SCHEMA_DIALECT",
    "ROOT_SCOPE",
    "SCHEMA_URN_PREFIX",
    "export_schema",
    "extract_property_schema",
    "model_scope",
    "schema_sha256",
    "schema_urn",
    "write_schema",
]
