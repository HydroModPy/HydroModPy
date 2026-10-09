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

Editor schema
-------------
:func:`export_editor_schema` is the document an editor reads through a
``#:schema`` header. ``HydroModPyConfig.model_json_schema()`` describes the
model, and a file is not the model: the loader reads it first. The editor
schema therefore accepts what the loader accepts and the model alone does not
say:

- ``base_config`` at the top level, and a file that omits any key (an overlay
  states only what it changes, so no ``required`` survives);
- the ``<key>__append`` and ``<key>__delete`` forms of a key (see
  :mod:`hydromodpy.core.toml_io.merge`);
- a quantity written as text with a unit (``'150 m'``, ``'0.36 m/h'``) wherever
  the field is a quantity type;
- a date written without a time (``2019-01-01``) where the model reads a datetime;
- a list item that omits its discriminator in an overlay (``oneOf`` becomes
  ``anyOf``);
- the flat ``[flow.ic]`` form.

What it cannot say stays with ``hmp config check``: the files a ``base_config``
chain merges, the rules between two keys, the bounds of a quantity once its unit
is converted, and every key that only exists after the merge.

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
import re
from functools import cache
from pathlib import Path
from typing import Any

from pydantic.json_schema import GenerateJsonSchema

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


# ---------------------------------------------------------------------------
# Editor schema: what the loader accepts
# ---------------------------------------------------------------------------

_QUANTITY_PATTERN = r"^\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\s*(?:\S.*)?$"
"""A number, then an optional unit: ``'150 m'``, ``'1e-4 m/s'``, ``'0.2'``."""

_QUANTITY_TEXT: dict[str, Any] = {
    "type": "string",
    "pattern": _QUANTITY_PATTERN,
    "description": "A quantity as text: a number then a unit, for example '150 m' or '0.36 m/h'.",
}

_QUANTITY_COERCERS = ("_coerce_bare_number.", "_coerce_to_canonical_float.")
_UNITS_MODULE = "hydromodpy.core.units.types"

_DATE_TEXT_PATTERN = (
    r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$"
)
"""A date, or a date and a time: ``2019-01-01``, ``2019-01-01T06:00:00Z``."""

_APPEND_SUFFIX = "__append"
_DELETE_SUFFIX = "__delete"
_ANY_KEY = ".+"

_BASE_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "string",
    "description": (
        "Path of a TOML file this file extends, relative to this file. The keys written "
        "here replace the ones the base file sets. Lists replace the base list unless the "
        "key carries the suffix __append, and a key is removed with <key>__delete = true."
    ),
}

_DELETE_DIRECTIVE: dict[str, Any] = {
    "const": True,
    "description": "Remove the inherited key. Only the literal true is accepted.",
}


def _accepts_number(node: dict[str, Any]) -> bool:
    """Whether a property schema already admits a JSON number."""
    if node.get("type") in ("number", "integer"):
        return True
    return any(
        _accepts_number(member)
        for key in ("anyOf", "oneOf")
        for member in node.get(key, ())
        if isinstance(member, dict)
    )


class _EditorSchemaGenerator(GenerateJsonSchema):
    """Let a quantity type say that it also reads text with a unit.

    A quantity field validates a number or a string such as ``'150 m'``. The
    default generator only sees the number, so a file that writes the unit is
    flagged in the editor although the loader reads it. The check is the origin
    of the validator, never the name of the field.
    """

    def function_before_schema(self, schema: Any) -> Any:  # noqa: D102
        result = super().function_before_schema(schema)
        function = schema.get("function")
        function = function.get("function") if isinstance(function, dict) else function
        qualname = getattr(function, "__qualname__", "")
        if getattr(function, "__module__", "") == _UNITS_MODULE and qualname.startswith(
            _QUANTITY_COERCERS
        ):
            # A pint type describes its text and object forms and not the bare
            # number the loader reads as the canonical unit.
            number = [] if _accepts_number(result) else [{"type": "number"}]
            return {"anyOf": [result, *number, dict(_QUANTITY_TEXT)]}
        return result


@cache
def _cached_editor_schema(model_cls: type) -> dict[str, Any]:
    return model_cls.model_json_schema(schema_generator=_EditorSchemaGenerator)


_SUBSCHEMA_MAPS = ("properties", "patternProperties", "$defs")
_SUBSCHEMA_LISTS = ("anyOf", "oneOf", "allOf", "prefixItems")
_SUBSCHEMA_VALUES = ("items", "additionalProperties", "not", "contains", "propertyNames")


