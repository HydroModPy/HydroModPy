"""Conformance suite for the solver port, run against every backend the registry serves.

Each test takes the ``key`` fixture, parametrized over ``solvers.names()`` and not
over a list this file keeps, so a backend installed beside the build through the
``hydromodpy.solver`` group is held to the port without a line of ``tests/``
naming it. ``register()`` already refuses an absent attribute and a wrong type.
This file checks what only the rest of the build can say: that every name a
backend declares means something to the registries, the field registry, the
budget terms, the table schemas and the traits of ``model/supports.py``, and that
the members a runner calls take the arguments the Protocol names: ``rerun`` if
and only if the backend is ``mutable``, ``observables`` with
``declared_observables``, and the cell lookups of ``CellLocator`` on a flow.

The supports of the three shipped flows are written here as the expected lists,
because the configuration refuses from them every trait a document uses and its
flow does not honour. Each trait has one small document that uses it, and every
flow loads it if and only if it lists the trait. A transport is held to the flows
its ``requires`` names the same way.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import pytest
from pandas.tseries.frequencies import to_offset
from pydantic import BaseModel

from hydromodpy.config import HydroModPyConfig
from hydromodpy.config.cross_checks import TRAIT_USES
from hydromodpy.core.budget.terms import PER_CELL_BUDGET_TERMS
from hydromodpy.core.exceptions import ConfigValidationError, IncompatibleCapabilitiesError
from hydromodpy.mesh.port import ANY_PLANAR_ENGINE
from hydromodpy.mesh.registry import mesh_engines
from hydromodpy.model.properties.property_table import OVERRIDE_PROPERTY_NAMES
from hydromodpy.model.supports import SUPPORT_SOURCES, SUPPORTS
from hydromodpy.results.catalog.constants import solver_category
from hydromodpy.results.field_registry import BUDGET_GROUP, all_zarr_paths
from hydromodpy.results.storage.parquet_schemas import VIEW_SCHEMAS
from hydromodpy.solver.base.adapter_protocol import (
    CATEGORIES,
    GEOMETRIES,
    OPTIONAL_MEMBERS,
    RERUN_MEMBERS,
    CellLocator,
    SolverAdapter,
)
from hydromodpy.solver.base.registry import extractors, solvers

UNDESCRIBED_GROUPS = ("particles/", "boussinesq_state/", "lake_state_final/", "lake_abacus/")
"""The four Zarr groups the field registry does not describe name by name.

``lake_state_final/`` and ``lake_abacus/`` sit outside the pipeline groups and
only the MODFLOW 6 extractor writes them. A later run reads the first back as
its prior lake stages.
"""

_HEAD_START = frozenset({"head_rule", "steady_start"})
_OPTIONS = SUPPORT_SOURCES["option"]
_RECHARGE_AND_WELLS = frozenset({"recharge", "wells"})

SHIPPED_SUPPORTS: dict[str, frozenset[str]] = {
    "flow_modflow6": SUPPORTS,
    "flow_modflow_nwt": frozenset(
        {"west_side", "east_side", "north_side", "south_side", "ocean", "drainage"}
    )
    | _OPTIONS
    | _HEAD_START
    | _RECHARGE_AND_WELLS
    | {"etp", "layers"},
    "flow_boussinesq": frozenset(
        {"west_side", "east_side", "north_side", "south_side", "stream", "ocean", "drainage"}
    )
    | {"drain_bed_thickness_m"}
    | _HEAD_START
    | _RECHARGE_AND_WELLS,
    "transport_modflow6": frozenset(),
    "transport_modflow6_prt": frozenset(),
    "transport_mt3dms": frozenset(),
    "transport_modpath": frozenset(),
}
"""What each shipped backend honours: MODFLOW 6 all 26 traits, NWT 16, Boussinesq 12.

