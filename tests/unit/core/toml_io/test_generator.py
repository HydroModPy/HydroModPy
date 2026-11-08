"""The commented TOML template written from small hand-made models."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Annotated, Literal

import pytest
from pydantic import Field, SerializerFunctionWrapHandler, model_serializer

from hydromodpy.core.config_kit import registry
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.toml_io import generator
from hydromodpy.core.toml_io.generator import (
    available_modules,
    generate_toml,
    generate_toml_from_instances,
)


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


class _Provider:
    def root_model(self) -> type[HydroModelBase]:
        return _Root


@pytest.fixture(autouse=True)
def _fake_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "get_root_config_provider", lambda: _Provider())
    monkeypatch.setattr(registry, "_CACHE", None)
    monkeypatch.setattr(registry, "_REPEATED_CACHE", None)
    monkeypatch.setattr(registry, "_SCALAR_CACHE", None)
    monkeypatch.setattr(
        generator, "get_dynamic_flow_examples_provider", lambda: None, raising=False
    )


def test_the_modules_are_the_sections_of_the_root_model() -> None:
    assert available_modules() == ["flow", "export"]


def test_an_unknown_module_is_refused_with_the_available_ones() -> None:
    with pytest.raises(ValueError, match=r"Unknown module\(s\): nope. Available: export, flow"):
        generate_toml(modules=["nope"])


@pytest.mark.parametrize(
    ("profile", "tol", "pcg"),
    [("user", False, False), ("dev", True, False), ("expert", True, True)],
)
def test_a_profile_decides_which_keys_the_template_mentions(profile, tol, pcg) -> None:
    text = generate_toml(modules=["flow"], profile=profile)
    assert "[flow]" in text
    assert "Hydraulic conductivity in m/s." in text
    assert ("tol" in text) is tol
    assert ("pcg" in text) is pcg


def test_the_template_with_overrides_is_valid_toml_that_holds_the_given_values() -> None:
    text = generate_toml(modules=["flow"], profile="user", overrides={"flow": {"k": 3e-4}})
    assert tomllib.loads(text)["flow"]["k"] == 3e-4


def test_the_template_is_written_to_the_path_when_one_is_given(tmp_path: Path) -> None:
    target = tmp_path / "t.toml"
    text = generate_toml(target, modules=["flow"], profile="user")
    assert target.read_text(encoding="utf-8") == text


def test_instances_give_a_filled_document_that_reads_back_to_the_same_values(tmp_path) -> None:
    flow = _Flow(k=2e-3, mode="transient")
    exports = [_Export(fmt="nc"), _Export(fmt="csv")]
    text = generate_toml_from_instances(
        {"flow": flow, "export": exports}, tmp_path / "c.toml", profile="expert", comment="Mine"
    )
    loaded = tomllib.loads(text)
    assert "# Mine" in text
    assert _Flow.model_validate(loaded["flow"]) == flow
    assert [e["fmt"] for e in loaded["export"]] == ["nc", "csv"]


def test_exclude_defaults_leaves_out_what_nobody_gave() -> None:
    text = generate_toml_from_instances(
        {"flow": _Flow(k=2e-3)}, profile="expert", exclude_defaults=True, exclude_none=True
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


class _TablesProvider:
    def root_model(self) -> type[HydroModelBase]:
        return _RootWithTables


def test_a_template_shows_each_named_table_and_an_instance_only_those_it_holds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(registry, "get_root_config_provider", lambda: _TablesProvider())
    monkeypatch.setattr(registry, "_CACHE", None)

    template = tomllib.loads(generate_toml(modules=["solver"], profile="user"))
    destination = tmp_path / "filled.toml"
    generate_toml_from_instances(
        {"solver": _Section()}, output_path=destination, profile="user", exclude_none=True
    )
    filled = tomllib.loads(destination.read_text())

    assert template["solver"]["a"] == {"steps": 4}
    assert template["solver"]["b"] == {"steps": 4}
    assert set(filled["solver"]) == {"backend", "a"}
    assert filled["solver"]["a"] == {"steps": 9}
