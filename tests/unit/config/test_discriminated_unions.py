"""Discriminated union dispatch tests for DataSource, SolverConfig, SimulationProcessConfig."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from hydromodpy.data.variables.dem.config import (
    CustomDemSource,
    DemSourceConfig,
    IgnGeoplateformeDemSource,
)
from hydromodpy.data.variables.geology.config import (
    BrgmGeology1mSource,
    BrgmGeology50kSource,
    CustomGeologySource,
    GeologySourceConfig,
)
from hydromodpy.solver.base.simulation_config import (
    FlowProcessConfig,
    MeshProcessConfig,
    SimulationProcessConfig,
    TransportProcessConfig,
)
from hydromodpy.solver.base.solver_config import SolverConfig
from tests._helpers.fake_solvers import fake_adapter

pytestmark = pytest.mark.fast


# ---------------------------------------------------------------------------
# DataSource axis (DEM + Geology variants share the 'source' discriminator)
# ---------------------------------------------------------------------------


class TestDataSourceUnion:
    DISPATCH_CASES = [
        pytest.param(
            DemSourceConfig,
            {"source": "custom", "path": "dem.tif"},
            CustomDemSource,
            {"source": "custom"},
            id="dem_custom",
        ),
        pytest.param(
            DemSourceConfig,
            {"source": "ign_geoplateforme_dem", "dataset": "bd-alti", "resolution_m": 25.0},
            IgnGeoplateformeDemSource,
            {"source": "ign_geoplateforme_dem", "dataset": "bd-alti"},
            id="dem_ign_geoplateforme",
        ),
        pytest.param(
            DemSourceConfig,
            {"source": "ign_geoplateforme_dem", "dataset": "rge-alti", "resolution_m": 5.0},
            IgnGeoplateformeDemSource,
            {"source": "ign_geoplateforme_dem", "dataset": "rge-alti"},
            id="dem_ign_geoplateforme_rge_alti",
        ),
        pytest.param(
            GeologySourceConfig,
            {"source": "brgm_1m"},
            BrgmGeology1mSource,
            {},
            id="geology_brgm_1m",
        ),
        pytest.param(
            GeologySourceConfig,
            {"source": "brgm_50k"},
            BrgmGeology50kSource,
            {},
            id="geology_brgm_50k",
        ),
    ]

    @pytest.mark.parametrize(
        ("union", "payload", "expected_type", "expected_attrs"), DISPATCH_CASES
    )
    def test_variant_dispatch(self, union, payload, expected_type, expected_attrs) -> None:
        ta = TypeAdapter(union)
        instance = ta.validate_python(payload)
        assert isinstance(instance, expected_type)
        for attr, value in expected_attrs.items():
            assert getattr(instance, attr) == value

    REJECT_CASES = [
        pytest.param(DemSourceConfig, {"source": "missing"}, id="dem_unknown_source"),
        pytest.param(
            DemSourceConfig,
            {"source": "ign_bdalti", "resolution_m": 25.0},
            id="dem_ign_bdalti_legacy_source_rejected",
        ),
        pytest.param(
            DemSourceConfig,
            {"source": "ign_geoplateforme_dem", "dataset": "rge-alti", "resolution_m": 25.0},
            id="dem_geoplateforme_rge_alti_25m_rejected",
        ),
    ]

    @pytest.mark.parametrize(("union", "payload"), REJECT_CASES)
    def test_variant_rejected(self, union, payload) -> None:
        ta = TypeAdapter(union)
        with pytest.raises(ValidationError):
            ta.validate_python(payload)

    def test_dem_custom_requires_path(self) -> None:
        with pytest.raises(ValidationError):
            CustomDemSource()

    def test_geology_custom_construction(self, tmp_path) -> None:
        cfg = CustomGeologySource(path=tmp_path / "g.gpkg", code_field="LITHOLOGY")
        assert cfg.source == "custom"
        assert cfg.code_field == "LITHOLOGY"


# ---------------------------------------------------------------------------
# SolverConfig axis: no union any more, the backend is a registered name
# ---------------------------------------------------------------------------


class TestSolverConfigUnion:
    BACKEND_CASES = [
        pytest.param("modflow6", "modflow6", id="modflow6_backend"),
        pytest.param("modflow_nwt", "modflow_nwt", id="modflow_nwt_backend"),
        pytest.param("boussinesq", "boussinesq", id="boussinesq_backend"),
        pytest.param("PluginSolver", "pluginsolver", id="plugin_backend_by_its_name"),
    ]

    @pytest.mark.parametrize(("backend", "expected_backend_name"), BACKEND_CASES)
    def test_backend_dispatch(self, isolated_solvers, backend, expected_backend_name) -> None:
        isolated_solvers.solvers.register(fake_adapter("pluginsolver"))
        cfg = SolverConfig(backend=backend)
        assert cfg.backend == expected_backend_name
        assert cfg.backend_name == expected_backend_name

    def test_the_table_form_of_2_0_is_read_by_the_migration_only(self) -> None:
        # The loader writes {kind = "modflow_nwt"} as "modflow_nwt" before the model reads it.
        with pytest.raises(ValidationError, match="valid string"):
            SolverConfig(backend={"kind": "modflow_nwt"})

    def test_legacy_solver_engine_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SolverConfig(solver_engine="modflow6")


# ---------------------------------------------------------------------------
# SimulationProcessConfig axis (type discriminator: flow/transport/mesh)
# ---------------------------------------------------------------------------


class TestSimulationProcessUnion:
    DISPATCH_CASES = [
        pytest.param(
            {"id": "flow_main", "kind": "flow", "solvers": ["modflow6"]},
            FlowProcessConfig,
            {"solvers": ["modflow6"]},
            id="flow_variant",
        ),
        pytest.param(
            {"id": "tr1", "kind": "transport", "solvers": ["mt3dms"]},
            TransportProcessConfig,
            {},
            id="transport_variant",
        ),
        pytest.param(
            {"id": "mesh_main", "kind": "mesh"},
            MeshProcessConfig,
            {"backend": "catchment", "solvers": []},
            id="mesh_variant_default_backend",
        ),
    ]

    @pytest.mark.parametrize(("payload", "expected_type", "expected_attrs"), DISPATCH_CASES)
    def test_variant_dispatch(self, payload, expected_type, expected_attrs) -> None:
        ta = TypeAdapter(SimulationProcessConfig)
        instance = ta.validate_python(payload)
        assert isinstance(instance, expected_type)
        for attr, value in expected_attrs.items():
            assert getattr(instance, attr) == value

    REJECT_CASES = [
        pytest.param({"id": "x", "type": "unknown"}, id="unknown_type_rejected"),
        pytest.param({"id": "x", "kind": "mesh", "solvers": ["a"]}, id="mesh_rejects_solvers"),
        pytest.param({"id": "x", "kind": "flow", "solvers": []}, id="flow_requires_solvers"),
    ]

    @pytest.mark.parametrize("payload", REJECT_CASES)
    def test_variant_rejected(self, payload) -> None:
        ta = TypeAdapter(SimulationProcessConfig)
        with pytest.raises(ValidationError):
            ta.validate_python(payload)
