"""Profile filtering and list-merge ``__append`` semantics."""

from __future__ import annotations

import pytest

from hydromodpy.config.schema_export import export_schema
from hydromodpy.core.toml_io.merge import merge_toml_payloads


def _properties(schema: dict) -> dict:
    return schema.get("properties", {})


def test_export_schema_full_includes_all_profiles() -> None:
    schema = export_schema()
    assert _properties(schema), "root schema must expose properties"


def test_export_schema_user_drops_dev_and_expert_fields() -> None:
    full = export_schema()
    user = export_schema(profile="user")

    assert set(_properties(user)).issubset(set(_properties(full)))
    for field_schema in _properties(user).values():
        level = field_schema.get("x-hmp-profile")
        if level is None:
            continue
        assert level in {"user"}


def test_export_schema_dev_includes_user_and_dev_fields() -> None:
    user = export_schema(profile="user")
    dev = export_schema(profile="dev")

    assert set(_properties(user)).issubset(set(_properties(dev)))
    for field_schema in _properties(dev).values():
        level = field_schema.get("x-hmp-profile")
        if level is None:
            continue
        assert level in {"user", "dev"}


def test_export_schema_expert_keeps_all_fields() -> None:
    full = export_schema()
    expert = export_schema(profile="expert")
    assert set(_properties(full)) == set(_properties(expert))


def test_export_schema_unknown_profile_raises() -> None:
    with pytest.raises(ValueError, match="unknown profile"):
        export_schema(profile="nope")


def test_merge_replaces_lists_by_default() -> None:
    base = {"flow": {"process": ["A", "B"]}}
    overlay = {"flow": {"process": ["C"]}}
    merged = merge_toml_payloads(base, overlay)
    assert merged == {"flow": {"process": ["C"]}}


def test_merge_append_suffix_concatenates_lists() -> None:
    base = {"flow": {"process": ["A", "B"]}}
    overlay = {"flow": {"process__append": ["C"]}}
    merged = merge_toml_payloads(base, overlay)
    assert merged == {"flow": {"process": ["A", "B", "C"]}}


def test_merge_append_creates_missing_key() -> None:
    base: dict = {"flow": {}}
    overlay = {"flow": {"process__append": ["C"]}}
    merged = merge_toml_payloads(base, overlay)
    assert merged == {"flow": {"process": ["C"]}}


def test_merge_append_rejects_non_list_value() -> None:
    base: dict = {}
    overlay = {"flow__append": "C"}
    with pytest.raises(ValueError, match="requires a list value"):
        merge_toml_payloads(base, overlay)


def test_merge_append_rejects_non_list_target() -> None:
    base = {"flow": {"process": "A"}}
    overlay = {"flow": {"process__append": ["C"]}}
    with pytest.raises(ValueError, match="cannot append to non-list"):
        merge_toml_payloads(base, overlay)


def test_merge_append_rejects_empty_target() -> None:
    base: dict = {}
    overlay = {"__append": ["C"]}
    with pytest.raises(ValueError, match="empty target key"):
        merge_toml_payloads(base, overlay)
