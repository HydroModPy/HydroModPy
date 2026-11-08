"""The commented TOML template written from small hand-made models."""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal

import pytest
from pydantic import Field, SerializerFunctionWrapHandler, model_serializer

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.registry import repeated_root_sections, root_sections
from hydromodpy.core.toml_io.generator import (
    available_modules,
    generate_toml,
    generate_toml_from_instances,
)
from hydromodpy.core.toml_io.section import repeated_root_section, section


class _Flow(HydroModelBase):
    k: float = Field(default=1e-5, ge=0, description="Hydraulic conductivity in m/s.")
    mode: Literal["steady", "transient"] = "steady"
    tol: Annotated[float, Profile.DEV] = 1e-6
    pcg: Annotated[float, Profile.EXPERT] = 0.97


class _Export(HydroModelBase):
    fmt: str = "csv"


class _Root(HydroModelBase):
    workflow: Literal["a", "b"] = "a"
    flow: _Flow = _Flow()
    export: list[_Export] = []


def test_the_modules_are_the_sections_of_the_root_model() -> None:
    assert available_modules(_Root) == ["flow", "export"]


def test_the_registry_functions_take_the_class_or_its_root_config() -> None:
    from hydromodpy.core.config_kit.root import RootConfig

    def _nothing(_layers: Any) -> list[str]:
        return []

    root = RootConfig(model=_Root, migrate_layers=_nothing, migrate_merged=_nothing)
    assert root_sections(_Root) == root_sections(root)
    assert repeated_root_sections(_Root) == repeated_root_sections(root) == {"export"}


def test_an_unknown_module_is_refused_with_the_available_ones() -> None:
    with pytest.raises(ValueError, match=r"Unknown module\(s\): nope. Available: export, flow"):
        generate_toml(modules=["nope"], root=_Root)


@pytest.mark.parametrize(
    ("profile", "tol", "pcg"),
    [("user", False, False), ("dev", True, False), ("expert", True, True)],
)
def test_a_profile_decides_which_keys_the_template_mentions(profile, tol, pcg) -> None:
    text = generate_toml(modules=["flow"], profile=profile, root=_Root)
    assert "[flow]" in text
    assert "Hydraulic conductivity in m/s." in text
    assert ("tol" in text) is tol
    assert ("pcg" in text) is pcg


def test_the_template_with_overrides_is_valid_toml_that_holds_the_given_values() -> None:
    text = generate_toml(
        modules=["flow"], profile="user", overrides={"flow": {"k": 3e-4}}, root=_Root
    )
    assert tomllib.loads(text)["flow"]["k"] == 3e-4


def test_the_template_is_written_to_the_path_when_one_is_given(tmp_path: Path) -> None:
    target = tmp_path / "t.toml"
    text = generate_toml(target, modules=["flow"], profile="user", root=_Root)
    assert target.read_text(encoding="utf-8") == text


def test_without_flow_examples_the_template_has_no_dynamic_block() -> None:
    text = generate_toml(modules=["flow"], profile="user", root=_Root)
    text = tomllib.loads(text)  # a plain valid TOML, no prose key of the examples
    assert set(text) == {"workflow", "flow"}


def test_flow_examples_receives_the_threshold_and_the_renderer() -> None:
    seen: dict[str, Any] = {}

    def examples(threshold: int, section_renderer: Callable[..., list[str]]) -> list[str]:
        seen["threshold"] = threshold
        seen["renderer"] = section_renderer
        return ["# rendered example block"]

    text = generate_toml(modules=["flow"], profile="dev", root=_Root, flow_examples=examples)
    assert seen["threshold"] == Profile.DEV
    assert seen["renderer"] is section
    assert "# rendered example block" in text
    assert text.index("[flow]") < text.index("# rendered example block")


def test_instances_give_a_filled_document_that_reads_back_to_the_same_values(tmp_path) -> None:
    flow = _Flow(k=2e-3, mode="transient")
    exports = [_Export(fmt="nc"), _Export(fmt="csv")]
    text = generate_toml_from_instances(
        {"flow": flow, "export": exports},
        tmp_path / "c.toml",
        profile="expert",
        comment="Mine",
        root=_Root,
    )
    loaded = tomllib.loads(text)
    assert "# Mine" in text
    assert _Flow.model_validate(loaded["flow"]) == flow
    assert [e["fmt"] for e in loaded["export"]] == ["nc", "csv"]


def test_exclude_defaults_leaves_out_what_nobody_gave() -> None:
    text = generate_toml_from_instances(
        {"flow": _Flow(k=2e-3)},
        profile="expert",
        exclude_defaults=True,
        exclude_none=True,
        root=_Root,
    )
    flow = tomllib.loads(text)["flow"]
    assert flow == {"k": 2e-3}


class _Engine(HydroModelBase):
    """Settings of one engine."""

    steps: int = 4


class _Section(HydroModelBase):
    backend: str = "a"

    @classmethod
    def named_tables(cls, *, shipped_only: bool) -> dict[str, type[HydroModelBase]]:
        return {"a": _Engine, "b": _Engine}

    def held_tables(self) -> dict[str, _Engine]:
        return {"a": _Engine(steps=9)}

    @model_serializer(mode="wrap")
    def _write_the_tables(self, handler: SerializerFunctionWrapHandler) -> dict:
        dumped = handler(self)
        dumped.update({name: table.model_dump() for name, table in self.held_tables().items()})
        return dumped


class _RootWithTables(HydroModelBase):
    solver: _Section = _Section()


def test_a_template_shows_each_named_table_and_an_instance_only_those_it_holds(
    tmp_path: Path,
) -> None:
    template = tomllib.loads(
        generate_toml(modules=["solver"], profile="user", root=_RootWithTables)
    )
    destination = tmp_path / "filled.toml"
    generate_toml_from_instances(
        {"solver": _Section()},
        output_path=destination,
        profile="user",
        exclude_none=True,
        root=_RootWithTables,
    )
    filled = tomllib.loads(destination.read_text())

    assert template["solver"]["a"] == {"steps": 4}
    assert template["solver"]["b"] == {"steps": 4}
    assert set(filled["solver"]) == {"backend", "a"}
    assert filled["solver"]["a"] == {"steps": 9}


def test_a_field_description_of_a_repeated_section_is_read_from_the_root() -> None:
    class _Described(HydroModelBase):
        fmt: str = "csv"

    class _RootDescribed(HydroModelBase):
        """Root."""

        export: list[_Described] = Field(default=[], description="Where the files go.")

    lines = repeated_root_section("export", _Described, 0, root=_RootDescribed)
    assert any("Where the files go." in line for line in lines)
