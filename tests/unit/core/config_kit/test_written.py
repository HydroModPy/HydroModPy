"""What a configuration was given, as opposed to the defaults it took."""

from __future__ import annotations

import logging
from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase, write_resolved
from hydromodpy.core.config_kit.written import (
    experimental_keys_line,
    log_experimental_keys,
    written_as_a_file,
    written_experimental_keys,
    written_fields,
    written_payload,
)


class _Mesh(HydroModelBase):
    nx: int = 10
    ny: int = 10


class _Solver(HydroModelBase):
    kind: Literal["cg"] = "cg"
    damping: Annotated[float, Field(json_schema_extra={"stability": "experimental"})] = 0.5


class _Other(HydroModelBase):
    kind: Literal["bicg"] = "bicg"


class _Step(HydroModelBase):
    value: str = "1 day"
    unit: str = "day"

    @model_validator(mode="after")
    def _derive_unit(self) -> _Step:
        if "value" in self.model_fields_set:
            write_resolved(self, "unit", self.value.split()[1])
        return self


class _Cfg(HydroModelBase):
    name: str = "run"
    mesh: _Mesh = _Mesh()
    solver: _Solver | _Other = Field(default_factory=_Solver)
    scheme: Annotated[str, Field(json_schema_extra={"experimental_values": ["fancy"]})] = "plain"
    steps: list[_Step] = []
    limits: dict[str, _Mesh] = {}
    note: str | None = None
    hidden: Annotated[int, Field(json_schema_extra={"toml_exclude": True})] = 3
    tags: list[str] = Field(default_factory=list)


def test_a_field_nobody_gave_is_not_written_but_a_union_tag_always_is() -> None:
    assert written_fields(_Cfg()) == ()
    assert written_fields(_Cfg(name="run")) == ("name",)
    assert written_fields(_Solver()) == ("kind",)


def test_a_value_that_departs_from_the_default_counts_as_written() -> None:
    cfg = _Cfg()
    object.__setattr__(cfg, "name", "other")
    assert "name" in written_fields(cfg)


def test_a_field_set_to_its_own_default_still_counts_as_given() -> None:
    assert "name" in written_fields(_Cfg(name="run"))


def test_the_payload_keeps_given_fields_at_every_depth() -> None:
    cfg = _Cfg(
        mesh=_Mesh(nx=4), solver=_Solver(), steps=[_Step(value="7 days")], limits={"a": _Mesh(ny=2)}
    )
    assert written_payload(cfg) == {
        "mesh": {"nx": 4},
        "solver": {"kind": "cg"},
        "steps": [{"value": "7 days", "unit": "days"}],
        "limits": {"a": {"ny": 2}},
    }


def test_the_payload_validates_back_into_a_model_with_the_same_fields_set() -> None:
    cfg = _Cfg(name="n", mesh=_Mesh(nx=4), solver=_Other(), steps=[_Step(value="7 days")])
    back = _Cfg.model_validate(written_payload(cfg))
    assert back == cfg
    assert back.model_fields_set == cfg.model_fields_set


def test_a_file_leaves_out_nulls_excluded_fields_and_empty_defaults() -> None:
    cfg = _Cfg(name="n", solver=_Solver(), note=None, hidden=5, tags=[], limits={})
    said = written_as_a_file(cfg)
    assert said == {"name": "n", "solver": {"kind": "cg"}}


def test_a_file_keeps_an_empty_table_over_a_default_of_none() -> None:
    class _Opt(HydroModelBase):
        mesh: _Mesh | None = None

    assert written_as_a_file(_Opt(mesh=_Mesh())) == {"mesh": {}}


def test_a_file_drops_the_none_inside_a_given_table_and_list() -> None:
    class _Holder(HydroModelBase):
        free: dict[str, int | None] = {}
        row: list[int | None] = []

    cfg = _Holder(free={"a": 1, "b": None}, row=[1, None])
    assert written_as_a_file(cfg) == {"free": {"a": 1}, "row": [1]}


def test_a_file_reads_alike_before_and_after_a_round_trip() -> None:
    cfg = _Cfg(name="n", solver=_Solver(), steps=[_Step(value="3 days")])
    assert written_as_a_file(_Cfg.model_validate(written_as_a_file(cfg))) == written_as_a_file(cfg)


def test_nothing_experimental_is_reported_for_defaults() -> None:
    assert written_experimental_keys(_Cfg()) == ()


def test_an_experimental_key_and_an_experimental_value_are_reported_by_path() -> None:
    cfg = _Cfg(scheme="fancy", solver=_Solver(damping=0.1), steps=[_Step(value="1 day")])
    assert written_experimental_keys(cfg) == ("solver.damping", 'scheme = "fancy"')


