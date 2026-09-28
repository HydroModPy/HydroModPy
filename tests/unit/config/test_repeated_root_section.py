"""A root array of tables such as [[export]] is a section, not a scalar."""

from __future__ import annotations

import tomllib
from typing import Optional

from pydantic import BaseModel

import hydromodpy.config  # noqa: F401  (installs the root config provider)
from hydromodpy.core.config_kit.export_spec import ExportRequest, load_export_requests
from hydromodpy.core.config_kit.registry import (
    _section_shape,
    repeated_root_sections,
    root_scalar_fields,
    root_sections,
)
from hydromodpy.core.toml_io.generator import generate_toml, generate_toml_from_instances


class _Item(BaseModel):
    name: str


def test_section_shape_tells_a_table_from_an_array_of_tables() -> None:
    assert _section_shape(_Item) == (_Item, False)
    assert _section_shape(Optional[_Item]) == (_Item, False)  # noqa: UP045
    assert _section_shape(list[_Item]) == (_Item, True)
    assert _section_shape(tuple[_Item, ...]) == (_Item, True)
    assert _section_shape(list[_Item] | None) == (_Item, True)


def test_section_shape_leaves_scalars_and_records_alone() -> None:
    assert _section_shape(str) is None
    assert _section_shape(list[str]) is None
    assert _section_shape(tuple[_Item, _Item]) is None
    assert _section_shape(dict[str, _Item]) is None


def test_export_is_a_repeated_root_section() -> None:
    assert root_sections()["export"] is ExportRequest
    assert "export" in repeated_root_sections()
    assert "export" not in root_scalar_fields()
    assert "display" not in repeated_root_sections()


def test_the_template_shows_one_commented_export_block() -> None:
    text = generate_toml(modules=["export"], profile="user")

    assert "export = []" not in text
    assert "REQUIRED\nexport" not in text
    assert "# Example entry, one [[export]] block per entry." in text
    assert "# [[export]]" in text
    assert "# variables = " in text
    # Every block is commented: an export is asked for, never on by default.
    assert tomllib.loads(text) == {}


def test_the_full_template_parses_and_carries_no_export() -> None:
    text = generate_toml(profile="user")

    assert "# [[export]]" in text
    assert "export" not in tomllib.loads(text)


def test_the_template_writes_each_given_export_as_a_block() -> None:
    requests = [{"variables": ["head"], "time": ["last"]}, {"variables": "discharge"}]
    text = generate_toml(modules=["export"], profile="user", overrides={"export": requests})

    assert text.count("\n[[export]]\n") == 2
    parsed = tomllib.loads(text)
    assert parsed["export"] == requests
    loaded = load_export_requests(parsed["export"])
    assert [r.variables for r in loaded] == [["head"], "discharge"]


def test_a_config_written_from_instances_keeps_its_exports() -> None:
    requests = load_export_requests(
        [{"variables": ["head"], "time": ["last"], "format": "netcdf"}, {"variables": "all"}]
    )
    text = generate_toml_from_instances({"export": requests}, exclude_none=True)

    parsed = tomllib.loads(text)
    reloaded = load_export_requests(parsed["export"])
    assert [r.model_dump() for r in reloaded] == [r.model_dump() for r in requests]


def test_a_config_written_from_instances_without_exports_has_no_block() -> None:
    text = generate_toml_from_instances({"export": []})

    assert "[[export]]" not in text


def test_config_meta_marks_export_as_repeated() -> None:
    from hydromodpy.schema.export import build_config_meta

    sections = {entry["name"]: entry for entry in build_config_meta()["sections"]}

    assert sections["export"]["repeated"] is True
    assert sections["export"]["ref"] == "#/$defs/ExportRequest"
    assert sections["display"]["repeated"] is False
