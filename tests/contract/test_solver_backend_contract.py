"""Conformance suite for the solver port, run against every backend the registry serves.

Each test takes the ``key`` fixture, parametrized over ``solvers.names()`` and not
over a list this file keeps, so a backend installed beside the build through the
``hydromodpy.solver`` group is held to the port without a line of ``tests/``
naming it. ``register()`` already refuses an absent attribute and a wrong type.
This file checks what only the rest of the build can say: that every name a
backend declares means something to the registries, the field registry, the
budget terms, the table schemas and the traits of ``model/supports.py``.

The supports of the three shipped flows are written here as the expected lists,
because the configuration refuses a boundary kind, a restart and a cyclic
spin-up from them. Until the boundary table loses its ``supported_backends``
column, the boundary kinds of a flow must equal that column.
"""

from __future__ import annotations

from fnmatch import fnmatchcase

import pytest
from pandas.tseries.frequencies import to_offset
from pydantic import BaseModel

from hydromodpy.core.budget.terms import PER_CELL_BUDGET_TERMS
from hydromodpy.mesh.port import ANY_PLANAR_ENGINE
from hydromodpy.mesh.registry import mesh_engines
from hydromodpy.model.boundaries.boundary_condition_registry import FLOW_BOUNDARY_DEFINITIONS
from hydromodpy.model.supports import SUPPORT_SOURCES, SUPPORTS
from hydromodpy.results.catalog.constants import solver_category
from hydromodpy.results.field_registry import BUDGET_GROUP, all_zarr_paths
from hydromodpy.results.storage.parquet_schemas import VIEW_SCHEMAS
from hydromodpy.solver.base.adapter_protocol import CATEGORIES, GEOMETRIES, SolverAdapter
from hydromodpy.solver.base.registry import extractors, solvers

UNDESCRIBED_GROUPS = ("particles/", "boussinesq_state/", "lake_state_final/", "lake_abacus/")
"""The four Zarr groups the field registry does not describe name by name.

``lake_state_final/`` and ``lake_abacus/`` sit outside the pipeline groups and
only the MODFLOW 6 extractor writes them. A later run reads the first back as
its prior lake stages.
"""

_HEAD_START = frozenset({"head_rule", "steady_start"})
_OPTIONS = SUPPORT_SOURCES["option"]

SHIPPED_SUPPORTS: dict[str, frozenset[str]] = {
    "flow_modflow6": SUPPORT_SOURCES["boundary"]
    | _OPTIONS
    | _HEAD_START
    | {"cyclic_start", "prior_state"},
    "flow_modflow_nwt": frozenset(
        {"west_side", "east_side", "north_side", "south_side", "ocean", "drainage"}
    )
    | _OPTIONS
    | _HEAD_START,
    "flow_boussinesq": frozenset(
        {"west_side", "east_side", "north_side", "south_side", "stream", "ocean", "drainage"}
    )
    | {"drain_bed_thickness_m"}
    | _HEAD_START,
    "transport_modflow6": frozenset(),
    "transport_modflow6_prt": frozenset(),
    "transport_mt3dms": frozenset(),
    "transport_modpath": frozenset(),
}
"""What each shipped backend honours: MODFLOW 6 all 17 traits, NWT 12, Boussinesq 10.

Only MODFLOW 6 reads a prior run and starts cyclic, and Boussinesq reads one
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


def test_the_boundary_kinds_of_a_flow_agree_with_the_boundary_table(backend: type) -> None:
    """The configuration still refuses a boundary from ``supported_backends``."""
    if backend.process_type != "flow":
        return
    from_table = {
        kind
        for kind, definition in FLOW_BOUNDARY_DEFINITIONS.items()
        if definition.supports_backend(backend.name)
    }
    assert backend.supports & SUPPORT_SOURCES["boundary"] == from_table


def test_options_is_a_pydantic_class_or_none(backend: type) -> None:
    options = backend.options
    assert options is None or (isinstance(options, type) and issubclass(options, BaseModel))


def test_native_step_is_none_or_a_pandas_frequency(backend: type) -> None:
    if backend.native_step is not None:
        to_offset(backend.native_step)


def test_mutable_names_are_strings(backend: type) -> None:
    assert isinstance(backend.mutable, frozenset)
    assert all(isinstance(name, str) for name in backend.mutable)


def test_an_extractor_reads_back_each_backend(key: str) -> None:
    """An adapter without an extractor solves, then loses the run at ingestion."""
    assert key in extractors.names()
    assert callable(getattr(extractors.get(key), "extract", None))