def _subschemas(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the schema members of *node*, never its data (defaults, examples, enums)."""
    found: list[dict[str, Any]] = []
    for key in _SUBSCHEMA_MAPS:
        value = node.get(key)
        if isinstance(value, dict):
            found.extend(v for v in value.values() if isinstance(v, dict))
    for key in _SUBSCHEMA_LISTS:
        value = node.get(key)
        if isinstance(value, list):
            found.extend(v for v in value if isinstance(v, dict))
    for key in _SUBSCHEMA_VALUES:
        value = node.get(key)
        if isinstance(value, dict):
            found.append(value)
    return found


def _array_branch(node: dict[str, Any]) -> dict[str, Any] | None:
    """Return the array member of a property schema, or ``None`` if it has none."""
    if node.get("type") == "array":
        return node
    for key in ("anyOf", "oneOf"):
        for member in node.get(key, ()):
            if isinstance(member, dict) and (found := _array_branch(member)) is not None:
                return found
    return None


def _model_directive_patterns(properties: dict[str, Any]) -> dict[str, Any]:
    """Return the ``patternProperties`` that admit the merge directives of a model.

    ``__delete`` may name any key: an overlay that switches a union to another
    variant removes a key the new variant does not even declare. ``__append``
    must name a key that holds a list, and carries that list's item schema.
    """
    patterns: dict[str, Any] = {f"^{_ANY_KEY}{_DELETE_SUFFIX}$": dict(_DELETE_DIRECTIVE)}
    for name, member in sorted(properties.items()):
        branch = _array_branch(member) if isinstance(member, dict) else None
        if branch is not None:
            items = {"items": branch["items"]} if "items" in branch else {}
            patterns[f"^{re.escape(name)}{_APPEND_SUFFIX}$"] = {"type": "array", **items}
    return patterns


def _admit_directives(node: dict[str, Any]) -> None:
    """Make an object schema accept ``<key>__append`` and ``<key>__delete`` (in place).

    A schema that already accepts any key needs nothing. A model that refuses
    unknown keys gets its directives named by key, and a map of free keys cannot
    name them, so any key may carry a suffix there.
    """
    properties = node.get("properties")
    patterns = node.get("patternProperties")
    extra = node.get("additionalProperties")
    if isinstance(properties, dict) and properties:
        if extra is False:
            node["patternProperties"] = {
                **(patterns or {}),
                **_model_directive_patterns(properties),
            }
    elif isinstance(patterns, dict) and patterns:
        # The key pattern of the map (``domain.supports``) matches a suffixed key
        # too, and every matching pattern applies: the value is widened instead.
        for key, member in list(patterns.items()):
            patterns[key] = {"anyOf": [member, dict(_DELETE_DIRECTIVE), {"type": "array"}]}
    elif isinstance(extra, dict):
        node["patternProperties"] = {
            f"^{_ANY_KEY}{_DELETE_SUFFIX}$": dict(_DELETE_DIRECTIVE),
            f"^{_ANY_KEY}{_APPEND_SUFFIX}$": {"type": "array"},
        }


def _relax_for_loader(node: dict[str, Any]) -> None:
    """Rewrite a schema node for a file the loader merges before it validates (in place)."""
    for member in _subschemas(node):
        _relax_for_loader(member)

    node.pop("required", None)
    if node.get("type") == "string" and node.get("format") == "date-time":
        # The model reads a bare date such as ``2019-01-01`` as midnight. A
        # validator that asserts the RFC 3339 format would refuse it.
        node.pop("format")
        node["pattern"] = _DATE_TEXT_PATTERN
    if "oneOf" in node:
        # A discriminated list item may omit its tag in an overlay: the merge
        # pairs the items by index, so exactly-one is no longer decidable.
        alternatives = node.pop("oneOf")
        if "anyOf" in node:
            node.setdefault("allOf", []).append({"anyOf": alternatives})
        else:
            node["anyOf"] = alternatives
    _admit_directives(node)


def _admit_flat_flow_ic(schema: dict[str, Any]) -> None:
    """Accept the flat ``[flow.ic]`` form next to the ``{h = ...}`` container.

    ``FlowConfig`` normalises ``[flow.ic] type = "top"`` into the container
    before validation, so the model schema only describes the container.
    """
    defs = schema.get("$defs", {})
    flow = defs.get("FlowConfig", {}).get("properties", {})
    container = defs.get("FlowInitialConditions", {}).get("properties", {}).get("h", {})
    variants = container.get("anyOf") or container.get("oneOf")
    if "ic" not in flow or not variants:
        raise RuntimeError(
            "the flat [flow.ic] form can no longer be derived from FlowConfig: "
            "update hydromodpy.config.schema_export._admit_flat_flow_ic"
        )
    original = flow["ic"]
    extras = {k: original[k] for k in ("description", "x-hmp-profile") if k in original}
    flow["ic"] = {**extras, "anyOf": [{"$ref": "#/$defs/FlowInitialConditions"}, *variants]}


def editor_schema(model_cls: type | None = None) -> dict[str, Any]:
    """Return the JSON Schema a TOML file is checked against in an editor.

    See the module docstring for what it accepts beyond the model schema. The
    full model is exported by :func:`export_schema` and stays the contract for
    frontends and for the lockfile fingerprint.
    """
    if model_cls is None:
        from hydromodpy.config import HydroModPyConfig

        model_cls = HydroModPyConfig
    schema = json.loads(json.dumps(_cached_editor_schema(model_cls)))
    if model_cls.__name__ == "HydroModPyConfig":
        _admit_flat_flow_ic(schema)
    _relax_for_loader(schema)
    properties = schema.setdefault("properties", {})
    properties["base_config"] = dict(_BASE_CONFIG_SCHEMA)

    document = {"$schema": JSON_SCHEMA_DIALECT, **schema}
    document["$comment"] = (
        "Generated by hydromodpy.config.schema_export.editor_schema. "
        "Checks the keys and the types of one TOML file. `hmp config check` checks "
        "the merged configuration."
    )
    return document


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
    "editor_schema",
    "export_schema",
    "extract_property_schema",
    "model_scope",
    "schema_sha256",
    "schema_urn",
    "write_schema",
]
