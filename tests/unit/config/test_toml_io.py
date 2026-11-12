from __future__ import annotations

import textwrap
import tomllib
from datetime import timezone
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

import hydromodpy.config
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.toml_io.error_locator import locate_loc
from hydromodpy.core.toml_io.generator import generate_toml, generate_toml_from_instances
from hydromodpy.results.exporters.export_spec import load_export_requests

# A template has to show the tables a section is actually configured with.
#
# The calibration section is the case that made this visible: its three
# indispensable tables reached the reader as three dead comment lines, so a user
# starting from ``hmp config template`` could not tell that a staged calibration
# exists, let alone what a phase carries.


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


# Map Pydantic ``ValidationError`` paths back to TOML source lines.


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


# A root array of tables such as [[export]] is a section, not a scalar.


class _Item(BaseModel):
    name: str


def test_the_full_template_parses_and_carries_no_export() -> None:
    text = generate_toml(profile="user", root=HydroModPyConfig)

    assert "# [[export]]" in text
    assert "export" not in tomllib.loads(text)


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
