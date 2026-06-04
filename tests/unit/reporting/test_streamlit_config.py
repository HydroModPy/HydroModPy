"""Unit tests for the pure introspection and serialization surface of the
Streamlit config editor.

This module is config/serialization code, not a running Streamlit UI. The
``main()`` app and widget renderers require a live streamlit runtime, so they
are out of scope here. We cover the deterministic, side-effect-free helpers:
type introspection, Pydantic validation, and the minimal dict -> TOML
serializer.
"""

from __future__ import annotations

import typing
from pathlib import Path
from typing import Annotated, Literal, Optional

import pytest
from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.reporting.streamlit_config import (
    _dict_to_toml,
    _fmt_toml,
    _get_literal_choices,
    _get_visible_when,
    _is_union_origin,
    _resolve_basemodel,
    _resolve_list_basemodel,
    _unwrap_optional,
    validate_section,
)


class _Inner(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: int = 0
    label: str = "default"


class _Sample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["a", "b", "c"] = "a"
    opt_mode: Literal["x", "y"] | None = None
    name: str = "hi"
    count: int | None = None
    inner: _Inner = Field(default_factory=_Inner)
    items: list[_Inner] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    cond: Annotated[str, VisibleWhen("mode", "a")] = "z"


@pytest.fixture
def fields() -> dict:
    return _Sample.model_fields


# ── Type introspection ───────────────────────────────────────────────────


@pytest.mark.fast
class TestTypeIntrospection:
    def test_is_union_origin_detects_optional(self) -> None:
        # Both union spellings must be detected; keep the legacy Optional form.
        assert _is_union_origin(typing.get_origin(Optional[int])) is True  # noqa: UP045
        assert _is_union_origin(typing.get_origin(int | None)) is True

    def test_is_union_origin_rejects_non_union(self) -> None:
        assert _is_union_origin(typing.get_origin(list[int])) is False
        assert _is_union_origin(None) is False

    def test_unwrap_optional_strips_none_and_flags(self, fields: dict) -> None:
        inner, is_optional = _unwrap_optional(fields["count"].annotation)
        assert inner is int
        assert is_optional is True

    def test_unwrap_optional_leaves_plain_type(self, fields: dict) -> None:
        inner, is_optional = _unwrap_optional(fields["name"].annotation)
        assert inner is str
        assert is_optional is False

    def test_literal_choices_for_plain_literal(self, fields: dict) -> None:
        assert _get_literal_choices(fields["mode"].annotation) == ["a", "b", "c"]

    def test_literal_choices_unwraps_optional_literal(self, fields: dict) -> None:
        assert _get_literal_choices(fields["opt_mode"].annotation) == ["x", "y"]

    def test_literal_choices_none_for_free_string(self, fields: dict) -> None:
        assert _get_literal_choices(fields["name"].annotation) is None

    def test_resolve_basemodel_on_nested_model(self, fields: dict) -> None:
        assert _resolve_basemodel(fields["inner"]) is _Inner

    def test_resolve_basemodel_none_for_scalar(self, fields: dict) -> None:
        assert _resolve_basemodel(fields["name"]) is None

    def test_resolve_basemodel_none_for_list_of_models(self, fields: dict) -> None:
        # A list[Model] is an array-of-tables, handled separately, so the
        # scalar/nested resolver must NOT claim it.
        assert _resolve_basemodel(fields["items"]) is None

    def test_resolve_list_basemodel_detects_array_of_tables(self, fields: dict) -> None:
        assert _resolve_list_basemodel(fields["items"]) is _Inner

    def test_resolve_list_basemodel_none_for_scalar_list(self, fields: dict) -> None:
        assert _resolve_list_basemodel(fields["tags"]) is None

    def test_get_visible_when_reads_annotated_metadata(self, fields: dict) -> None:
        vw = _get_visible_when(fields["cond"])
        assert vw is not None
        assert vw.field == "mode"
        assert vw.matches("a") is True
        assert vw.matches("b") is False

    def test_get_visible_when_none_when_absent(self, fields: dict) -> None:
        assert _get_visible_when(fields["name"]) is None


# ── Pydantic validation ──────────────────────────────────────────────────


@pytest.mark.fast
class TestValidateSection:
    def test_valid_values_yield_no_errors(self) -> None:
        assert validate_section("inner", _Inner, {"x": 5, "label": "ok"}) == []

    def test_type_error_is_reported_with_field_path(self) -> None:
        errors = validate_section("inner", _Inner, {"x": "not-an-int"})
        assert len(errors) == 1
        assert errors[0].startswith("**x**")
        assert "valid integer" in errors[0]

    def test_extra_field_is_rejected(self) -> None:
        errors = validate_section("inner", _Inner, {"x": 1, "ghost": 2})
        assert any("ghost" in err.lower() for err in errors)

    def test_empty_strings_are_stripped_before_validation(self) -> None:
        # An empty string for an int field would fail validation; the loader's
        # _strip_empty_strings drops it so the model default kicks in.
        assert validate_section("inner", _Inner, {"x": ""}) == []


# ── TOML serialization ───────────────────────────────────────────────────


@pytest.mark.fast
class TestFmtToml:
    def test_none_renders_empty_string(self) -> None:
        assert _fmt_toml(None) == '""'

    def test_bools_lowercase(self) -> None:
        assert _fmt_toml(True) == "true"
        assert _fmt_toml(False) == "false"

    def test_string_quoted(self) -> None:
        assert _fmt_toml("hello") == '"hello"'

    def test_path_quoted_as_string(self) -> None:
        assert _fmt_toml(Path("/tmp/x")) == '"/tmp/x"'

    def test_numbers_bare(self) -> None:
        assert _fmt_toml(7) == "7"
        assert _fmt_toml(3.5) == "3.5"

    def test_list_is_recursive(self) -> None:
        assert _fmt_toml([1, "x", True, None]) == '[1, "x", true, ""]'

    def test_tuple_renders_like_list(self) -> None:
        assert _fmt_toml((1, 2)) == "[1, 2]"


@pytest.mark.fast
class TestDictToToml:
    def test_scalars_get_prefixed_table_header(self) -> None:
        lines = _dict_to_toml({"a": 1, "b": "two"}, prefix="mod")
        assert lines[0] == "\n[mod]"
        assert "a = 1" in lines
        assert 'b = "two"' in lines

    def test_root_scalars_have_no_header(self) -> None:
        lines = _dict_to_toml({"a": 1})
        # No prefix => no leading "[...]" header line.
        assert lines == ["a = 1"]

    def test_nested_dict_becomes_dotted_subtable(self) -> None:
        lines = _dict_to_toml({"a": 1, "sub": {"b": 2}}, prefix="mod")
        assert "\n[mod]" in lines
        assert "\n[mod.sub]" in lines
        assert "b = 2" in lines

    def test_list_of_dicts_becomes_array_of_tables(self) -> None:
        lines = _dict_to_toml({"items": [{"x": 1}, {"x": 2}]}, prefix="mod")
        assert lines.count("\n[[mod.items]]") == 2
        assert "x = 1" in lines
        assert "x = 2" in lines

    def test_nested_dict_inside_array_item_is_skipped(self) -> None:
        # The serializer only emits scalar sub-keys for array-of-table items.
        lines = _dict_to_toml({"items": [{"x": 1, "deep": {"y": 9}}]}, prefix="mod")
        assert "x = 1" in lines
        assert not any("y = 9" in line for line in lines)

    def test_roundtrip_through_real_toml_parser(self) -> None:
        import tomllib

        data = {
            "name": "demo",
            "count": 3,
            "enabled": True,
            "sub": {"ratio": 0.5},
        }
        lines = _dict_to_toml(data, prefix="workspace")
        parsed = tomllib.loads("\n".join(lines))
        assert parsed == {
            "workspace": {
                "name": "demo",
                "count": 3,
                "enabled": True,
                "sub": {"ratio": 0.5},
            }
        }
