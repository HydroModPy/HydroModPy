from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError

from hydromodpy.config import HydroModPyConfig
from hydromodpy.physics.flow.boundary_conditions import DirichletBC, DrainBC
from hydromodpy.physics.flow.flow_config import FlowConfig, FlowParam
from hydromodpy.physics.flow.sinks_sources import (
    FlowBarrierConfig,
    FlowLakeConfig,
    FlowSinksSourcesConfig,
)
from hydromodpy.physics.flow.structure_binders import _lake_payloads_as_mappings

# Native Pydantic payload tests for flow parameters.


def test_flow_param_native_round_trip_all_sections() -> None:
    cfg = FlowConfig.model_validate(
        {
            "param": {
                "K": {
                    "field": {
                        "kind": "heterogeneous",
                        "unit": "m/s",
                        "values": {
                            "sand": "1e-4 m/s",
                            "clay": "1e-7 m/s",
                        },
                        "field_spatial_id": "geology",
                    },
                    "field_vertical_profile": {
                        "kind": "exponential",
                        "characteristic_depth": 20.0,
                    },
                },
                "Sy": {
                    "field": {
                        "kind": "homogeneous",
                        "unit": "-",
                        "value": 0.2,
                    },
                },
            }
        }
    )

    assert isinstance(cfg.param["K"], FlowParam)
    assert cfg.param["K"].field.id == "K"
    assert cfg.param["K"].field.kind == "heterogeneous"
    assert cfg.param["K"].field_vertical_profile is not None
    assert cfg.param["Sy"].field.kind == "homogeneous"

    reloaded = FlowConfig.model_validate_json(cfg.model_dump_json())

    assert reloaded == cfg


# Native Pydantic payload tests for flow boundary conditions.


def test_flow_bc_native_round_trip_dirichlet_and_cauchy() -> None:
    cfg = FlowConfig.model_validate(
        {
            "bc": {
                "ocean": {"kind": "dirichlet", "value": 0.0},
                "stream": {"kind": "dirichlet", "value": 1.0},
                "north_side": {"kind": "dirichlet", "value": 2.0},
                "south_side": {"kind": "dirichlet", "value": 3.0},
                "east_side": {"kind": "dirichlet", "value": 4.0},
                "west_side": {"kind": "dirichlet", "value": 5.0},
                "drainage": {
                    "kind": "drain",
                    "value": "10 cm2/day",
                    "application_domain": "top",
                },
            }
        }
    )

    assert all(isinstance(cfg.bc[bc_id], DirichletBC) for bc_id in cfg.bc if bc_id != "drainage")
    assert isinstance(cfg.bc["drainage"], DrainBC)

    reloaded = FlowConfig.model_validate_json(cfg.model_dump_json())

    assert reloaded == cfg


def test_flow_bc_native_round_trip_robin() -> None:
    cfg = FlowConfig.model_validate(
        {
            "bc": {
                "drainage": {
                    "kind": "drain",
                    "value": 2.0e-6,
                    "application_domain": "top",
                }
            }
        }
    )

    assert isinstance(cfg.bc["drainage"], DrainBC)

    reloaded = FlowConfig.model_validate_json(cfg.model_dump_json())

    assert reloaded == cfg


# Guard against opaque payloads in the root configuration schema.
#
# The parameter reference is read from the Pydantic ``model_fields``. A
# ``dict[str, object]`` under ``HydroModPyConfig`` hides a structure the
# reference cannot show, unless its path is a free-form mapping listed in
# ``INTENTIONALLY_OPAQUE_PATHS``.


_OPAQUE_DICT_VALUE = re.compile(
    r"\bdict\[\s*str\s*,\s*(object|dict\[str,\s*object\])",
    re.IGNORECASE,
)


# Mappings from an external key (geology zone, station id) to a scalar value.
INTENTIONALLY_OPAQUE_PATHS: frozenset[str] = frozenset()


def _annotation_text(annotation: object) -> str:
    return annotation.__name__ if isinstance(annotation, type) else str(annotation)


