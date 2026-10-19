"""A frozen copy of a configuration keeps what it was given, not the defaults it took.

``written_payload`` writes the copy a run freezes. A default nobody gave stays
out, so a validator that reads ``model_fields_set`` answers on the copy as it
did on the file. Three things the copy cannot leave out: a value set below a
section the file never wrote, a field a validator derived from another, and the
tag a union reads its member by.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from hydromodpy.core.config_kit.written import written_payload


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


class _Step(BaseModel):
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
    def _a_bare_number_needs_a_unit(self) -> _Step:
        if self.unit is None:
            raise ValueError("value has no unit")
        return self


def test_a_field_a_validator_derived_is_kept() -> None:
    step = _Step.model_validate({"value": "7 days"})
    step.__pydantic_fields_set__.discard("unit")

    payload = written_payload(step)

    assert payload == {"value": 7.0, "unit": "days"}
    assert _Step.model_validate(payload) == step


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