Only MODFLOW 6 reads a prior run, starts cyclic, builds a lake, a stream network,
a flow barrier or a cutoff wall, reads the soil reservoir and the K tensor, and
has pass-through cells. Boussinesq solves one layer, builds no ETP, and reads one
option of ``ModelOptions``, the drain bed thickness.
"""


@pytest.fixture(params=solvers.names())
def key(request: pytest.FixtureRequest) -> str:
    """The key of one backend, once per adapter this installation serves."""
    return request.param


@pytest.fixture
def backend(key: str) -> type:
    return solvers.get(key)


def _known_name(name: str) -> bool:
    """Whether *name* is a stored field, a budget term, a table or a member of an undescribed group."""
    known = set(all_zarr_paths()) | {f"{BUDGET_GROUP}{term}" for term in PER_CELL_BUDGET_TERMS}
    known |= set(VIEW_SCHEMAS)
    if name.startswith(UNDESCRIBED_GROUPS) and name not in UNDESCRIBED_GROUPS:
        return True
    if "*" in name:
        return any(fnmatchcase(candidate, name) for candidate in known)
    return name in known


def test_the_backend_is_an_adapter_under_its_own_key(key: str, backend: type) -> None:
    assert isinstance(backend, SolverAdapter)
    assert f"{backend.process_type}_{backend.name}" == key


def test_the_identity_attributes_are_non_empty_strings(backend: type) -> None:
    for attribute in ("name", "process_type"):
        value = getattr(backend, attribute)
        assert isinstance(value, str) and value.strip(), attribute


def test_geometry_and_category_are_in_their_vocabulary(backend: type) -> None:
    assert backend.geometry in GEOMETRIES
    assert backend.category in CATEGORIES


def test_the_category_of_a_flow_agrees_with_the_index_table(backend: type) -> None:
    """The index falls back on ``solver_category()`` when a manifest has no category.

    That table in ``results/catalog/constants.py`` is a second copy of the
    category of each flow, because ``results`` does not read ``solver``. It
    leaves with the index seeds, and this case leaves with it.
    """
    if backend.process_type != "flow":
        return
    assert solver_category(backend.name) in (None, backend.category)


def test_a_flow_reads_meshes_the_mesh_registry_serves_and_a_transport_none(backend: type) -> None:
    assert isinstance(backend.accepted_meshes, frozenset)
    if backend.process_type == "transport":
        assert backend.accepted_meshes == frozenset()
        return
    assert backend.accepted_meshes, "a flow reads at least one mesh"
    served = set(mesh_engines.names()) | {ANY_PLANAR_ENGINE}
    assert set(backend.accepted_meshes) <= served


def test_each_required_key_is_a_backend_the_registry_serves(backend: type) -> None:
    for process_type, name in backend.requires:
        assert name in solvers.names(process_type), (process_type, name)


def test_each_written_name_is_known_to_the_store(backend: type) -> None:
    assert isinstance(backend.writes, tuple) and backend.writes
    unknown = sorted(name for name in backend.writes if not _known_name(name))
    assert unknown == []


def test_a_flow_reads_nothing_and_a_transport_reads_the_face_flows(backend: type) -> None:
    expected = {"flow": (), "transport": ("face_flow",)}.get(backend.process_type)
    if expected is not None:
        assert backend.reads == expected


def test_each_supported_trait_belongs_to_the_closed_set(backend: type) -> None:
    assert isinstance(backend.supports, frozenset)
    assert sorted(backend.supports - SUPPORTS) == []


def test_the_listed_traits_cover_the_shipped_backends() -> None:
    assert sorted(SHIPPED_SUPPORTS) == list(solvers.names(shipped_only=True))


@pytest.mark.parametrize("shipped", sorted(SHIPPED_SUPPORTS))
def test_a_shipped_backend_supports_exactly_its_listed_traits(shipped: str) -> None:
    assert solvers.get(shipped).supports == SHIPPED_SUPPORTS[shipped]


def test_options_is_a_pydantic_class_or_none(backend: type) -> None:
    options = backend.options
    assert options is None or (isinstance(options, type) and issubclass(options, BaseModel))


def test_native_step_is_none_or_a_pandas_frequency(backend: type) -> None:
    if backend.native_step is not None:
        to_offset(backend.native_step)


def test_mutable_names_are_strings(backend: type) -> None:
    assert isinstance(backend.mutable, frozenset)
    assert all(isinstance(name, str) for name in backend.mutable)


def _parameters(member: Callable[..., Any]) -> list[tuple[str, str]]:
    """The ``(name, kind)`` of each parameter a member takes after ``self``."""
    found = [
        (parameter.name, parameter.kind.name)
        for parameter in inspect.signature(member).parameters.values()
    ]
    return found[1:] if found and found[0][0] == "self" else found


def _protocol_methods(protocol: type) -> list[str]:
    return [
        name
        for name, value in vars(protocol).items()
        if callable(value) and not name.startswith("_")
    ]


SIGNATURES: dict[str, list[tuple[str, str]]] = {
    "rerun": [
        ("previous", "POSITIONAL_OR_KEYWORD"),
        ("model", "POSITIONAL_OR_KEYWORD"),
        ("slot", "POSITIONAL_OR_KEYWORD"),
    ],
    "observables": [
        ("solver_run", "POSITIONAL_OR_KEYWORD"),
        ("requests", "POSITIONAL_OR_KEYWORD"),
        ("time_index", "KEYWORD_ONLY"),
    ],
    "declared_observables": [("active", "POSITIONAL_OR_KEYWORD")],
}
"""The parameters of the optional members, which the Protocol describes in words."""


def test_each_member_the_runner_calls_takes_the_arguments_the_protocol_names(
    backend: type,
) -> None:
    """A runner calls ``build(model, options, slot, ctx)``: a backend that renamed one breaks."""
    for name in _protocol_methods(SolverAdapter):
        member = getattr(backend, name)
        assert _parameters(member) == _parameters(getattr(SolverAdapter, name)), name


def test_rerun_is_there_if_and_only_if_the_backend_is_mutable(backend: type) -> None:
    for name in RERUN_MEMBERS:
        member = getattr(backend, name, None)
        assert callable(member) is bool(backend.mutable), name
        if callable(member):
            assert _parameters(member) == SIGNATURES[name], name


def test_a_mutable_name_is_a_property_the_model_can_change(backend: type) -> None:
    """``rerun`` receives a model made by ``with_properties``, which accepts these names."""
    assert sorted(backend.mutable - OVERRIDE_PROPERTY_NAMES) == []


def test_observables_and_their_declaration_come_together(backend: type) -> None:
    present = {name: callable(getattr(backend, name, None)) for name in OPTIONAL_MEMBERS}
    assert len(set(present.values())) == 1, present
    for name, there in present.items():
        if there:
            assert _parameters(getattr(backend, name)) == SIGNATURES[name], name


def test_a_flow_locates_a_cell_on_the_grid_of_its_run(backend: type) -> None:
    if backend.process_type != "flow":
        return
    assert isinstance(backend, CellLocator)
    for name in _protocol_methods(CellLocator):
        assert _parameters(getattr(backend, name)) == _parameters(getattr(CellLocator, name)), name


def test_an_extractor_reads_back_each_backend(key: str) -> None:
    """An adapter without an extractor solves, then loses the run at ingestion."""
    assert key in extractors.names()
    assert callable(getattr(extractors.get(key), "extract", None))


LAKE = {"bedleak": 0.1, "initial_stage": "85 m"}
WALL = {"line": [[0.0, 0.0], [10.0, 0.0]], "depths": [5.0], "hydchr": 1e-9}
K_FIELD = {"kind": "homogeneous", "value": "1e-5 m/s"}
SOIL_DATA = {
    "types": ["precipitation", "etp"],
    "precipitation": {"sources": [{"source": "sim2", "extent": "watershed"}]},
    "etp": {"sources": [{"source": "sim2", "extent": "watershed"}]},
}


def _flow(**flow: Any) -> dict[str, Any]:
    return {"flow": flow}


TRAIT_DOCUMENTS: dict[str, dict[str, Any]] = {
    **{side: _flow(bc={side: {"value": "10 m"}}) for side in ("west_side", "east_side")},
    **{side: _flow(bc={side: {"value": "10 m"}}) for side in ("north_side", "south_side")},
    "stream": _flow(bc={"stream": {"value": "10 m"}}),
    "ocean": _flow(bc={"ocean": {"value": "0 m"}}),
    "drainage": _flow(bc={"drainage": {}}),
    "lake": _flow(sinks_sources={"lakes": {"lac": LAKE}}),
    "sfr": _flow(bc={"drainage": {}}, sinks_sources={"sfr": {"main": {}}}),
    "sink_fill": {"solver": {"sink_fill": True}},
    "drain_band_depth_m": {"solver": {"drain_band_depth_m": 0.5}},
    "drain_bed_thickness_m": {"solver": {"drain_bed_thickness_m": 0.5}},
    "drain_conductance_floor_m2_s": {"solver": {"drain_conductance_floor_m2_s": 1e-10}},
    "head_rule": _flow(ic={"kind": "top"}),
    "steady_start": _flow(ic={"kind": "steady_state"}),
    "cyclic_start": _flow(ic={"kind": "spinup_cyclic"}),
    "prior_state": _flow(restart_from="runs/spinup/fields.zarr"),
    "recharge": _flow(sinks_sources={"recharge": {}}),
    "wells": _flow(
        sinks_sources={
            "wells": {"w1": {"location": {"kind": "absolute_xy", "x": 1.0, "y": 2.0}, "flux": -1.0}}
        }
    ),
    "etp": _flow(sinks_sources={"etp": {}}),
    "flow_barriers": _flow(sinks_sources={"flow_barriers": {"wall": WALL}}),
    "cutoff_wall": _flow(sinks_sources={"lakes": {"lac": {**LAKE, "cutoff_wall": WALL}}}),
    "soil": {
        "simulation": {
            "time": {
                "start_datetime": "2015-01-01",
                "end_datetime": "2016-12-31",
                "step_value": "1 day",
            }
        },
        "data": SOIL_DATA,
        "flow": {
            "first_period_steady": False,
            "sinks_sources": {"recharge": {"soil": {"ru": "150 mm"}}},
        },
    },
    "k_tensor": _flow(
        param_list=["K", "K22"], param={"K": {"field": K_FIELD}, "K22": {"field": K_FIELD}}
    ),
    "layers": {"domain": {"layers": {"nlay": 3}}},
    "pass_through": {
        "domain": {
            "layers": {
                "genmtd_lay": "surfaces",
                "pinch_out": "pass_through",
                "layer": [{"name": "weathered", "surface": "weathered_base"}, {"name": "rock"}],
            }
        },
        "data": {"layer_base": {"sources": [{"name": "weathered_base", "path": "weathered.tif"}]}},
    },
}
"""One small document per trait, which uses that trait and no other a shipped flow lacks."""


def _mesh_for(flow: type) -> dict[str, Any]:
    """The mesh section a flow reads: none for the default engine, else its first engine."""
    if "regular" in flow.accepted_meshes:
        return {}
    engine = sorted(flow.accepted_meshes - {ANY_PLANAR_ENGINE})[0]
    return {"mesh": {"engine": engine, "families": {"rivers": "none"}}}


def _document(tmp_path: Path, flow: type, extra: dict[str, Any]) -> dict[str, Any]:
    (tmp_path / "weathered.tif").touch()
    return {
        "workflow": {"mode": "simulation"},
        "geographic": {"source_mode": "synthetic"},
        **_mesh_for(flow),
        **extra,
        "solver": {"backend": flow.name, **extra.get("solver", {})},
    }


def _flows() -> list[str]:
    return [f"flow_{name}" for name in solvers.names("flow")]


def test_every_trait_has_a_document_and_a_row_of_the_trait_table() -> None:
    assert set(TRAIT_DOCUMENTS) == SUPPORTS
    assert set(TRAIT_USES) == SUPPORTS


@pytest.mark.parametrize("flow_key", _flows())
def test_the_toml_accepts_the_name_of_each_flow(tmp_path: Path, flow_key: str) -> None:
    flow = solvers.get(flow_key)
    cfg = HydroModPyConfig.from_dict(_document(tmp_path, flow, {}), base_dir=tmp_path)

    assert cfg.solver.backend_name == flow.name


@pytest.mark.parametrize("flow_key", _flows())
def test_the_settings_of_a_flow_read_back_from_its_own_table(tmp_path: Path, flow_key: str) -> None:
    flow = solvers.get(flow_key)
    if flow.options is None:
        return
    written = flow.options().model_dump(mode="json")
    document = _document(tmp_path, flow, {"solver": {flow.name: written}})

    cfg = HydroModPyConfig.from_dict(document, base_dir=tmp_path)

    assert cfg.solver.options_of(flow.name).model_dump(mode="json") == written


@pytest.mark.parametrize("flow_key", _flows())
def test_an_unknown_key_of_a_flow_table_is_refused(tmp_path: Path, flow_key: str) -> None:
    """A flow without settings refuses its table; a flow with settings refuses a key it lacks."""
    flow = solvers.get(flow_key)
    document = _document(tmp_path, flow, {"solver": {flow.name: {"no_solver_has_this_key": 1}}})

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_dict(document, base_dir=tmp_path)

    message = str(excinfo.value)
    assert f"solver.{flow.name}" in message
    if flow.options is None:
        assert "declares none to read them" in message
    else:
        assert "no_solver_has_this_key" in message


@pytest.mark.parametrize("trait", sorted(SUPPORTS))
@pytest.mark.parametrize("flow_key", _flows())
def test_a_document_that_uses_a_trait_loads_if_and_only_if_the_flow_lists_it(
    tmp_path: Path, flow_key: str, trait: str
) -> None:
    flow = solvers.get(flow_key)
    document = _document(tmp_path, flow, TRAIT_DOCUMENTS[trait])
    if trait in flow.supports:
        HydroModPyConfig.from_dict(document, base_dir=tmp_path)
        return
    honoring = [
        name for name in solvers.names("flow") if trait in solvers.get("flow", name).supports
    ]
    with pytest.raises(IncompatibleCapabilitiesError) as excinfo:
        HydroModPyConfig.from_dict(document, base_dir=tmp_path)

    message = str(excinfo.value)
    assert f"solver.backend = {flow.name!r} does not honor" in message
    assert f"({', '.join(honoring)})" in message


@pytest.mark.parametrize("transport", solvers.names("transport"))
@pytest.mark.parametrize("flow_key", _flows())
def test_a_transport_loads_if_and_only_if_its_requires_names_the_flow(
    tmp_path: Path, flow_key: str, transport: str
) -> None:
    flow = solvers.get(flow_key)
    process = [
        {"id": "flow_main", "kind": "flow", "solvers": [flow.name]},
        {"id": "transport_main", "kind": "transport", "solvers": [transport]},
    ]
    document = _document(tmp_path, flow, {"simulation": {"process": process}})
    followed = [
        name for kind, name in solvers.get("transport", transport).requires if kind == "flow"
    ]
    if not followed or flow.name in followed:
        HydroModPyConfig.from_dict(document, base_dir=tmp_path)
        return
    with pytest.raises(ConfigValidationError, match=f"the transport solver {transport!r} follows"):
        HydroModPyConfig.from_dict(document, base_dir=tmp_path)