def test_an_experimental_key_inside_a_list_or_table_carries_its_index_or_name() -> None:
    class _Inner(HydroModelBase):
        flag: Annotated[bool, Field(json_schema_extra={"stability": "experimental"})] = False

    class _Outer(HydroModelBase):
        rows: list[_Inner] = []
        by_name: dict[str, _Inner] = {}

    cfg = _Outer(rows=[_Inner(), _Inner(flag=True)], by_name={"w": _Inner(flag=True)})
    assert written_experimental_keys(cfg) == ("rows[1].flag", "by_name.w.flag")


def test_the_line_lists_the_keys_and_the_log_says_it_once(caplog: pytest.LogCaptureFixture) -> None:
    cfg = _Cfg(solver=_Solver(damping=0.1))
    assert experimental_keys_line(["a", "b"]).endswith("minor release: a, b")
    with caplog.at_level(logging.INFO):
        log_experimental_keys(cfg)
        log_experimental_keys(_Cfg())
    messages = [r.getMessage() for r in caplog.records if "Experimental keys" in r.getMessage()]
    assert messages == [experimental_keys_line(["solver.damping"])]


# A frozen copy of a configuration keeps what it was given, not the defaults it took.
#
# ``written_payload`` writes the copy a run freezes. A default nobody gave stays
# out, so a validator that reads ``model_fields_set`` answers on the copy as it
# did on the file. Three things the copy cannot leave out: a value set below a
# section the file never wrote, a field a validator derived from another, and the
# tag a union reads its member by.


class _Leaf(BaseModel):
    model_config = ConfigDict(extra="forbid")

    depth: float = 1.0
    offset: float = 2.0


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")

    leaf: _Leaf = _Leaf()
    label: str = "x"


class _Root(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: _Section = _Section()
    name: str = "run"


def test_a_default_nobody_gave_is_left_out() -> None:
    root = _Root.model_validate({"section": {"leaf": {"depth": 3.0}}})

    payload = written_payload(root)

    assert payload == {"section": {"leaf": {"depth": 3.0}}}
    assert _Root.model_validate(payload).section.leaf.model_fields_set == {"depth"}


def test_a_default_the_file_wrote_is_kept() -> None:
    root = _Root.model_validate({"name": "run"})

    assert written_payload(root) == {"name": "run"}


def test_a_value_set_below_an_unwritten_section_is_kept() -> None:
    root = _Root()
    root.section.leaf.offset = 5.0

    assert written_payload(root) == {"section": {"leaf": {"offset": 5.0}}}


class _FrozenStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float = 1.0
    unit: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _split_an_inline_unit(cls, data: object) -> object:
        if isinstance(data, dict) and isinstance(data.get("value"), str):
            number, unit = str(data["value"]).split()
            return {**data, "value": float(number), "unit": unit}
        return data

    @model_validator(mode="after")
    def _a_bare_number_needs_a_unit(self) -> _FrozenStep:
        if self.unit is None:
            raise ValueError("value has no unit")
        return self


def test_a_field_a_validator_derived_is_kept() -> None:
    step = _FrozenStep.model_validate({"value": "7 days"})
    step.__pydantic_fields_set__.discard("unit")

    payload = written_payload(step)

    assert payload == {"value": 7.0, "unit": "days"}
    assert _FrozenStep.model_validate(payload) == step


def _with_metres(value: object) -> object:
    return f"{value} m" if isinstance(value, float) else value


class _Etp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface_offset: Annotated[str, BeforeValidator(_with_metres)] = Field(
        default=2.0, validate_default=True
    )
    extinction_depth: float = 1.0


def test_a_default_is_compared_as_its_field_validates_it() -> None:
    etp = _Etp.model_validate({"extinction_depth": 2.9})

    assert etp.surface_offset == "2.0 m"
    assert written_payload(etp) == {"extinction_depth": 2.9}


class _Homogeneous(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["homogeneous"] = "homogeneous"
    value: float = 0.0


class _Zonal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["zonal"] = "zonal"
    zones: int = 1


class _Parameter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: Annotated[_Homogeneous | _Zonal, Field(discriminator="kind")] = _Homogeneous()


def test_the_tag_of_a_union_member_is_kept() -> None:
    parameter = _Parameter(field=_Zonal(zones=3))

    payload = written_payload(parameter)

    assert payload == {"field": {"kind": "zonal", "zones": 3}}
    assert _Parameter.model_validate(payload) == parameter
