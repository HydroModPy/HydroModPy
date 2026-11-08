"""One parser of dotted key paths for --set, HMP_SET_*, bind and inline recipes."""

from __future__ import annotations

from typing import Annotated, Any

import pytest
from pydantic import BaseModel, Field

from hydromodpy.core.toml_io.error_locator import locate_loc
from hydromodpy.core.toml_io.paths import (
    DottedPath,
    UnknownPathError,
    assign,
    lookup,
    parse,
    resolve_field,
)


def test_a_bare_path_splits_on_dots() -> None:
    assert parse("geographic.catchment.x_outlet").parts == (
        "geographic",
        "catchment",
        "x_outlet",
    )


def test_a_quoted_part_keeps_its_dots_and_dashes() -> None:
    path = parse('sites.recipes."k2e-5".file')
    assert path.parts == ("sites", "recipes", "k2e-5", "file")
    assert parse("a.'x.y'.b").parts == ("a", "x.y", "b")
    assert parse('a."say \\"hi\\"".b').parts == ("a", 'say "hi"', "b")
    assert parse(' a . "b c" ').parts == ("a", "b c")


def test_a_path_renders_back_to_what_parse_reads() -> None:
    path = DottedPath(("sites", "recipes", "k2e-5", "a.b", "plain", "x y"))
    assert str(path) == 'sites.recipes."k2e-5"."a.b".plain."x y"'
    assert parse(str(path)) == path


@pytest.mark.parametrize("text", ["data.sources[0].path", "x[0]", "a.b[]"])
def test_an_index_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="no index"):
        parse(text)


def test_a_bracket_inside_quotes_is_a_key() -> None:
    assert parse('a."x[0]"').parts == ("a", "x[0]")


@pytest.mark.parametrize("text", ["", "a..b", ".a", "a.", 'a.""', "a b", "a.$b", 'a."open'])
def test_a_malformed_path_is_refused(text: str) -> None:
    with pytest.raises(ValueError):
        parse(text)


def test_assign_creates_the_nested_tables() -> None:
    payload: dict[str, Any] = {"flow": {"param": {"K": {"type": "homogeneous"}}}}
    assign(payload, "flow.param.K.field.value", 2e-5)
    assign(payload, parse('sites.recipes."k2e-5"'), "k.toml")
    assert payload["flow"]["param"]["K"] == {"type": "homogeneous", "field": {"value": 2e-5}}
    assert payload["sites"]["recipes"]["k2e-5"] == "k.toml"


def test_assign_refuses_to_turn_a_value_into_a_table() -> None:
    payload: dict[str, Any] = {"simulation": {"name": "x"}}
    with pytest.raises(ValueError, match="simulation.name holds a value"):
        assign(payload, "simulation.name.first", "y")


def test_lookup_reads_a_value_and_names_the_neighbours_of_a_miss() -> None:
    payload = {"geographic": {"catchment": {"x_outlet": 1.0, "y_outlet": 2.0}}}
    assert lookup(payload, "geographic.catchment.x_outlet") == 1.0
    with pytest.raises(KeyError, match="x_outlet"):
        lookup(payload, "geographic.catchment.x_outlt")


class _Leaf(BaseModel):
    value: float = 0.0
    unit: str = "m/s"


class _VariantA(BaseModel):
    kind: str = "a"
    alpha: int = 0


class _VariantB(BaseModel):
    kind: str = "b"
    beta: _Leaf = Field(default_factory=_Leaf)


class _Root(BaseModel):
    name: str = ""
    leaf: _Leaf | None = None
    variant: Annotated[_VariantA | _VariantB, Field(discriminator=None)] = Field(
        default_factory=_VariantA
    )
    params: dict[str, _Leaf] = Field(default_factory=dict)
    free: dict[str, Any] = Field(default_factory=dict)
    items: list[_Leaf] = Field(default_factory=list)


def test_resolve_field_walks_optional_models() -> None:
    assert resolve_field(_Root, "leaf.value").annotation is float


def test_resolve_field_picks_the_union_variant_that_declares_the_key() -> None:
    assert resolve_field(_Root, "variant.alpha").annotation is int
    assert resolve_field(_Root, "variant.beta.unit").annotation is str


def test_resolve_field_reads_a_table_key_as_a_key() -> None:
    assert resolve_field(_Root, "params.K.value").annotation is float
    assert resolve_field(_Root, 'params."k-2".unit').annotation is str


def test_a_free_table_ends_the_walk_at_its_own_field() -> None:
    assert resolve_field(_Root, "free.any.depth") is _Root.model_fields["free"]


def test_a_list_ends_the_walk() -> None:
    assert resolve_field(_Root, "items") is _Root.model_fields["items"]
    assert resolve_field(_Root, "items__merge") is _Root.model_fields["items"]
    with pytest.raises(UnknownPathError, match="items is a list"):
        resolve_field(_Root, "items.value")


def test_an_unknown_key_is_refused_with_its_neighbours() -> None:
    with pytest.raises(UnknownPathError, match="nearest: value"):
        resolve_field(_Root, "leaf.valeu")


def test_a_key_below_a_value_is_refused() -> None:
    with pytest.raises(UnknownPathError, match="name is a value"):
        resolve_field(_Root, "name.first")


def test_resolve_field_reaches_a_field_of_the_project_config() -> None:
    from hydromodpy.config import HydroModPyConfig

    field = resolve_field(HydroModPyConfig, "geographic.catchment.x_outlet")
    assert "outlet" in (field.description or "")
    with pytest.raises(UnknownPathError, match="sources is a list"):
        resolve_field(HydroModPyConfig, "data.hydrometry.sources.path")


def test_the_locator_finds_a_quoted_key() -> None:
    text = (
        "[sites.bind]\n"
        '"site.name" = "site"\n'
        "'geographic.catchment.x_outlet' = \"x_outlet\"\n"
        'plain = "p"\n'
    )
    assert locate_loc(text, ("sites", "bind", "site.name")) == 2
    assert locate_loc(text, ("sites", "bind", "geographic.catchment.x_outlet")) == 3
    assert locate_loc(text, ("sites", "bind", "plain")) == 4


SOLVER_TABLE_PATHS = (
    ("solver.modflow6.runtime.mf6_ims_complexity", "mf6_ims_complexity"),
    ("solver.modflow_nwt.runtime.upw.hdry", "hdry"),
    ("solver.boussinesq.max_iterations", "max_iterations"),
    ("solver.modflow6", None),
)


@pytest.mark.parametrize(("path", "leaf"), SOLVER_TABLE_PATHS)
def test_resolve_field_walks_the_settings_table_of_a_flow_solver(
    path: str, leaf: str | None
) -> None:
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.core.config_kit.introspect import fields_and_tables
    from hydromodpy.solver.base.solver_config import SolverConfig

    field = resolve_field(HydroModPyConfig, path)

    if leaf is None:
        assert field is fields_and_tables(SolverConfig)["modflow6"]
    else:
        assert field.annotation is not None


def test_a_solver_table_nothing_serves_is_refused_with_the_tables_served() -> None:
    from hydromodpy.config import HydroModPyConfig

    with pytest.raises(UnknownPathError, match="solver has no key 'modflow7'; nearest: modflow6"):
        resolve_field(HydroModPyConfig, "solver.modflow7.runtime")
