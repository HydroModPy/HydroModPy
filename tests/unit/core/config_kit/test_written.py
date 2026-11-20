"""What a configuration was given, as opposed to the defaults it took.

``written_payload`` writes the copy a run freezes. A default nobody gave stays out,
so a validator that reads ``model_fields_set`` answers on the copy as it did on the file.
"""

from __future__ import annotations

from typing import Annotated, Literal

import pytest
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
)

from hydromodpy.core.config_kit.base import HydroModelBase
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


TABLE_READERS = [
    pytest.param(written_payload, id="payload"),
    pytest.param(written_as_a_file, id="file"),
]


@pytest.mark.parametrize("reader", TABLE_READERS)
def test_written_tables_only(reader) -> None:
    # The "mesh" table is held but never written, so it stays out.
    assert reader(_Held()) == {"cg": {"kind": "cg", "damping": 0.7}}


class _Derived(BaseModel):
    """A field whose default factory reads the data validated before it."""

    model_config = ConfigDict(extra="forbid")

    nx: int = 10
    ny: int = Field(default_factory=lambda data: data["nx"] * 2)
    label: str = "a"


DERIVED = [
    pytest.param({}, {}, id="nothing given"),
    pytest.param({"nx": 4}, {"nx": 4}, id="only nx"),
    pytest.param({"nx": 4, "ny": 8}, {"nx": 4, "ny": 8}, id="ny equals its default"),
    pytest.param({"nx": 4, "ny": 9}, {"nx": 4, "ny": 9}, id="ny differs"),
    pytest.param({"ny": 20}, {"ny": 20}, id="only ny"),
]


@pytest.mark.parametrize(("given", "expected"), DERIVED)
def test_default_built_from_data(given, expected) -> None:
    assert written_payload(_Derived.model_validate(given)) == expected


def test_default_cached() -> None:
    _validated_default.cache_clear()
    for _ in range(3):
        assert written_payload(_Mesh()) == {}
    info = _validated_default.cache_info()
    assert (info.misses, info.hits) == (2, 4)
    assert _validated_default(_Mesh, "nx")[0] == 10


def test_unbuildable_default_is_given() -> None:
    def broken() -> int:
        raise RuntimeError("no default")

    class _Broken(BaseModel):
        count: int = Field(default_factory=broken)

    model = _Broken.model_construct(_fields_set=set(), count=1)
    assert written_fields(model) == ("count",)