def _opaque_fields(model: type[BaseModel], section_path: str, seen: set[int]) -> list[str]:
    paths: list[str] = []
    for name, field in model.model_fields.items():
        if field.exclude:
            continue
        path = f"{section_path}.{name}" if section_path else name
        if _OPAQUE_DICT_VALUE.search(_annotation_text(field.annotation)):
            paths.append(path)
        for arg in (field.annotation, *getattr(field.annotation, "__args__", ())):
            if isinstance(arg, type) and issubclass(arg, BaseModel) and id(arg) not in seen:
                paths.extend(_opaque_fields(arg, path, seen | {id(arg)}))
    return paths


def test_no_opaque_dicts_in_root_schema() -> None:
    opaque = _opaque_fields(HydroModPyConfig, "", {id(HydroModPyConfig)})
    assert set(opaque) - INTENTIONALLY_OPAQUE_PATHS == set()


# A boundary, a sink or a source is active when its table is declared, unless it says so.
#
# No list names what a run builds. ``FlowConfig.active_bc`` and
# ``FlowConfig.active_sinks_sources`` read the tables, and ``enabled = false`` keeps a
# table in the file and builds nothing from it.


WELL = {"flux": -0.01, "location": {"kind": "relative_xy", "x_rel": 0.5, "y_rel": 0.5}}


LAKE = {"bedleak": 1e-6, "initial_stage": "10 m"}


#: (table family, name, a declared table, the name the run lists for it)
TABLES = [
    ("bc", "drainage", {}, "drainage"),
    ("sinks_sources", "recharge", {}, "recharge"),
    ("sinks_sources", "etp", {}, "etp"),
    ("sinks_sources", "wells", {"W1": WELL}, "wells"),
    ("sinks_sources", "lakes", {"pond": LAKE}, "lake"),
    ("sinks_sources", "sfr", {"main": {}}, "sfr"),
]


def _config(family: str, name: str, table: dict) -> FlowConfig:
    return FlowConfig(**{family: {name: table}})


def _listed(cfg: FlowConfig) -> list[str]:
    return [*cfg.active_bc, *cfg.active_sinks_sources]


def _switched_off(name: str, table: dict) -> dict:
    """The same table with ``enabled = false``: on the table, or on each entry of a map."""
    if name in {"wells", "lakes", "sfr"}:
        return {key: {**entry, "enabled": False} for key, entry in table.items()}
    return {**table, "enabled": False}


@pytest.mark.parametrize(("family", "name", "table", "listed"), TABLES)
def test_a_declared_table_is_active(family: str, name: str, table: dict, listed: str) -> None:
    assert _listed(_config(family, name, table)) == [listed]


@pytest.mark.parametrize(("family", "name", "table", "listed"), TABLES)
def test_a_table_that_says_enabled_false_builds_nothing(
    family: str, name: str, table: dict, listed: str
) -> None:
    assert _listed(_config(family, name, _switched_off(name, table))) == []


def test_a_run_that_declares_nothing_lists_nothing() -> None:
    assert _listed(FlowConfig()) == []


@pytest.mark.parametrize("old", ["active_bc", "active_sinks_sources"])
def test_the_lists_are_no_longer_a_key(old: str) -> None:
    with pytest.raises(ValueError, match=f"'{old}' is not accepted any more"):
        FlowConfig(**{old: ["drainage"]})


# The FlowBarrierConfig HFB payload (general addon + lake cutoff wall).
#
# A flow barrier carries the trace (inline ``line`` or a ``line_path`` vector
# file), the ``depths`` below the model top, and the resistance (``hydchr`` or
# ``k`` + ``thickness``). It is declared either generally under
# ``[flow.sinks_sources.flow_barriers.<id>]`` or as a lake's ``cutoff_wall``. The
# tests check the geometry / resistance XOR rules, the unit conversions of
# ``effective_hydchr``, ``extra='forbid'``, that it nests on a lake config and on
# the sinks-sources container, and that the binder normalizer carries the lake
# wall onto the payload dict.


def test_inline_line_and_hydchr_validate() -> None:
    wall = FlowBarrierConfig(line=[[0.0, 0.0], [10.0, 0.0]], depths=[10.0], hydchr=1e-9)
    assert wall.effective_hydchr() == pytest.approx(1e-9)
    assert wall.line_path is None


