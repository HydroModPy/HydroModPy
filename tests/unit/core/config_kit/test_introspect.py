"""Reading profile, union and site-scoped metadata off small configuration models."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union

import pytest
from pydantic import BaseModel, Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.introspect import (
    DEFAULT_FIELD_PROFILE,
    collect_profile_violations,
    extract_profile,
    is_model,
    is_site_scoped,
    is_union_origin,
    iter_basemodels,
    iter_fields_by_profile,
    read_profile_from_schema,
    resolve_profile,
    site_scoped_paths,
    unwrap_members,
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


def test_a_field_without_a_tag_is_visible_to_the_user() -> None:
    assert extract_profile(_Cfg.model_fields["name"]) is DEFAULT_FIELD_PROFILE is Profile.USER
    assert extract_profile(_Cfg.model_fields["pcg"]) is Profile.EXPERT
    assert extract_profile(object()) is Profile.USER


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


@pytest.mark.parametrize("bad", ["guru", 3])
def test_an_unknown_profile_is_refused_with_the_allowed_names(bad) -> None:
    with pytest.raises(ValueError, match="Allowed values: user, dev, expert"):
        resolve_profile(bad)


@pytest.mark.parametrize(
    ("threshold", "visible"),
    [
        (Profile.USER, ["k", "station"]),
        (Profile.DEV, ["k", "tol", "station"]),
        (Profile.EXPERT, ["k", "tol", "station"]),
    ],
)
def test_fields_above_the_threshold_are_not_listed(threshold, visible) -> None:
    assert [name for name, _, _ in iter_fields_by_profile(_Aquifer, threshold)] == visible


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


def test_the_origin_of_both_union_spellings_is_a_union() -> None:
    from typing import get_origin

    assert is_union_origin(get_origin(Optional[int]))  # noqa: UP045
    assert is_union_origin(get_origin(int | None))
    assert not is_union_origin(get_origin(list[int]))
    assert not is_union_origin(None)


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        (_Cfg, True),
        (BaseModel, True),
        (int, False),
        (list[_Cfg], False),
        (None, False),
        ("x", False),
    ],
)
def test_a_model_class_is_told_from_anything_else(annotation, expected) -> None:
    assert is_model(annotation) is expected


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        (int, [int]),
        (int | None, [int]),
        (Optional[str], [str]),  # noqa: UP045
        (Annotated[int, "meta"], [int]),
        (Annotated[int | str | None, "m"], [int, str]),
        (Union[int, Annotated[float, "m"], None], [int, float]),  # noqa: UP007, UP045
        (type(None), []),
        (list[int], [list[int]]),
    ],
)
def test_members_of_an_annotation_have_annotated_and_none_removed(annotation, expected) -> None:
    assert unwrap_members(annotation) == expected


def test_every_model_reachable_through_an_annotation_is_listed_once() -> None:
    annotation = _Aquifer | list[_Station] | dict[str, _Station] | None
    assert iter_basemodels(annotation) == [_Aquifer, _Station]
    assert iter_basemodels(int) == []


def test_site_scoped_is_read_from_the_field_metadata() -> None:
    assert is_site_scoped(_Cfg.model_fields["name"])
    assert not is_site_scoped(_Cfg.model_fields["pcg"])
    assert not is_site_scoped(object())


def test_site_scoped_paths_follow_models_lists_tables_and_unions() -> None:
    assert site_scoped_paths(_Cfg) == (
        "aquifer.station.code",
        "by_id.*.code",
        "maybe.station.code",
        "name",
        "stations[].code",
    )


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


def test_a_literal_annotation_is_one_member() -> None:
    assert unwrap_members(Literal["a", "b"]) == [Literal["a", "b"]]
