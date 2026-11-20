"""The commented TOML template written from small hand-made models, or from filled instances.

A filled instance reads back to the same values. A mapping inside an array-of-tables entry
(the overrides of a calibration phase) is written as TOML and not as a Python repr.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Annotated, Literal

import pytest
from pydantic import Field, SerializerFunctionWrapHandler, model_serializer

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.toml_io.generator import generate_toml, generate_toml_from_instances


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


def test_an_unknown_module_is_refused() -> None:
    with pytest.raises(ValueError, match=r"Unknown module\(s\): nope. Available: export, flow"):
        generate_toml(modules=["nope"], root=_Root)


def test_instances_round_trip(tmp_path) -> None:
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


def test_exclude_defaults() -> None:
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


def test_template_and_instance_tables(tmp_path: Path) -> None:
    # A template shows each named table, an instance only the ones it holds.
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


_STAGED = {
    "parameters": {
        "K": {"bounds": [1e-8, 1e-2], "search_space": "log"},
        "Sy": {"bounds": [1e-4, 0.5], "search_space": "log"},
    },
    "phases": [
        {
            "name": "steady_conductivity",
            "method": "bisection",
            "parameters": ["K"],
            "variable": "discharge",
            "objective": "nse",
            "method_options": {"sweep_points": 7},
            "overrides": {
                "flow.flow_regime": "steady",
                "simulation.time.start_datetime": "2000-01-01T00:00:00",
                "simulation.time.step_value": 1096,
            },
        },
        {
            "name": "transient_storage",
            "method": "scipy_nelder_mead",
            "parameters": ["Sy"],
            "variable": "discharge",
            "objective": "nse_log",
            "depends_on": "steady_conductivity",
            "method_options": {},
            "overrides": {"flow.flow_regime": "transient"},
        },
    ],
}


@pytest.fixture
def written(tmp_path: Path) -> dict:
    config = CalibrationConfig.model_validate(_STAGED)
    destination = tmp_path / "staged.toml"
    generate_toml_from_instances(
        {"calibration": config},
        output_path=destination,
        profile="expert",
        exclude_none=True,
        root=CalibrationConfig,
    )
    return tomllib.loads(destination.read_text())["calibration"]


@pytest.mark.fast
def test_empty_mapping_table(written: dict) -> None:
    assert written["phases"][1]["method_options"] == {}


@pytest.mark.fast
def test_none_is_commented_out(tmp_path: Path) -> None:
    # exclude_none defaults to False. "precision = " is not a TOML line, so the key
    # is written commented out and reload restores the None it defaults to.
    config = CalibrationConfig.model_validate(_STAGED)
    destination = tmp_path / "with_nones.toml"

    generate_toml_from_instances(
        {"calibration": config},
        output_path=destination,
        profile="expert",
        root=CalibrationConfig,
    )
    reloaded = CalibrationConfig.model_validate(
        tomllib.loads(destination.read_text())["calibration"]
    )

    assert reloaded.phases[0].precision is None
    assert reloaded.model_dump(mode="json", exclude_none=True) == config.model_dump(
        mode="json", exclude_none=True
    )
