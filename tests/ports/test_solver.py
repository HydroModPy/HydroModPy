"""The solver port, played on every backend the registry serves.

The first cases read the attributes of each backend and the documents that
name it. Each takes the ``key`` fixture, parametrized over ``solvers.names()``
and not over a list this file keeps, so a backend installed beside the build
through the ``hydromodpy.solver`` group is held to the port without a line of
``tests/`` naming it. ``register()`` already refuses an absent attribute and a
wrong type. These cases check what only the rest of the build can say: that
every name a backend declares means something to the registries, the field
registry, the budget terms, the table schemas and the traits of
``model/supports.py``, and that the members a runner calls take the arguments
the Protocol names: ``rerun`` if and only if the backend is ``mutable``,
``observables`` with ``declared_observables``, and the cell lookups of
``CellLocator`` on a flow. The supports of the shipped flows are written here
as the expected lists, because the configuration refuses from them every trait
a document uses and its flow does not honour. Each trait has one small
document that uses it, and every flow loads it if and only if it lists the
trait. A transport is held to the flows its ``requires`` names the same way.

The behaviour section builds, solves and extracts real runs on the backends
this build ships. Each flow plays on each mesh engine: a pair outside
``accepted_meshes`` is a skip that says so, which gives the lumped reservoir
one played case and three declared skips. The flow keeps the ``Model`` it is
given and leaves it as it found it, reads a K and a recharge set on it, builds
and solves in the folder of its ``RunSlot``, extracts only the names of
``writes`` and what the ``Retention`` keeps, closes its budget, and finds the
cell that holds a point. Each transport follows the first flow its
``requires`` names. Each boundary of the registry reaches the build of every
flow that supports it, and each flow solves once with all its boundaries open
on the island. A missing solver binary or optional module is a declared skip,
see ``conftest.py``.

The last section installs a backend this file never names and plays the first
cases against it in a subprocess.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager, ExitStack, contextmanager, nullcontext
from dataclasses import dataclass, fields, is_dataclass, replace
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import tomli_w
import zarr
from pandas.tseries.frequencies import to_offset
from pydantic import BaseModel

from hydromodpy.calibration.metrics import solver_extract
from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.calibration.runners.trial import built_model, prepare_trials
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.config.solver_supports import TRAIT_USES
from hydromodpy.core.budget.terms import PER_CELL_BUDGET_TERMS, BudgetKeep
from hydromodpy.core.exceptions import ConfigValidationError, IncompatibleCapabilitiesError
from hydromodpy.mesh.port import ANY_PLANAR_ENGINE
from hydromodpy.mesh.registry import DEFAULT_ENGINE_ID, engine_accepted, mesh_engines
from hydromodpy.model.boundaries.boundary_condition_registry import FLOW_BOUNDARY_DEFINITIONS
from hydromodpy.model.model import ModelTime
from hydromodpy.model.properties.property_table import OVERRIDE_PROPERTY_NAMES
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.model.supports import SUPPORT_SOURCES, SUPPORTS
from hydromodpy.results.field_registry import (
    BUDGET_GROUP,
    FACE_FLOW,
    TIME_SERIES_REGISTRY,
    all_zarr_paths,
)
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    PARQUET_FILE_SUFFIX,
    TABLES_DIRNAME,
)
from hydromodpy.results.storage.declared import refuse_undeclared, stored_names
from hydromodpy.results.storage.kept import Retention
from hydromodpy.results.storage.parquet_schemas import VIEW_SCHEMAS
from hydromodpy.solver.base import adapter_protocol
from hydromodpy.solver.base.adapter_protocol import (
    CATEGORIES,
    GEOMETRIES,
    OPTIONAL_MEMBERS,
    RERUN_MEMBERS,
    CellLocator,
    SolverAdapter,
)
from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.solver.base.registry import extractors, solvers
from hydromodpy.solver.base.runner import options_for, slot_for, solve_one
from tests._helpers.island_project import island_toml
from tests._helpers.model_factory import make_model, one_cell_geometry, time_grid
from tests._helpers.run_stores import open_run_store
from tests._helpers.tolerances import tol
from tests.scenarios.factory import (
    TRANSPORT_PARAMETERS,
    TRANSPORT_TAILS,
    cheze_valley_files,
    transport_island,
)

from ._installed_probe import REPO_ROOT, collected, run_suite, unpack

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
    | {"etp", "layers", "properties"},
    "flow_boussinesq": frozenset(
        {"west_side", "east_side", "north_side", "south_side", "stream", "ocean", "drainage"}
    )
    | {"drain_bed_thickness_m", "properties"}
    | _HEAD_START
    | _RECHARGE_AND_WELLS,
    "flow_linear_reservoir": frozenset({"recharge", "steady_start"}),
    "transport_modflow6": frozenset(),
    "transport_modflow6_prt": frozenset(),
    "transport_mt3dms": frozenset(),
    "transport_modpath": frozenset(),
}
"""What each shipped backend honours: MODFLOW 6 all 27 traits, NWT 17, Boussinesq 13,
the linear reservoir 2.

