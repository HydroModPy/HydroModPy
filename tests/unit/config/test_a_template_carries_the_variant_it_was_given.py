"""A generated TOML carries the union member the config holds, not the default one.

``generate_toml_from_instances`` walks a model class and fills it with the values
of an instance. For a discriminated union it used to walk the member the *field*
falls back to -- the ``default_factory`` type, or the first member of the union --
whatever member the instance actually held. The members declare different keys, so
the table came out of the wrong shape: what the value carried was dropped, and what
the value forbids was written from the other member's defaults.

``[domain.depth_model]`` set to ``flat_substratum`` is where it surfaced: the
generated file lost ``substratum_elevation`` and gained the ``thickness`` of
``constant_thickness``, which reload refuses outright. The other seven unions of
the config tree failed the same way but in silence, dropping a key instead of
adding a forbidden one.

Every case here sets a **non-default** value on a **non-default** member: a member
that only differs by its tag round-trips even through the wrong class.
"""

from __future__ import annotations

import tomllib
import types
import typing
from pathlib import Path
from typing import Any, get_args, get_origin

import pytest
from pydantic import BaseModel

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.toml_io.generator import generate_toml_from_instances
from hydromodpy.physics.flow.flow_param_config import FlowParam
from hydromodpy.physics.flow.initial_conditions import FlowICSpinupCyclic, FlowInitialConditions
from hydromodpy.physics.flow.sinks_sources.sfr import (
    FlowReachNetworkConfig,
    FlowReachWidthByOrder,
)
from hydromodpy.physics.flow.sinks_sources.wells import (
    FlowWellConfig,
    FlowWellLocationAbsoluteXY,
)
from hydromodpy.solver.base.solver_config import ModflowNwtBackend, SolverConfig
from hydromodpy.spatial.domain.depth_model_config import FlatSubstratumDepthModel
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.field.core._field_param_sections import FieldHeterogeneousSection
from hydromodpy.spatial.geographic.synthetic.config import (
    LinearTopography,
    SyntheticGeographicConfig,
)
from hydromodpy.spatial.mesh.config.main import MeshCatchmentConfig
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._domain_schema import ZoneMeshingDomainBBox

pytestmark = pytest.mark.fast


def _case(field: str, instance: BaseModel) -> tuple[str, str, BaseModel]:
    return (type(instance).__name__, field, instance)


CASES: tuple[tuple[str, str, BaseModel], ...] = (
    _case(
        "topography",
        SyntheticGeographicConfig(
            topography=LinearTopography(base_elevation=31.0, right_to_left_amplitude=12.5)
        ),
    ),
    _case(
        "depth_model",
        DomainConfig(depth_model=FlatSubstratumDepthModel(substratum_elevation=-78.0)),
    ),
    _case(
        "field",
        FlowParam(
            field=FieldHeterogeneousSection(
                id="K", unit="m/s", values={"zone_a": 1e-5}, field_spatial_id="zones"
            )
        ),
    ),
    _case("h", FlowInitialConditions(h=FlowICSpinupCyclic(max_cycles=4, tol_head=0.05))),
    _case(
        "location",
        FlowWellConfig(
            location=FlowWellLocationAbsoluteXY(x=351000.0, y=6789000.0, layer=1), flux=-0.004
        ),
    ),
    _case(
        "width",
        FlowReachNetworkConfig(
            stream_threshold_km2=0.5, width=FlowReachWidthByOrder(widths={1: 1.5, 3: 4.0})
        ),
    ),
    _case("backend", SolverConfig(backend=ModflowNwtBackend())),
    _case(
        "domain",
        MeshCatchmentConfig(
            constraints_mode="rivers_only",
            domain=ZoneMeshingDomainBBox(bbox=[0.0, 0.0, 1000.0, 1000.0]),
        ),
    ),
)


def _is_union(origin: Any) -> bool:
    return origin is typing.Union or origin is types.UnionType


def _discriminated_union_sites() -> set[tuple[str, str]]:
    """Return every ``(model, field)`` of the config tree holding a union of models.

    Only direct unions: a union nested under ``Optional[Annotated[...]]`` is
    rendered from the value itself and never goes through a member class.
    """
    sites: set[tuple[str, str]] = set()
    seen: set[type[BaseModel]] = set()

    def members(annotation: Any) -> list[type[BaseModel]]:
        return [a for a in get_args(annotation) if isinstance(a, type) and issubclass(a, BaseModel)]

    def walk(model_cls: type[BaseModel]) -> None:
        if model_cls in seen:
            return
        seen.add(model_cls)
        for name, field_info in model_cls.model_fields.items():
            annotation = field_info.annotation
            if _is_union(get_origin(annotation)) and len(members(annotation)) > 1:
                sites.add((model_cls.__name__, name))
            nested: list[type[BaseModel]] = []
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                nested.append(annotation)
            else:
                for arg in get_args(annotation):
                    if isinstance(arg, type) and issubclass(arg, BaseModel):
                        nested.append(arg)
                    else:
                        nested.extend(members(arg))
            for child in nested:
                walk(child)

    walk(HydroModPyConfig)
    return sites


@pytest.mark.parametrize(
    ("model_name", "field", "instance"),
    CASES,
    ids=[f"{model}.{field}" for model, field, _ in CASES],
)
def test_the_generated_table_reloads_into_the_same_variant(
    model_name: str, field: str, instance: BaseModel, tmp_path: Path
) -> None:
    destination = tmp_path / f"{model_name}_{field}.toml"

    generate_toml_from_instances(
        {"section": instance},
        output_path=destination,
        profile="expert",
        exclude_none=True,
    )
    reloaded = type(instance).model_validate(tomllib.loads(destination.read_text())["section"])

    assert reloaded.model_dump(mode="json", exclude_none=True) == instance.model_dump(
        mode="json", exclude_none=True
    )


@pytest.mark.parametrize(
    ("model_name", "field", "instance"),
    CASES,
    ids=[f"{model}.{field}" for model, field, _ in CASES],
)
def test_the_generated_table_names_the_variant_and_none_of_its_siblings(
    model_name: str, field: str, instance: BaseModel, tmp_path: Path
) -> None:
    """Reload refuses a sibling key only where the member forbids extras loudly.

    Elsewhere the wrong member drops a key instead, which the round-trip above
    catches. This one catches the other half at the source: what the table names.
    """
    destination = tmp_path / f"{model_name}_{field}.toml"
    generate_toml_from_instances(
        {"section": instance},
        output_path=destination,
        profile="expert",
        exclude_none=True,
    )
    section = tomllib.loads(destination.read_text())["section"]
    # A model declaring toml_flatten renders its single member at the section
    # itself, so the member's keys are the section's keys.
    written = section if getattr(type(instance), "toml_flatten", False) else section[field]

    held = getattr(instance, field)
    declared = type(instance).model_fields[field]
    siblings = [
        member
        for member in get_args(declared.annotation)
        if isinstance(member, type) and issubclass(member, BaseModel) and member is not type(held)
    ]
    sibling_only = {
        name
        for member in siblings
        for name in member.model_fields
        if name not in type(held).model_fields
    }

    assert set(written).isdisjoint(sibling_only)
    assert written[declared.discriminator] == getattr(held, declared.discriminator)


def test_every_discriminated_union_of_the_config_tree_has_a_case() -> None:
    """A union added later joins CASES, or this test names it."""
    covered = {(model_name, field) for model_name, field, _ in CASES}

    assert _discriminated_union_sites() == covered