def test_hydchr_unit_is_converted_to_per_second() -> None:
    # 1/day at 8.64e-5 is 1e-9 1/s.
    wall = FlowBarrierConfig(
        line=[[0.0, 0.0], [1.0, 1.0]], depths=[5.0], hydchr=8.64e-5, hydchr_unit="1/day"
    )
    assert wall.effective_hydchr() == pytest.approx(1e-9)


def test_k_and_thickness_derive_hydchr() -> None:
    # hydchr = K / thickness = 1e-8 (m/s) / 0.5 (m) = 2e-8 1/s.
    wall = FlowBarrierConfig(line=[[0.0, 0.0], [10.0, 0.0]], depths=[5.0], k=1e-8, thickness=0.5)
    assert wall.effective_hydchr() == pytest.approx(2e-8)


def test_k_unit_is_converted() -> None:
    # 0.864 m/day = 1e-5 m/s; over 1 m thickness => 1e-5 1/s.
    wall = FlowBarrierConfig(
        line=[[0.0, 0.0], [10.0, 0.0]],
        depths=[5.0],
        k=0.864,
        k_unit="m/day",
        thickness=1.0,
    )
    assert wall.effective_hydchr() == pytest.approx(1e-5)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(line=[[0, 0], [1, 0]], line_path="x.gpkg", depths=[1.0], hydchr=1e-9),  # both geom
        dict(depths=[1.0], hydchr=1e-9),  # no geom
        dict(line=[[0, 0], [1, 0]], depths=[1.0], hydchr=1e-9, k=1e-8, thickness=0.5),  # both R
        dict(line=[[0, 0], [1, 0]], depths=[1.0], hydchr=1e-9, k=1e-8),  # hydchr + stray k
        dict(line=[[0, 0], [1, 0]], depths=[1.0], hydchr=1e-9, thickness=0.5),  # hydchr + stray th
        dict(line=[[0, 0], [1, 0]], depths=[1.0], k=1e-8),  # partial resistance (k only)
        dict(line=[[0, 0], [1, 0]], depths=[1.0], thickness=0.5),  # partial resistance (th only)
        dict(line=[[0, 0]], depths=[1.0], hydchr=1e-9),  # single-vertex line
        dict(line=[[0, 0], [1, 0]], depths=[0.0], hydchr=1e-9),  # non-positive depth
        dict(line=[[0, 0], [1, 0]], depths=[1.0], hydchr=1e-9, hydchr_unit="bogus"),  # bad unit
        dict(line=[[0, 0], [1, 0]], depths=[1.0], hydchr=1e-9, who="me"),  # extra field
    ],
)
def test_invalid_configs_are_rejected(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        FlowBarrierConfig(**kwargs)


def test_nests_as_lake_cutoff_wall_and_survives_the_binder_normalizer() -> None:
    lake = FlowLakeConfig.model_validate(
        {
            "bedleak": 1e-6,
            "initial_stage": "81.82 m",
            "cutoff_wall": {
                "line": [[331142.0, 6780439.3], [331119.4, 6780718.7]],
                "depths": [10.0],
                "hydchr": 1e-9,
            },
        }
    )
    assert isinstance(lake.cutoff_wall, FlowBarrierConfig)

    flow = SimpleNamespace(sinks_sources={"lakes": {"reservoir": lake}})
    payloads = _lake_payloads_as_mappings(flow)
    assert isinstance(payloads["reservoir"]["cutoff_wall"], FlowBarrierConfig)


def test_general_flow_barriers_mapping_validates() -> None:
    ss = FlowSinksSourcesConfig.model_validate(
        {
            "flow_barriers": {
                "wall_a": {"line": [[0.0, 0.0], [10.0, 0.0]], "depths": [8.0], "hydchr": 1e-9}
            }
        }
    )
    assert isinstance(ss.flow_barriers["wall_a"], FlowBarrierConfig)
    assert ss.flow_barriers["wall_a"].effective_hydchr() == pytest.approx(1e-9)
