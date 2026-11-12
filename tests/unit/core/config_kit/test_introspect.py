"""Reading profile, union and site-scoped metadata off small configuration models."""

from __future__ import annotations

from typing import Annotated, Any

import pytest
from pydantic import BaseModel, Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.introspect import (
    collect_profile_violations,
    held_tables_of,
    iter_basemodels,
    named_tables_of,
    read_profile_from_schema,
    resolve_profile,
    site_scoped_paths,
    written_tables_of,
)
from hydromodpy.core.config_kit.profile import Profile


class _Station(HydroModelBase):
    code: Annotated[str, Field(json_schema_extra={"site_scoped": True})] = "s"
    gain: Annotated[float, Profile.EXPERT] = 1.0


class _Aquifer(HydroModelBase):
    k: float = 1.0
    tol: Annotated[float, Profile.DEV] = 1e-6
    station: _Station = _Station()


class _Cfg(HydroModelBase):
    name: Annotated[str, Field(json_schema_extra={"site_scoped": True})] = "x"
    aquifer: _Aquifer = _Aquifer()
    stations: list[_Station] = []
    by_id: dict[str, _Station] = {}
    maybe: _Aquifer | None = None
    pcg: Annotated[float, Profile.EXPERT] = 0.9


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("user", Profile.USER),
        ("DEV", Profile.DEV),
        ("expert", Profile.EXPERT),
        (Profile.DEV, Profile.DEV),
    ],
)
def test_resolve_profile(given, expected) -> None:
    assert resolve_profile(given) is expected


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        ({"x-hmp-profile": "dev"}, Profile.DEV),
        ({"x-hmp-profile": "nope"}, None),
        ({"x-hmp-profile": 3}, None),
        ({}, None),
    ],
)
def test_profile_of_schema_node(node, expected) -> None:
    assert read_profile_from_schema(node) is expected


def test_schema_carries_profile() -> None:
    props = _Aquifer.model_json_schema()["properties"]
    assert props["k"]["x-hmp-profile"] == "user"
    assert props["tol"]["x-hmp-profile"] == "dev"


def test_models_in_annotation() -> None:
    annotation = _Aquifer | list[_Station] | dict[str, _Station] | None
    assert iter_basemodels(annotation) == [_Aquifer, _Station]
    assert iter_basemodels(int) == []


def test_self_referencing_model() -> None:
    class _Node(HydroModelBase):
        label: Annotated[str, Field(json_schema_extra={"site_scoped": True})] = "n"
        child: _Node | None = None

    _Node.model_rebuild(_types_namespace={"_Node": _Node})
    assert site_scoped_paths(_Node) == ("label",)


def test_variadic_tuple_walked() -> None:
    class _Holder(HydroModelBase):
        items: tuple[_Station, ...] = ()

    assert site_scoped_paths(_Holder) == ("items[].code",)


_PAYLOAD: dict[str, Any] = {
    "name": "x",
    "pcg": 0.5,
    "aquifer": {"k": 1, "tol": 1e-3, "station": {"gain": 2}},
    "stations": [{"code": "a"}, {"gain": 3}],
}


def test_profile_violations() -> None:
    found = collect_profile_violations(_Cfg, _PAYLOAD, Profile.USER)
    assert found == [
        (("aquifer", "tol"), Profile.DEV),
        (("aquifer", "station", "gain"), Profile.EXPERT),
        (("stations", "[1]", "gain"), Profile.EXPERT),
        (("pcg",), Profile.EXPERT),
    ]


def test_no_violation_at_expert() -> None:
    assert collect_profile_violations(_Cfg, _PAYLOAD, Profile.EXPERT) == []


def test_non_mapping_payload() -> None:
    assert collect_profile_violations(_Cfg, ["pcg"], Profile.USER) == []


class _Engine(HydroModelBase):
    """Settings of the engine.

    A second paragraph the field does not carry.
    """

    steps: int = 4


class _WithTables(HydroModelBase):
    kind: str = "engine"

    @classmethod
    def named_tables(cls, *, shipped_only: bool) -> dict[str, type[BaseModel]]:
        return {"engine": _Engine} if shipped_only else {"engine": _Engine, "plugin": _Station}

    def held_tables(self) -> dict[str, BaseModel]:
        return {"engine": _Engine(steps=8)}

    def written_tables(self) -> dict[str, BaseModel]:
        return {}


def test_named_table_violations() -> None:
    payload = {"plugin": {"gain": 2.0}}

    assert collect_profile_violations(_WithTables, payload, Profile.USER) == [
        (("plugin", "gain"), Profile.EXPERT)
    ]
