from __future__ import annotations

import textwrap
import tomllib
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

import hydromodpy.config
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.registry import (
    _section_shape,
    repeated_root_sections,
    root_scalar_fields,
    root_sections,
)
from hydromodpy.core.toml_io import generator
from hydromodpy.core.toml_io.error_locator import format_loc, format_validation_error, locate_loc
from hydromodpy.core.toml_io.generator import generate_toml, generate_toml_from_instances
from hydromodpy.core.toml_io.writer import dumps
from hydromodpy.results.exporters.export_spec import ExportRequest, load_export_requests
from hydromodpy.schema.changes import FIRST_EDITION


def test_dumps_round_trips_nested_tables_and_arrays() -> None:
    payload = {
        "base_config": r"C:\configs\base.toml",
        "workspace": {
            "root": r"C:\workspace",
            "flags": ["calibration", "snapshot"],
        },
        "simulation": {
            "run_id": "case_a",
            "enabled": True,
        },
        "simulation process": [
            {"kind": "flow", "solvers": ["modflow6"]},
            {"kind": "transport", "solvers": ["mt3dms"]},
        ],
    }

    rendered = dumps(payload)
    parsed = tomllib.loads(rendered)

    assert parsed["base_config"] == r"C:\configs\base.toml"
    assert parsed["workspace"]["root"] == r"C:\workspace"
    assert parsed["workspace"]["flags"] == ["calibration", "snapshot"]
    assert parsed["simulation"]["run_id"] == "case_a"
    assert parsed["simulation"]["enabled"] is True
    assert parsed["simulation process"][0]["kind"] == "flow"
    assert parsed["simulation process"][1]["solvers"] == ["mt3dms"]


def test_dumps_serializes_datetimes_and_inline_tables() -> None:
    payload = {
        "meta": {
            "created_at": datetime(2026, 4, 26, 21, 10, tzinfo=UTC),
            "limits": [{"min": 1.0, "max": 2.5}],
        }
    }

    rendered = dumps(payload)
    parsed = tomllib.loads(rendered)

    assert parsed["meta"]["created_at"] == datetime(2026, 4, 26, 21, 10, tzinfo=UTC)
    assert parsed["meta"]["limits"][0] == {"min": 1.0, "max": 2.5}


# A template has to show the tables a section is actually configured with.
#
# The calibration section is the case that made this visible: its three
# indispensable tables reached the reader as three dead comment lines, so a user
# starting from ``hmp config template`` could not tell that a staged calibration
# exists, let alone what a phase carries.


@pytest.fixture(scope="module")
def calibration_template() -> str:
    return generate_toml(modules=["calibration"], root=HydroModPyConfig)


def test_the_mapping_of_parameters_shows_one_entry(calibration_template: str) -> None:
    assert "# [calibration.parameters.<id>]" in calibration_template
    # The fields a parameter needs, not just the pointer line.
    assert "# bounds = " in calibration_template
    assert "# search_space = " in calibration_template


def test_the_mapping_of_outputs_lists_every_support(calibration_template: str) -> None:
    assert "# [calibration.outputs.<id>]" in calibration_template
    for support in ("point", "boundary", "cell", "lake", "network"):
        assert f'support = "{support}"' in calibration_template


def test_the_staged_table_shows_what_a_phase_carries(calibration_template: str) -> None:
    assert "# [[calibration.phases]]" in calibration_template
    for field in ("name", "method", "parameters", "depends_on", "freeze_on_success"):
        assert f"# {field} = " in calibration_template


def test_the_staged_table_stays_commented_out(calibration_template: str) -> None:
    # Writing this table is what switches the runner to staged mode, so a
    # template must not turn it on for a reader who only wanted a starting
    # point.
    assert "\n[[calibration.phases]]" not in calibration_template
    parsed = tomllib.loads(calibration_template)
    assert "phases" not in parsed["calibration"]


def test_the_whole_template_stays_parseable() -> None:
    # Every skeleton is commented, so adding them must not cost validity.
    parsed = tomllib.loads(generate_toml(root=HydroModPyConfig))

    assert "workflow" in parsed


# A template never writes a value the reload refuses in a section that is off.
#
# ``[geographic.crossings]`` is off by default, and its ``kinds`` reached the
# template as ``kinds = []``: a key the model fills by itself, labeled
# REQUIRED and given an empty placeholder that ``min_length=1`` refuses. A key
# filled by a ``default_factory`` is written with that value; a key that is
# really required, in a section whose ``enabled`` is false, is written
# commented with its form.


class _Probe(BaseModel):
    """Probe section."""

    model_config = ConfigDict(extra="forbid")

    enabled: Annotated[bool, Profile.USER] = Field(default=False, description="Switch.")
    target: Annotated[str, Profile.USER] = Field(description="Needed when enabled.")
    kinds: Annotated[list[str], Profile.USER] = Field(
        default_factory=lambda: ["road", "bridge"], min_length=1, description="Kinds."
    )


def test_a_factory_key_carries_its_value_and_a_required_key_stays_commented(monkeypatch) -> None:
    monkeypatch.setattr(generator, "root_sections", lambda _root=None: {"probe": _Probe})

    text = generate_toml(modules=["probe"], profile="user", root=HydroModPyConfig)

    assert 'kinds = ["road", "bridge"]' in text
    assert "kinds = []" not in text
    assert '# Type: list[str] | Default: ["road", "bridge"]' in text
    assert '# target = ""' in text
    assert "\ntarget =" not in text
    assert tomllib.loads(text)["probe"] == {"enabled": False, "kinds": ["road", "bridge"]}