Only MODFLOW 6 reads a prior run, starts cyclic, builds a lake, a stream network,
a flow barrier or a cutoff wall, reads the soil reservoir and the K tensor, and
has pass-through cells. Boussinesq solves one layer, builds no ETP, and reads one
option of ``ModelOptions``, the drain bed thickness. The linear reservoir reads
only its recharge and starts from its steady state: it reads no aquifer property.
"""

FLOW_SETTINGS: dict[str, dict[str, Any]] = {
    "flow_linear_reservoir": {"time_constant": "30 days"},
}
"""The settings a flow refuses to run without, which its options class leaves without a default."""


@pytest.fixture(params=solvers.names())
def key(request: pytest.FixtureRequest) -> str:
    """The key of one backend, once per adapter this installation serves."""
    return request.param


@pytest.fixture
def backend(key: str) -> type:
    return solvers.get(key)


def _known_name(name: str) -> bool:
    """Whether *name* is a stored field, a budget term, a table, a series or a member of an undescribed group."""
    known = set(all_zarr_paths()) | {f"{BUDGET_GROUP}{term}" for term in PER_CELL_BUDGET_TERMS}
    known |= set(VIEW_SCHEMAS) | set(TIME_SERIES_REGISTRY)
    if name.startswith(UNDESCRIBED_GROUPS) and name not in UNDESCRIBED_GROUPS:
        return True
    if "/*" in name:
        prefix = name.split("/*", 1)[0]
        return any(candidate == prefix or candidate.startswith(prefix + "/") for candidate in known)
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


def test_the_hand_off_tuple_is_gone_and_the_registry_names_the_product() -> None:
    assert not hasattr(adapter_protocol, "HANDOFF_PRODUCTS")
    assert _known_name(FACE_FLOW)


def test_a_flow_reads_nothing_and_a_transport_reads_the_face_flows(backend: type) -> None:
    expected = {"flow": (), "transport": (FACE_FLOW,)}.get(backend.process_type)
    if expected is not None:
        assert backend.reads == expected


def test_a_transport_declares_reads_and_never_observables(backend: type) -> None:
    """A transport names what it reads, in one place; observables stay flow members."""
    if backend.process_type != "transport":
        return
    assert backend.reads, "a transport with no read has nothing to follow"
    for name in backend.reads:
        assert _known_name(name), name
    for name in OPTIONAL_MEMBERS:
        assert not callable(getattr(backend, name, None)), name


def test_a_flow_declares_writes_the_store_names(backend: type) -> None:
    """A name a flow writes is one the registry describes or a table the store holds."""
    if backend.process_type != "flow":
        return
    for name in backend.writes:
        assert _known_name(name), name


@pytest.mark.parametrize("flow", ["flow_modflow6", "flow_modflow_nwt"])
def test_the_two_flows_write_the_cells_of_each_connection(flow: str) -> None:
    assert "connection_cells" in solvers.get(flow).writes


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
    params = found[1:] if found and found[0][0] == "self" else found
    return [("upstream" if name == "ctx" else name, kind) for name, kind in params]


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


def test_each_member_the_runner_calls_takes_the_arguments_the_protocol_names(backend: type) -> None:
    """A runner calls ``build(model, options, slot, upstream)``: a backend that renamed one breaks."""
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
    "properties": _flow(param={"K": {"field": K_FIELD}}),
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


def _merged(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """*base* with *extra* written over it, table by table."""
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merged(merged[key], value)
        else:
            merged[key] = value
    return merged


def _needs_of(flow: type) -> dict[str, Any]:
    """What a flow reads in every document: its required settings and the start it honours.

    A flow that lists no head rule starts from its steady state, so its
    documents ask for it in place of the default head rule.
    """
    needs: dict[str, Any] = {}
    settings = FLOW_SETTINGS.get(f"flow_{flow.name}")
    if settings is not None:
        needs["solver"] = {flow.name: settings}
    if "head_rule" not in flow.supports and "steady_start" in flow.supports:
        needs["flow"] = {"ic": {"kind": "steady_state"}}
    return needs


def _document(tmp_path: Path, flow: type, extra: dict[str, Any]) -> dict[str, Any]:
    (tmp_path / "weathered.tif").touch()
    document = _merged(
        {
            "workflow": {"mode": "simulation"},
            "geographic": {"source_mode": "synthetic"},
            **_mesh_for(flow),
            **_needs_of(flow),
        },
        extra,
    )
    document["solver"] = {**document.get("solver", {}), "backend": flow.name}
    return document


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
    written = flow.options(**FLOW_SETTINGS.get(flow_key, {})).model_dump(mode="json")
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


def _documented_scalar(options: type[BaseModel]) -> tuple[list[str], str] | None:
    """Return the path and the description of the first documented field that is not a table.

    The walk goes down the tables of the settings, ``runtime`` of MODFLOW 6 for one.
    """
    for name, info in options.model_fields.items():
        members = (info.annotation, *getattr(info.annotation, "__args__", ()))
        tables = [arg for arg in members if isinstance(arg, type) and issubclass(arg, BaseModel)]
        if tables:
            inner = _documented_scalar(tables[0])
            if inner is not None:
                return [name, *inner[0]], inner[1]
            continue
        mappings = [arg for arg in members if isinstance(arg, type) and issubclass(arg, dict)]
        if info.description and info.annotation is not Any and not mappings:
            return [name], info.description
    return None


@pytest.mark.parametrize("flow_key", _flows())
def test_the_check_points_at_a_key_of_a_flow_table_with_its_help(
    tmp_path: Path, flow_key: str
) -> None:
    """``check`` names the exact key of ``[solver.<name>]``, and helps with its description.

    The settings class is the one the registry serves for the backend, so a
    plugin that ships no phrase of its own gets the description of its field.
    """
    from hydromodpy.config.check import check

    flow = solvers.get(flow_key)
    document = _document(tmp_path, flow, {"solver": {flow.name: {"no_solver_has_this_key": 1}}})

    found = check(document, base=tmp_path)

    if flow.options is None:
        assert [d.path for d in found if d.severity == "error"] == [f"solver.{flow.name}"]
        return
    unknown = [d for d in found if d.code == "unknown_key"]
    assert [d.path for d in unknown] == [f"solver.{flow.name}.no_solver_has_this_key"]

    documented = _documented_scalar(flow.options)
    assert documented is not None, f"{flow_key} documents none of its settings"
    keys, description = documented
    table: dict[str, Any] = {keys[-1]: {"not": "a value"}}
    for key in reversed(keys[:-1]):
        table = {key: table}
    document = _document(tmp_path, flow, {"solver": {flow.name: table}})
    (wrong,) = [d for d in check(document, base=tmp_path) if d.severity == "error"]
    assert wrong.path == ".".join(["solver", flow.name, *keys])
    assert wrong.help == description


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


def _transports() -> tuple[str, ...]:
    return tuple(solvers.names("transport"))


@pytest.mark.parametrize("flow_key", _flows())
@pytest.mark.parametrize("transport_name", _transports())
def test_a_transport_loads_if_and_only_if_its_requires_names_the_flow(
    tmp_path: Path, flow_key: str, transport_name: str
) -> None:
    flow = solvers.get(flow_key)
    transport = solvers.get("transport", transport_name)
    process = [
        {"id": "flow_main", "kind": "flow", "solvers": [flow.name]},
        {"id": "transport_main", "kind": "transport", "solvers": [transport_name]},
    ]
    document = _document(tmp_path, flow, {"simulation": {"process": process}})
    missing = [product for product in transport.reads if product not in flow.writes]
    followed = [name for kind, name in transport.requires if kind == "flow"]
    if missing:
        with pytest.raises(
            IncompatibleCapabilitiesError,
            match=f"the transport solver {transport_name!r} reads {missing[0]}",
        ):
            HydroModPyConfig.from_dict(document, base_dir=tmp_path)
    elif followed and flow.name not in followed:
        with pytest.raises(
            ConfigValidationError, match=f"the transport solver {transport_name!r} follows"
        ):
            HydroModPyConfig.from_dict(document, base_dir=tmp_path)
    else:
        HydroModPyConfig.from_dict(document, base_dir=tmp_path)


# ---- behaviour section ----
#
# The cases below build, solve and extract real runs. They play the backends
# this build ships, read from the registry: a backend installed beside the
# build is held to the attributes and the documents above, and only the
# probes of ``PROBES`` can read what a backend wrote, in its own terms.

K_M_S = 5e-6
K_FACTOR = 4.0
RECHARGE_FACTOR = 2.0
K_PATH = "flow.param.K.field.value"
SAMPLED_CELLS = 6
"""Cells whose center ``locate_cell`` must find, spread over the mesh."""


def _mf6_or_nwt_conductivity(solver: Any) -> np.ndarray:
    return np.asarray(solver.hk, dtype=float)


def _boussinesq_conductivity(solver: Any) -> np.ndarray:
    return np.asarray(solver.mesh.hydraulic_conductivity_m_s, dtype=float)


def _mf6_recharge(solver: Any) -> float:
    from hydromodpy.solver.modflow6.builders.recharge import recharge_to_spd

    return float(np.max(np.asarray(recharge_to_spd(solver)[0], dtype=float)))


def _nwt_recharge(solver: Any) -> float:
    return float(np.max(np.asarray(solver.recharge[0], dtype=float)))


def _boussinesq_recharge(solver: Any) -> float:
    from hydromodpy.solver.boussinesq.forcing import BoussinesqForcingResolver

    resolver = BoussinesqForcingResolver(mesh=solver.mesh, inputs=solver.inputs)
    return float(np.max(np.asarray(resolver.resolve_recharge_series(1)[0], dtype=float)))


def _reservoir_recharge(solver: Any) -> float:
    return float(np.max(np.asarray(solver.rates_m_per_s, dtype=float)))


def _reservoir_written_recharge(solved: SolverRun) -> np.ndarray:
    from hydromodpy.solver.linear_reservoir.adapter import SERIES_FILE

    frame = pd.read_csv(solved.output_dir / SERIES_FILE, index_col="time")
    return frame["recharge_m_s"].to_numpy(dtype=float)


@dataclass(frozen=True)
class Probe:
    """What the port reads of one shipped backend, in the backend's own terms.

    ``conductivity`` and ``recharge`` read the solver object a build returns,
    in its own units: only the ratio to another build is compared.
    ``conductivity`` is None for a flow that reads no aquifer property.
    ``refused_property`` is a property name the backend refuses, when it
    refuses one. ``binaries`` are the canonical solver names a solve needs.
    ``tail`` is the TOML a transport reads beside the island.
    ``written_recharge`` reads the recharge a solve wrote, in m/s, one rate per
    piece, for a backend whose output keeps it.
    """

    binaries: tuple[str, ...] = ()
    conductivity: Callable[[Any], np.ndarray] | None = None
    recharge: Callable[[Any], float] | None = None
    refused_property: str | None = None
    tail: str = ""
    written_recharge: Callable[[SolverRun], np.ndarray] | None = None


PROBES: dict[str, Probe] = {
    "flow_modflow6": Probe(("mf6", "libmf6"), _mf6_or_nwt_conductivity, _mf6_recharge),
    "flow_modflow_nwt": Probe(("mfnwt",), _mf6_or_nwt_conductivity, _nwt_recharge),
    "flow_boussinesq": Probe((), _boussinesq_conductivity, _boussinesq_recharge, "Kv"),
    "flow_linear_reservoir": Probe(
        (), None, _reservoir_recharge, written_recharge=_reservoir_written_recharge
    ),
    "transport_modflow6": Probe(("mf6", "libmf6"), tail=TRANSPORT_PARAMETERS),
    "transport_modflow6_prt": Probe(("mf6", "libmf6"), tail=TRANSPORT_TAILS["mf6_prt"]),
    "transport_mt3dms": Probe(("mt3dusgs",), tail=TRANSPORT_TAILS["nwt_mt3dms"]),
    "transport_modpath": Probe(("mp7",), tail=TRANSPORT_TAILS["nwt_modpath"]),
}
"""The one table of this file keyed by backend: the registry key, never a list of names."""


def _shipped(process_type: str) -> tuple[str, ...]:
    return tuple(
        key for key in solvers.names(shipped_only=True) if key.startswith(f"{process_type}_")
    )


FLOW_CASES = [
    pytest.param(key, engine, id=f"{key}-{engine}")
    for key in _shipped("flow")
    for engine in mesh_engines.names()
]
"""Every shipped flow on every mesh engine: a pair the flow does not read is a declared skip."""


def test_the_probes_cover_the_shipped_backends() -> None:
    assert sorted(PROBES) == sorted(solvers.names(shipped_only=True))


def test_the_flow_cases_are_the_flows_times_the_mesh_engines() -> None:
    expected = {(key, engine) for key in _shipped("flow") for engine in mesh_engines.names()}
    assert {tuple(case.values) for case in FLOW_CASES} == expected


def test_a_conductivity_probe_exists_if_and_only_if_the_flow_reads_properties() -> None:
    for key in _shipped("flow"):
        reads = "properties" in solvers.get(key).supports
        assert (PROBES[key].conductivity is not None) is reads, key
        assert PROBES[key].recharge is not None, key


def _digest(value: object) -> str:
    """A digest of a model that walks dataclasses, mappings, sequences and arrays.

    A read-only mapping cannot be pickled, so the model is walked member by member.
    Anything else is read through its dumped fields or its ``repr``. The walk keeps
    every object it has seen alive, because a dumped mapping is a temporary and a
    later one could take the id of a freed one and be read as already seen.
    """
    hasher = hashlib.sha256()
    seen: dict[int, object] = {}

    def feed(item: object) -> None:
        if isinstance(item, np.ndarray):
            hasher.update(f"{item.dtype}{item.shape}".encode())
            if item.dtype == object:
                hasher.update(repr(item.tolist()).encode())
            else:
                hasher.update(np.ascontiguousarray(item).tobytes())
            return
        if item is None or isinstance(item, str | bytes | int | float | bool | complex):
            hasher.update(repr(item).encode())
            return
        if id(item) in seen:
            hasher.update(b"<seen>")
            return
        seen[id(item)] = item
        hasher.update(type(item).__name__.encode())
        if is_dataclass(item) and not isinstance(item, type):
            for member in fields(item):
                hasher.update(member.name.encode())
                feed(getattr(item, member.name))
        elif isinstance(item, Mapping):
            for key in sorted(item, key=repr):
                feed(key)
                feed(item[key])
        elif isinstance(item, list | tuple | set | frozenset):
            for part in item if not isinstance(item, set | frozenset) else sorted(item, key=repr):
                feed(part)
        elif hasattr(item, "model_dump"):
            feed(item.model_dump(mode="python"))
        else:
            hasher.update(repr(item).encode())

    feed(value)
    return hasher.hexdigest()


class _Rate(BaseModel):
    value: float


@dataclass(frozen=True)
class _TwoRates:
    first: _Rate
    second: _Rate


def test_the_digest_tells_two_models_apart_by_their_dumped_members() -> None:
    """Two members dumped one after the other are both read, so a change shows."""
    one = _digest(_TwoRates(_Rate(value=1.0), _Rate(value=2.0)))
    other = _digest(_TwoRates(_Rate(value=1.0), _Rate(value=3.0)))

    assert one != other


def _space() -> ParameterSpace:
    return ParameterSpace.from_toml_mapping({"K": {"bounds": [1e-7, 1e-3], "path": K_PATH}})


def _mesh_table(engine: str) -> dict[str, Any]:
    """The ``[mesh]`` table of the island on one engine."""
    if engine == DEFAULT_ENGINE_ID:
        return {"mesh": {"cell_size": 40.0}}
    return {"mesh": {"engine": engine, "cell_size": 30.0}}


def _island_document(flow: type, engine: str, extra: dict[str, Any] | None = None) -> str:
    """The island solved by ``flow`` on ``engine``, with ``extra`` written over it."""
    text = island_toml(f"port_{flow.name}").replace(
        'solvers = ["modflow6"]', f'solvers = ["{flow.name}"]'
    )
    document = _merged(tomllib.loads(text), _mesh_table(engine))
    return tomli_w.dumps(_merged(document, extra or {}))


@dataclass
class Played:
    """One flow case: its adapter, its ``Model`` and how to build or solve it."""

    key: str
    adapter: Any
    model: Any
    solve_with: Callable[[Any, bool], SolverRun]

    def solve(self, model: Any | None = None, *, solve: bool = False) -> SolverRun:
        """Run the adapter on ``model`` (the case's own by default), stopped before the solve unless asked."""
        return self.solve_with(self.model if model is None else model, solve)


@contextmanager
def _project(
    root: Path,
    files: Mapping[str, str],
    monkeypatch: pytest.MonkeyPatch,
    guard: AbstractContextManager[Any] | None = None,
) -> Iterator[Any]:
    """Yield the context of a project whose flow model was built by the real steps.

    ``guard`` wraps the preparation only, never the body that reads the context.
    """
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    monkeypatch.chdir(root)
    with ExitStack() as stack:
        with guard if guard is not None else nullcontext():
            trial_ctx = prepare_trials(
                root / "project.toml", override_paths=[K_PATH], parameter_space=_space()
            )
            ctx = stack.enter_context(built_model(trial_ctx, {"K": K_M_S}))
        yield ctx


def _solver_of(ctx: Any) -> Callable[[Any, bool], SolverRun]:
    """How the flow adapter of ``ctx`` builds or solves a model in the slot the runner fills."""
    adapter, run_ctx = solver_extract.resolve_flow_adapter(ctx)

    def solve_with(model: Any, solve: bool) -> SolverRun:
        ctx.setup.model = model
        slot = replace(slot_for(run_ctx.plan, run_ctx.run, ctx.setup), stop_before_solve=not solve)
        return solve_one(adapter, model, options_for(adapter, run_ctx.run, ctx.cfg), slot)

    return solve_with


@contextmanager
def _played(
    key: str,
    engine: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    optional_modules: Callable[[str], Any],
) -> Iterator[Played]:
    """Yield one flow case, or skip it when the flow does not read the meshes of ``engine``.

    A lumped engine meshes the catchment as one cell, so its ``Model`` comes
    from the factory: the one polygon cell the catchment engine meshes, two
    pieces of recharge in m/s. Any other engine meshes the island, prepared
    by the real steps up to the model of its flow run.
    """
    flow = solvers.get(key)
    if not engine_accepted(flow.accepted_meshes, engine):
        pytest.skip(
            f"{key} reads the meshes of {sorted(flow.accepted_meshes)}, not those of {engine!r}"
        )
    if mesh_engines.get(engine).capabilities.lumped:
        adapter = solvers.create("flow", flow.name)
        options = None if adapter.options is None else adapter.options(**FLOW_SETTINGS.get(key, {}))
        model = make_model(
            geometry=one_cell_geometry(),
            time=ModelTime(grid=time_grid(5.0, 5.0), regime="transient", first_period_steady=False),
            recharge=FlowRechargeConfig(units="m/s", values=[1.5e-8, 3.0e-8]),
        )

        def solve_with(model: Any, solve: bool) -> SolverRun:
            slot = RunSlot(
                folder=tmp_path / "runs", name=f"port_{flow.name}", stop_before_solve=not solve
            )
            return solve_one(adapter, model, options, slot)

        yield Played(key, adapter, model, solve_with)
        return
    files = {"project.toml": _island_document(flow, engine)}
    guard = optional_modules(f"the mesh engine {engine!r}")
    with _project(tmp_path, files, monkeypatch, guard) as ctx:
        adapter, _ = solver_extract.resolve_flow_adapter(ctx)
        yield Played(key, adapter, ctx.setup.model, _solver_of(ctx))


@pytest.fixture
def played(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    optional_modules: Callable[[str], Any],
) -> Iterator[Played]:
    key, engine = request.param
    with _played(key, engine, tmp_path, monkeypatch, optional_modules) as case:
        yield case


@pytest.mark.parametrize(
    "played",
    [pytest.param(case.values, id=case.id) for case in FLOW_CASES],
    indirect=True,
)
def test_a_solver_keeps_the_model_it_was_given(played: Played) -> None:
    built = played.solve()

    assert built.model is played.model
    inputs = getattr(built.solver_model, "inputs", played.model)
    assert inputs is played.model


@pytest.mark.parametrize(
    "played",
    [pytest.param(case.values, id=case.id) for case in FLOW_CASES],
    indirect=True,
)
def test_a_k_and_a_recharge_set_on_the_model_reach_the_backend(played: Played) -> None:
    probe = PROBES[played.key]
    model = played.model
    base = played.solve().solver_model

    recharge = model.recharge.model_copy(
        update={"values": [RECHARGE_FACTOR * float(value) for value in model.recharge.values]}
    )
    changed = replace(model, recharge=recharge)
    if probe.conductivity is not None:
        changed = replace(model.with_properties(K=K_FACTOR * K_M_S), recharge=recharge)
    solver = played.solve(changed).solver_model

    assert probe.recharge(solver) == pytest.approx(
        RECHARGE_FACTOR * probe.recharge(base), rel=1e-12
    )
    if probe.conductivity is not None:
        np.testing.assert_allclose(
            probe.conductivity(solver), K_FACTOR * probe.conductivity(base), rtol=1e-12
        )
    assert model.properties.overrides == {}


@pytest.mark.parametrize(
    "played",
    [
        pytest.param(case.values, id=case.id)
        for case in FLOW_CASES
        if PROBES[case.values[0]].written_recharge is not None
    ],
    indirect=True,
)
def test_a_solve_writes_the_recharge_the_model_carries_piece_by_piece(played: Played) -> None:
    probe = PROBES[played.key]
    assert played.model.recharge.units == "m/s"
    expected = np.asarray(played.model.recharge.values, dtype=float)

    solved = played.solve(solve=True)

    assert (solved.written, solved.solved) == (True, True)
    np.testing.assert_allclose(probe.written_recharge(solved), expected, rtol=1e-12)


@pytest.mark.parametrize(
    "played",
    [
        pytest.param(case.values, id=case.id)
        for case in FLOW_CASES
        if PROBES[case.values[0]].refused_property is not None
    ],
    indirect=True,
)
def test_a_property_the_backend_does_not_read_is_refused(played: Played) -> None:
    name = PROBES[played.key].refused_property
    model = played.model.with_properties(**{name: K_M_S})

    with pytest.raises(ValueError, match=f"sets {name}, which this solver does not read"):
        played.solve(model)


@pytest.mark.parametrize(
    "played",
    [pytest.param(case.values, id=case.id) for case in FLOW_CASES],
    indirect=True,
)
def test_a_name_that_is_no_property_is_refused_by_the_model(played: Played) -> None:
    with pytest.raises(ValueError, match="K_22 name no flow property"):
        played.model.with_properties(K_22=K_M_S)


@pytest.mark.parametrize(
    "played",
    [pytest.param(case.values, id=case.id) for case in FLOW_CASES],
    indirect=True,
)
def test_a_build_leaves_the_model_as_it_found_it(played: Played) -> None:
    model = played.model
    if PROBES[played.key].conductivity is not None:
        model = model.with_properties(K=K_FACTOR * K_M_S)
    before = _digest(model)

    played.solve(model)

    assert _digest(model) == before


@pytest.mark.parametrize(
    "played",
    [pytest.param(case.values, id=case.id) for case in FLOW_CASES],
    indirect=True,
)
def test_a_build_that_stops_before_the_solve_lies_in_its_slot_unsolved(played: Played) -> None:
    built = played.solve()

    assert (built.written, built.solved) == (False, False)
    assert built.model is played.model
    assert built.solver_model is not None
    where = getattr(built.solver_model, "full_path", None)
    if where is not None:
        assert Path(where).resolve() == built.slot.directory.resolve()


@pytest.mark.binary
@pytest.mark.parametrize(
    "played",
    [pytest.param(case.values, id=case.id) for case in FLOW_CASES],
    indirect=True,
)
def test_a_solve_leaves_the_model_as_it_found_it_and_writes_into_its_slot(
    played: Played, require_binaries: Callable[[Iterable[str], str], None]
) -> None:
    require_binaries(PROBES[played.key].binaries, played.key)
    before = _digest(played.model)

    solved = played.solve(solve=True)

    assert _digest(played.model) == before
    assert (solved.written, solved.solved) == (True, True)
    assert solved.output_dir is not None
    assert solved.output_dir.resolve() == solved.slot.directory.resolve()


def _extracted(
    adapter: Any, run: SolverRun, root: Path, name: str, retention: Retention
) -> set[str]:
    """Extract ``run`` into a fresh run store and return the names the extract added.

    A name outside ``writes`` raises ``DataContractViolation``, as in the pipeline.
    """
    store = open_run_store(root, name, create_zarr=False, solver=adapter.name)
    before = stored_names(store.run_dir)
    adapter.extract(run, store, retention)
    added = set(stored_names(store.run_dir) - before)
    refuse_undeclared(added, adapter.writes, backend=adapter.name)
    return added


def _budget_gap(run_dir: Path) -> float:
    """The largest ``|in - out| / max(in, out)`` of the domain budget over the steps of a run."""
    table = pd.read_parquet(run_dir / TABLES_DIRNAME / f"budgets{PARQUET_FILE_SUFFIX}")
    totals = table.groupby("timestep")[["flux_in", "flux_out"]].sum()
    scale = totals.max(axis=1).where(lambda value: value > 0.0, 1.0)
    return float(((totals["flux_in"] - totals["flux_out"]).abs() / scale).max())


NOTHING_KEPT = Retention(level="result", budget=BudgetKeep.of_terms(()))
EVERYTHING_KEPT = Retention(level="result", budget=BudgetKeep.everything(), face_flows=True)


@pytest.mark.binary
@pytest.mark.parametrize(
    "played",
    [pytest.param(case.values, id=case.id) for case in FLOW_CASES],
    indirect=True,
)
def test_the_extract_writes_what_the_flow_declares_and_the_retention_keeps(
    played: Played, tmp_path: Path, require_binaries: Callable[[Iterable[str], str], None]
) -> None:
    """Only names of ``writes``, the per-cell budget and the face flow only when kept, a closed budget."""
    require_binaries(PROBES[played.key].binaries, played.key)
    solved = played.solve(solve=True)
    writes = played.adapter.writes
    root = tmp_path / "stores"

    lean = _extracted(played.adapter, solved, root, "lean", NOTHING_KEPT)
    full = _extracted(played.adapter, solved, root, "full", EVERYTHING_KEPT)

    assert lean and full
    assert not any(name.startswith(BUDGET_GROUP) for name in lean)
    assert FACE_FLOW not in lean
    declares_a_budget = any(name.startswith(BUDGET_GROUP) for name in writes)
    assert any(name.startswith(BUDGET_GROUP) for name in full) is declares_a_budget
    assert (FACE_FLOW in full) is (FACE_FLOW in writes)
    if "budgets" in writes:
        assert "budgets" in full
        assert _budget_gap(root / "runs" / "full") <= tol("global_water_budget_closure")


@pytest.mark.parametrize(
    "played",
    [pytest.param(case.values, id=case.id) for case in FLOW_CASES],
    indirect=True,
)
def test_a_cell_center_is_located_in_its_own_cell(played: Played) -> None:
    """``locate_cell`` names the cell that holds a point, read back on the mesh of the ``Model``.

    A selector is ``(layer, row, col)``: a structured mesh numbers its cells row
    by row, any other mesh puts the cell id in ``col`` with row 0.
    """
    built = played.solve()
    cells = played.model.geometry.cells
    columns = cells.structured_shape[1] if cells.structured_shape is not None else 0
    count = len(cells.centers)

    for index in np.unique(np.linspace(0, count - 1, SAMPLED_CELLS).astype(int)):
        x, y = (float(value) for value in cells.centers[index][:2])
        selector = played.adapter.locate_cell(built, x, y)
        assert selector is not None, (index, x, y)
        layer, row, col = selector
        assert layer >= 0
        assert row * columns + col == index, (index, selector)


TRANSPORT_CASES = [pytest.param(key, id=key) for key in _shipped("transport")]


def test_the_transport_cases_are_the_shipped_transports() -> None:
    assert [case.values[0] for case in TRANSPORT_CASES] == list(_shipped("transport"))


def _store_head(run_dir: Path) -> np.ndarray:
    return zarr.open_group(run_dir / FIELDS_STORE_NAME, mode="r")["head"][...]


@pytest.mark.binary
@pytest.mark.parametrize("key", TRANSPORT_CASES)
def test_a_transport_follows_its_flow_and_writes_only_what_it_declares(
    key: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    require_binaries: Callable[[Iterable[str], str], None],
) -> None:
    """The flow is the first that ``requires`` names, on the island, then the transport follows it.

    The flow hands off what the transport reads. The transport adds to the store
    only names of its ``writes``, and the head of the flow run reads the same
    after the transport as before it.
    """
    transport = solvers.get(key)
    flow_name = next(name for kind, name in transport.requires if kind == "flow")
    flow_key = f"flow_{flow_name}"
    flow = solvers.get(flow_key)
    assert engine_accepted(flow.accepted_meshes, DEFAULT_ENGINE_ID)
    require_binaries((*PROBES[flow_key].binaries, *PROBES[key].binaries), key)
    text = transport_island(
        f"port_{transport.name}", flow.name, transport.name, tail=PROBES[key].tail
    )
    stores = tmp_path / "stores"

    with _project(tmp_path / "project", {"project.toml": text}, monkeypatch) as ctx:
        plan = ctx.execution.simulation_plan
        model = ctx.setup.model
        done: dict[str, SolverRun] = {}
        flow_slot = transport_run = None
        for run in plan.runs:
            if run.process_type == "mesh":
                continue
            adapter = solvers.create(run.process_type, run.solver)
            upstream = tuple(done[name] for name in run.depends_on)
            slot = replace(
                slot_for(plan, run, ctx.setup, upstream=upstream), stop_before_solve=False
            )
            options = options_for(adapter, run, ctx.cfg)
            done[run.id] = solve_one(adapter, model, options, slot, upstream)
            if run.process_type == "flow":
                flow_slot, flow_adapter, flow_run = slot, adapter, done[run.id]
                _extracted(adapter, flow_run, stores, "flow_before", EVERYTHING_KEPT)
                head_before = _store_head(stores / "runs" / "flow_before")
            else:
                transport_run = done[run.id]
                added = _extracted(adapter, transport_run, stores, "transport", EVERYTHING_KEPT)

        assert flow_slot is not None and transport_run is not None
        assert set(transport.reads) <= flow_slot.hand_off
        assert added
        _extracted(flow_adapter, flow_run, stores, "flow_after", EVERYTHING_KEPT)
        np.testing.assert_array_equal(_store_head(stores / "runs" / "flow_after"), head_before)


ISLAND_BOUNDARIES: dict[str, dict[str, Any]] = {
    **{name: TRAIT_DOCUMENTS[name] for name in FLOW_BOUNDARY_DEFINITIONS},
    "stream": _flow(bc={"stream": {"value": "10 m", "support_label": "west_side"}}),
}
"""The table of each boundary on the island. The island holds no stream line, so the
stream boundary reads the cells of its west side."""

VALLEY_BOUNDARIES = frozenset({"lake", "sfr"})
"""The boundaries the island cannot carry: a lake needs its polygon and abacus, a
stream network its valley. They build on the Cheze valley, which holds both."""

CHEZE_DATA = REPO_ROOT / "tests" / "data" / "sfr_cheze"

SEA_LEVEL = "0.0 m"
"""The head of the sea around the island, ``[flow.bc.ocean]`` of its document."""

BOUNDARY_CASES = [
    pytest.param(boundary, key, id=f"{boundary}-{key}")
    for boundary in FLOW_BOUNDARY_DEFINITIONS
    for key in _shipped("flow")
]


def test_the_boundary_cases_are_the_boundaries_times_the_flows() -> None:
    expected = {(name, key) for name in FLOW_BOUNDARY_DEFINITIONS for key in _shipped("flow")}
    assert {tuple(case.values) for case in BOUNDARY_CASES} == expected
    assert set(ISLAND_BOUNDARIES) == set(FLOW_BOUNDARY_DEFINITIONS)


def _first_engine(flow: type) -> str:
    """The first mesh engine of the registry whose meshes ``flow`` reads."""
    return next(
        engine for engine in mesh_engines.names() if engine_accepted(flow.accepted_meshes, engine)
    )


def _valley_document(flow: type) -> str:
    """The Cheze valley solved by ``flow``."""
    document = tomllib.loads(cheze_valley_files(str(CHEZE_DATA))["project.toml"])
    for process in document["simulation"]["process"]:
        if process["kind"] == "flow":
            process["solvers"] = [flow.name]
    return tomli_w.dumps(document)


@pytest.mark.parametrize(("boundary", "key"), BOUNDARY_CASES)
def test_a_boundary_the_flow_supports_reaches_its_build(
    boundary: str,
    key: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    optional_modules: Callable[[str], Any],
) -> None:
    """A boundary outside ``supports`` is a refusal, held in ``tests/refusals``."""
    flow = solvers.get(key)
    if boundary not in flow.supports:
        pytest.skip(f"{key} does not list {boundary!r} in supports: its refusal is a refusal test")
    if boundary in VALLEY_BOUNDARIES:
        text = _valley_document(flow)
    else:
        engine = _first_engine(flow)
        if mesh_engines.get(engine).capabilities.lumped:
            pytest.skip(f"{key} reads one lumped cell, which carries no {boundary!r} boundary")
        text = _island_document(flow, engine, ISLAND_BOUNDARIES[boundary])

    guard = optional_modules(f"the mesh of {key}")
    with _project(tmp_path, {"project.toml": text}, monkeypatch, guard) as ctx:
        built = _solver_of(ctx)(ctx.setup.model, False)

    assert boundary in ctx.setup.model.boundaries.active_ids
    assert (built.written, built.solved) == (False, False)


def _open_on_the_island(key: str) -> tuple[str, ...]:
    """The boundaries the island carries that ``key`` supports."""
    supports = solvers.get(key).supports
    return tuple(
        name
        for name in FLOW_BOUNDARY_DEFINITIONS
        if name in supports and name not in VALLEY_BOUNDARIES
    )


@pytest.mark.binary
@pytest.mark.parametrize(
    "key", [pytest.param(key, id=key) for key in _shipped("flow") if _open_on_the_island(key)]
)
def test_a_flow_with_all_its_island_boundaries_open_closes_its_budget(
    key: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    optional_modules: Callable[[str], Any],
    require_binaries: Callable[[Iterable[str], str], None],
) -> None:
    """One solve per flow, every boundary it supports on the island at once.

    The prescribed heads share cells where a side meets the sea, so each one
    holds the sea level of the island, and the cells they share agree.
    """
    require_binaries(PROBES[key].binaries, key)
    flow = solvers.get(key)
    extra: dict[str, Any] = {}
    for name in _open_on_the_island(key):
        extra = _merged(extra, ISLAND_BOUNDARIES[name])
        if FLOW_BOUNDARY_DEFINITIONS[name].family == "dirichlet":
            extra = _merged(extra, _flow(bc={name: {"value": SEA_LEVEL}}))
    text = _island_document(flow, _first_engine(flow), extra)

    guard = optional_modules(f"the mesh of {key}")
    with _project(tmp_path / "project", {"project.toml": text}, monkeypatch, guard) as ctx:
        adapter, _ = solver_extract.resolve_flow_adapter(ctx)
        solved = _solver_of(ctx)(ctx.setup.model, True)
        _extracted(adapter, solved, tmp_path / "stores", "open", EVERYTHING_KEPT)

    assert set(_open_on_the_island(key)) <= set(ctx.setup.model.boundaries.active_ids)
    assert _budget_gap(tmp_path / "stores" / "runs" / "open") <= tol("global_water_budget_closure")


# ---- installed-probe section ----
#
# The solver conformance suite runs a backend it does not name.
#
# ``register()`` certifies a backend on the attributes it declares. Whether each
# declared name means something to the build (a mesh engine, a stored field, a
# trait of the ``Model``, an extractor for its key) is only seen by the cases of
# this file, so this section installs a backend the suite has never heard of
# and runs the file against it in a subprocess. The probe solves nothing: it
# spells out the five members a runner calls and the two cell lookups of a
# flow, with the arguments the Protocol names, and no optional member. What
# passes here is the plumbing (discovered under the join of ``process_type`` and
# ``name``, held to the port), not a solver, so the behaviour section plays the
# shipped backends only. The probe declares a settings class and two traits, so
# the suite also shows that the TOML accepts its name, reads its
# ``[solver.<name>]`` table by that class, refuses an unknown key of the table,
# and refuses every trait it does not list.
#
# Two controls. A probe published under a name that is not that join is ignored,
# with a warning naming what the class declares. A probe that declares a stored
# name nothing writes passes the registry and fails the suite.
#
# A subprocess, because ``importlib.metadata`` reads the entry points once and the
# registries cache them. One worker runs the section, so each collection runs once.

CONFORMANCE_SUITE = "tests/ports/test_solver.py"

PROBE_KEY = "flow_conformance_probe"
"""The key the installed distribution answers to, written nowhere but here."""

BROKEN_KEY = "flow_conformance_probe_unread"

MISNAMED_ENTRY = "flow_conformanceprobe"
"""An entry-point name that drops the underscore of the probe's name."""

PROBE_MODULE = '''\
"""An out-of-tree flow backend and its extractor, as a third party would ship them.

Every attribute of the port is spelled out, so an attribute added to the Protocol
breaks this probe instead of being inherited in silence.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class ProbeOptions(BaseModel):
    """The settings of the probe, read from its [solver.conformance_probe] table."""

    model_config = ConfigDict(extra="forbid")

    steps: int = Field(3, description="Steps the probe takes in one period.")


class ProbeFlowAdapter:
    name: ClassVar[str] = "conformance_probe"
    process_type: ClassVar[str] = "flow"
    accepted_meshes: ClassVar[frozenset[str]] = frozenset({"regular"})
    geometry: ClassVar[str] = "cells"
    writes: ClassVar[tuple[str, ...]] = ("head", "budget/recharge", "budgets")
    reads: ClassVar[tuple[str, ...]] = ()
    supports: ClassVar[frozenset[str]] = frozenset({"head_rule", "steady_start"})
    options: ClassVar = ProbeOptions
    category: ClassVar[str] = "distributed"
    native_step: ClassVar = None
    mutable: ClassVar[frozenset[str]] = frozenset()
    requires: ClassVar[tuple[tuple[str, str], ...]] = ()

    def validate(self, model, options, slot):
        raise NotImplementedError

    def build(self, model, options, slot, upstream):
        raise NotImplementedError

    def run(self, solver_run):
        raise NotImplementedError

    def cleanup(self, solver_run):
        raise NotImplementedError

    def extract(self, solver_run, store, retention):
        raise NotImplementedError

    def locate_cell(self, solver_run, x, y):
        raise NotImplementedError

    def top_active_layer(self, solver_run, row, col):
        raise NotImplementedError


class ProbeExtractor:
    process_type: ClassVar[str] = "flow"
    solver_name: ClassVar[str] = "conformance_probe"

    def extract(self, *args, **kwargs):
        raise NotImplementedError
'''

BROKEN_PROBE_TAIL = '''

class UnreadFlowAdapter(ProbeFlowAdapter):
    """Passes the registry and declares a field nothing stores. The negative control."""

    name = "conformance_probe_unread"
    writes = ("head", "budget/seepage_to_nowhere")


class UnreadExtractor(ProbeExtractor):
    solver_name = "conformance_probe_unread"
'''


def _publish(root: Path, entry: str, adapter: str, extractor: str, *, tail: str = "") -> Path:
    """Unpack the probe publishing *adapter* under *entry*, and its extractor beside it."""
    unpack(root, "hmp_solver_conformance_probe", PROBE_MODULE + tail, "hydromodpy.solver", entry, adapter)  # fmt: skip
    entry_points = next(root.glob("*.dist-info")) / "entry_points.txt"
    with entry_points.open("a", encoding="utf-8") as stream:
        stream.write(
            f"\n[hydromodpy.solver.extractor]\n{entry} = hmp_solver_conformance_probe:{extractor}\n"
        )
    return root


@pytest.fixture(scope="module")
def installed_probe(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("probe_site_packages")
    return _publish(root, PROBE_KEY, "ProbeFlowAdapter", "ProbeExtractor")


@pytest.fixture(scope="module")
def installed_broken_probe(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("broken_probe_site_packages")
    return _publish(
        root, BROKEN_KEY, "UnreadFlowAdapter", "UnreadExtractor", tail=BROKEN_PROBE_TAIL
    )


@pytest.fixture(scope="module")
def installed_misnamed_probe(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("misnamed_probe_site_packages")
    return _publish(root, MISNAMED_ENTRY, "ProbeFlowAdapter", "ProbeExtractor")


@pytest.fixture(scope="module")
def bare_collection(tmp_path_factory) -> subprocess.CompletedProcess:
    return run_suite(CONFORMANCE_SUITE, tmp_path_factory.mktemp("bare"), "--collect-only", "-q")


@pytest.fixture(scope="module")
def probe_collection(installed_probe, tmp_path_factory) -> subprocess.CompletedProcess:
    session = tmp_path_factory.mktemp("probe_collect")
    return run_suite(
        CONFORMANCE_SUITE, session, "--collect-only", "-q", site_packages=installed_probe
    )


def _names_seen_by_a_child(site_packages: Path) -> subprocess.CompletedProcess:
    """List ``solvers.names("flow")`` and the registry warnings in a child interpreter."""
    script = (
        "import logging, sys\n"
        "from hydromodpy.core import plugin_registry\n"
        "plugin_registry.logger.addHandler(logging.StreamHandler(sys.stdout))\n"
        "from hydromodpy.solver.base.registry import solvers\n"
        "print(' '.join(solvers.names('flow')))\n"
    )
    environment = dict(os.environ)
    entries = [site_packages, REPO_ROOT, environment.get("PYTHONPATH")]
    environment["PYTHONPATH"] = os.pathsep.join(str(entry) for entry in entries if entry)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.mark.xdist_group("solver_conformance_probe")
def test_installing_a_backend_adds_it_to_the_suite(bare_collection, probe_collection) -> None:
    """The probe adds its own parameter set and changes no other node (bare is the control)."""
    without, with_probe = bare_collection, probe_collection
    assert without.returncode == 0, without.stdout[-4000:]
    assert collected(without.stdout, CONFORMANCE_SUITE, PROBE_KEY) == []
    assert with_probe.returncode == 0, with_probe.stdout[-4000:]
    probe_nodes = collected(with_probe.stdout, CONFORMANCE_SUITE, PROBE_KEY)
    assert probe_nodes, with_probe.stdout[-4000:]
    added = len(collected(with_probe.stdout, CONFORMANCE_SUITE)) - len(
        collected(without.stdout, CONFORMANCE_SUITE)
    )
    assert added == len(probe_nodes), "the probe may only add its own parameter set"


PROBE_SETS = (
    "test_the_toml_accepts_the_name_of_each_flow",
    "test_the_settings_of_a_flow_read_back_from_its_own_table",
    "test_an_unknown_key_of_a_flow_table_is_refused",
    "test_a_document_that_uses_a_trait_loads_if_and_only_if_the_flow_lists_it",
    "test_a_transport_loads_if_and_only_if_its_requires_names_the_flow",
)
"""The cases of the suite that read a TOML, which the probe must reach as a flow."""


@pytest.mark.xdist_group("solver_conformance_probe")
def test_the_probe_reaches_every_case_that_reads_a_toml(probe_collection) -> None:
    probe_nodes = collected(probe_collection.stdout, CONFORMANCE_SUITE, PROBE_KEY)
    for case in PROBE_SETS:
        assert any(f"::{case}[" in node for node in probe_nodes), case


@pytest.mark.xdist_group("solver_conformance_probe")
def test_every_conformance_assertion_passes_against_the_installed_backend(
    installed_probe, probe_collection, tmp_path
) -> None:
    """The gate: the whole parameter set of a backend this file never names."""
    probe_nodes = collected(probe_collection.stdout, CONFORMANCE_SUITE, PROBE_KEY)
    result = run_suite(
        CONFORMANCE_SUITE, tmp_path / "probe", "-q", "-k", PROBE_KEY, site_packages=installed_probe
    )
    assert result.returncode == 0, result.stdout[-8000:]
    passed = re.search(r"(\d+) passed", result.stdout)
    assert passed is not None, result.stdout[-4000:]
    assert int(passed.group(1)) == len(probe_nodes)


@pytest.mark.xdist_group("solver_conformance_probe")
def test_a_backend_the_registry_accepts_and_the_store_cannot_read_is_caught(
    installed_broken_probe, tmp_path
) -> None:
    """The negative control: ``register()`` accepts it, and the suite fails it on ``writes``."""
    registered = run_suite(
        CONFORMANCE_SUITE,
        tmp_path / "collect",
        "--collect-only",
        "-q",
        site_packages=installed_broken_probe,
    )
    assert collected(registered.stdout, CONFORMANCE_SUITE, BROKEN_KEY), "accepted by the registry, or it proves nothing"  # fmt: skip
    result = run_suite(CONFORMANCE_SUITE, tmp_path / "run", "-q", "-k", BROKEN_KEY, site_packages=installed_broken_probe)  # fmt: skip
    assert result.returncode != 0
    assert "test_each_written_name_is_known_to_the_store" in result.stdout


@pytest.mark.xdist_group("solver_conformance_probe")
def test_an_entry_point_that_does_not_join_the_key_is_ignored_with_its_warning(
    installed_misnamed_probe,
) -> None:
    """``flow_conformanceprobe`` is not ``flow`` joined to ``conformance_probe``: no key is minted."""
    result = _names_seen_by_a_child(installed_misnamed_probe)

    assert result.returncode == 0, result.stderr[-4000:]
    flows = result.stdout.strip().splitlines()[-1].split()
    assert "conformance_probe" not in flows
    assert "conformanceprobe" not in flows
    assert f"the entry-point name is {MISNAMED_ENTRY!r}" in result.stdout
    assert "declares process_type, name = 'flow', 'conformance_probe'" in result.stdout


@pytest.mark.xdist_group("solver_conformance_probe")
def test_the_conformance_suite_neither_names_nor_imports_the_backend_it_runs() -> None:
    """The import check is a tripwire (aliases included), not a proof."""
    suite = _suite_proper()
    imported = {
        alias.name.rpartition(".")[2]
        for node in ast.walk(ast.parse(suite))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    # ``SolverAdapter`` is the Protocol the suite asserts membership of.
    adapters = sorted(
        name for name in imported if name.endswith("Adapter") and name != "SolverAdapter"
    )

    assert "conformance_probe" not in suite
    assert adapters == [], f"the suite imports {adapters} instead of asking the registry"


def _suite_proper() -> str:
    """This file up to the probe section, which is what the suite proper says."""
    text = (REPO_ROOT / CONFORMANCE_SUITE).read_text(encoding="utf-8")
    return text.split("# ---- installed-probe section ----")[0]
