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
def test_a_profile_name_or_enum_resolves_to_the_profile(given, expected) -> None:
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
def test_the_profile_of_a_json_schema_node(node, expected) -> None:
    assert read_profile_from_schema(node) is expected


def test_the_exported_json_schema_carries_the_profile_of_each_field() -> None:
    props = _Aquifer.model_json_schema()["properties"]
    assert props["k"]["x-hmp-profile"] == "user"
    assert props["tol"]["x-hmp-profile"] == "dev"


def test_every_model_reachable_through_an_annotation_is_listed_once() -> None:
    annotation = _Aquifer | list[_Station] | dict[str, _Station] | None
    assert iter_basemodels(annotation) == [_Aquifer, _Station]
    assert iter_basemodels(int) == []


def test_a_self_referencing_model_does_not_loop() -> None:
    class _Node(HydroModelBase):
        label: Annotated[str, Field(json_schema_extra={"site_scoped": True})] = "n"
        child: _Node | None = None

    _Node.model_rebuild(_types_namespace={"_Node": _Node})
    assert site_scoped_paths(_Node) == ("label",)


def test_a_tuple_with_an_ellipsis_is_walked_through_its_item_model() -> None:
    class _Holder(HydroModelBase):
        items: tuple[_Station, ...] = ()

    assert site_scoped_paths(_Holder) == ("items[].code",)


_PAYLOAD: dict[str, Any] = {
    "name": "x",
    "pcg": 0.5,
    "aquifer": {"k": 1, "tol": 1e-3, "station": {"gain": 2}},
    "stations": [{"code": "a"}, {"gain": 3}],
}


def test_a_key_above_the_threshold_is_reported_with_its_path_and_level() -> None:
    found = collect_profile_violations(_Cfg, _PAYLOAD, Profile.USER)
    assert found == [
        (("aquifer", "tol"), Profile.DEV),
        (("aquifer", "station", "gain"), Profile.EXPERT),
        (("stations", "[1]", "gain"), Profile.EXPERT),
        (("pcg",), Profile.EXPERT),
    ]


def test_nothing_is_reported_when_the_threshold_allows_every_key() -> None:
    assert collect_profile_violations(_Cfg, _PAYLOAD, Profile.EXPERT) == []


def test_a_payload_that_is_not_a_mapping_has_no_violation() -> None:
    assert collect_profile_violations(_Cfg, ["pcg"], Profile.USER) == []


# Named tables: keys beyond the fields that name a plugin -------------------------


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


NAMED_CASES = (
    (_WithTables, True, ["kind", "engine"]),
    (_WithTables, False, ["kind", "engine", "plugin"]),
    (_Station, True, ["code", "gain"]),
)


INSTANCE_CASES = (
    (named_tables_of, _WithTables, {"engine": _Engine}),
    (named_tables_of, _Station, {}),
    (held_tables_of, _WithTables(), {"engine": _Engine(steps=8)}),
    (held_tables_of, _Station(), {}),
    (written_tables_of, _WithTables(), {}),
    (written_tables_of, _Station(), {}),
)


def test_a_raw_payload_is_checked_against_the_profile_of_its_named_tables() -> None:
    payload = {"plugin": {"gain": 2.0}}

    assert collect_profile_violations(_WithTables, payload, Profile.USER) == [
        (("plugin", "gain"), Profile.EXPERT)
    ]