def test_the_crossings_section_of_the_template_is_valid_as_written() -> None:
    from hydromodpy.catchment.preprocess.crossings_config import CrossingNotchConfig

    section = tomllib.loads(
        generate_toml(modules=["geographic"], profile="user", root=HydroModPyConfig)
    )["geographic"]

    assert section["crossings"]["kinds"] == ["road", "railway", "bridge"]
    CrossingNotchConfig.model_validate(section["crossings"])


# Map Pydantic ``ValidationError`` paths back to TOML source lines.


def test_format_loc_renders_dotted_path_with_indices() -> None:
    assert format_loc(("flow", "param_list", 0, "kind")) == "flow.param_list[0].kind"
    assert format_loc(()) == ""
    assert format_loc(("workspace",)) == "workspace"


def test_locate_loc_finds_assignment_under_section() -> None:
    text = textwrap.dedent(
        """\
        [workspace]

        [flow]
        flow_regime = "steady"
        param_list = ["K", "Sy"]
        """
    )
    line = locate_loc(text, ("flow", "param_list"))
    assert line is not None
    assert text.splitlines()[line - 1].startswith("param_list")


def test_locate_loc_falls_back_to_header_for_missing_key() -> None:
    text = textwrap.dedent(
        """\
        [flow]
        flow_regime = "steady"
        """
    )
    assert locate_loc(text, ("flow", "missing_field")) == 1


def test_locate_loc_returns_header_for_root_index() -> None:
    text = textwrap.dedent(
        """\
        [mesh.families]
        rivers = "cell"
        """
    )
    assert locate_loc(text, ("mesh", "families", "0", "kind")) == 1


def test_format_validation_error_includes_file_and_line(tmp_path: Path) -> None:
    class Inner(BaseModel):
        value: int

    class Outer(BaseModel):
        inner: Inner

    src = tmp_path / "config.toml"
    src.write_text(
        textwrap.dedent(
            """\
            [inner]
            value = "not-an-int"
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError) as excinfo:
        Outer.model_validate({"inner": {"value": "not-an-int"}})

    rendered = format_validation_error(excinfo.value, source_path=src)
    assert str(src) in rendered
    assert "inner.value" in rendered
    assert ":2:" in rendered  # the bad assignment is on line 2


# A root array of tables such as [[export]] is a section, not a scalar.


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
    assert root_sections(HydroModPyConfig)["export"] is ExportRequest
    assert "export" in repeated_root_sections(HydroModPyConfig)
    assert "export" not in root_scalar_fields(HydroModPyConfig)
    assert "display" not in repeated_root_sections(HydroModPyConfig)


def test_the_template_shows_one_commented_export_block() -> None:
    text = generate_toml(modules=["export"], profile="user", root=HydroModPyConfig)

    assert "export = []" not in text
    assert "REQUIRED\nexport" not in text
    assert "# Example entry, one [[export]] block per entry." in text
    assert "# [[export]]" in text
    assert "# variables = " in text
    # Every block is commented: an export is asked for, never on by default.
    # The edition is the one scalar of the root, so a template writes it.
    assert tomllib.loads(text) == {"edition": FIRST_EDITION}


def test_the_full_template_parses_and_carries_no_export() -> None:
    text = generate_toml(profile="user", root=HydroModPyConfig)

    assert "# [[export]]" in text
    assert "export" not in tomllib.loads(text)


def test_the_template_writes_each_given_export_as_a_block() -> None:
    requests = [{"variables": ["head"], "time": ["last"]}, {"variables": "discharge"}]
    text = generate_toml(
        modules=["export"], profile="user", overrides={"export": requests}, root=HydroModPyConfig
    )

    assert text.count("\n[[export]]\n") == 2
    parsed = tomllib.loads(text)
    assert parsed["export"] == requests
    loaded = load_export_requests(parsed["export"])
    assert [r.variables for r in loaded] == [["head"], "discharge"]


def test_a_config_written_from_instances_keeps_its_exports() -> None:
    requests = load_export_requests(
        [{"variables": ["head"], "time": ["last"], "format": "netcdf"}, {"variables": "all"}]
    )
    text = generate_toml_from_instances(
        {"export": requests}, exclude_none=True, root=HydroModPyConfig
    )

    parsed = tomllib.loads(text)
    reloaded = load_export_requests(parsed["export"])
    assert [r.model_dump() for r in reloaded] == [r.model_dump() for r in requests]


def test_a_config_written_from_instances_without_exports_has_no_block() -> None:
    text = generate_toml_from_instances({"export": []}, root=HydroModPyConfig)

    assert "[[export]]" not in text


def test_config_meta_marks_export_as_repeated() -> None:
    from hydromodpy.schema.config_schema import build_config_meta

    sections = {entry["name"]: entry for entry in build_config_meta(HydroModPyConfig)["sections"]}

    assert sections["export"]["repeated"] is True
    assert sections["export"]["ref"] == "#/$defs/ExportRequest"
    assert sections["display"]["repeated"] is False
