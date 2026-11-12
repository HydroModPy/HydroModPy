"""What a configuration was given, as opposed to the defaults it took."""

from __future__ import annotations

from typing import Annotated, Literal

import pytest
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from hydromodpy.core.config_kit.base import HydroModelBase, write_resolved
from hydromodpy.core.config_kit.written import (
    _validated_default,
    written_as_a_file,
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


def _with_metres(value: object) -> object:
    return f"{value} m" if isinstance(value, float) else value


class _Etp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface_offset: Annotated[str, BeforeValidator(_with_metres)] = Field(
        default=2.0, validate_default=True
    )
    extinction_depth: float = 1.0


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


# Named tables: a table is said when it was written, flat under its name -----------


class _Held(HydroModelBase):
    """A section that holds two named tables, of which it wrote one."""

    name: str = "x"

    def held_tables(self) -> dict[str, BaseModel]:
        return {"cg": _Solver(damping=0.7), "mesh": _Mesh()}

    def written_tables(self) -> dict[str, BaseModel]:
        return {"cg": self.held_tables()["cg"]}

    @model_serializer(mode="wrap")
    def _write_the_tables(self, handler: SerializerFunctionWrapHandler) -> dict:
        dumped = handler(self)
        dumped.update({key: table.model_dump() for key, table in self.held_tables().items()})
        return dumped


TABLE_READERS = (
    (written_payload, {"cg": {"kind": "cg", "damping": 0.7}}),
    (written_as_a_file, {"cg": {"kind": "cg", "damping": 0.7}}),
)


@pytest.mark.parametrize(("reader", "expected"), TABLE_READERS)
def test_a_written_table_is_said_and_a_held_default_is_not(reader, expected) -> None:
    assert reader(_Held()) == expected


class _Derived(BaseModel):
    """A field whose default factory reads the data validated before it."""

    model_config = ConfigDict(extra="forbid")

    nx: int = 10
    ny: int = Field(default_factory=lambda data: data["nx"] * 2)
    label: str = "a"


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ({}, {}),
        ({"nx": 4}, {"nx": 4}),
        ({"nx": 4, "ny": 8}, {"nx": 4, "ny": 8}),
        ({"nx": 4, "ny": 9}, {"nx": 4, "ny": 9}),
        ({"ny": 20}, {"ny": 20}),
    ],
)
def test_a_default_that_reads_the_data_is_built_for_each_model(given, expected) -> None:
    assert written_payload(_Derived.model_validate(given)) == expected


def test_a_default_that_reads_no_data_is_looked_up_once_per_field() -> None:
    _validated_default.cache_clear()
    for _ in range(3):
        assert written_payload(_Mesh()) == {}
    info = _validated_default.cache_info()
    assert (info.misses, info.hits) == (2, 4)
    assert _validated_default(_Mesh, "nx")[0] == 10


def test_a_default_that_cannot_be_built_counts_as_departed() -> None:
    def broken() -> int:
        raise RuntimeError("no default")

    class _Broken(BaseModel):
        count: int = Field(default_factory=broken)

    model = _Broken.model_construct(_fields_set=set(), count=1)
    assert written_fields(model) == ("count",)
