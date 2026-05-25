"""Discriminated union dispatch tests for DataSource, SolverConfig, SimulationProcessConfig."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from hydromodpy.data.variables.dem.config import (
    CustomDemSource,
    DemSourceConfig,
    IgnBdaltiDemSource,
    IgnGeoplateformeDemSource,
)
from hydromodpy.data.variables.geology.config import (
    BrgmGeology1mSource,
    BrgmGeology50kSource,
    CustomGeologySource,
    GeologySourceConfig,
)
from hydromodpy.simulation.planning.config import (
    FlowProcessConfig,
    MeshProcessConfig,
    SimulationProcessConfig,
    TransportProcessConfig,
)
from hydromodpy.solver.base.solver_config import (
    BoussinesqBackend,
    CustomBackend,
    Modflow6Backend,
    ModflowNwtBackend,
    SolverConfig,
)

pytestmark = pytest.mark.fast


# ---------------------------------------------------------------------------
# DataSource axis (DEM + Geology variants share the 'source' discriminator)
# ---------------------------------------------------------------------------


class TestDataSourceUnion:
    def test_dem_custom_variant_dispatch(self, tmp_path) -> None:
        ta = TypeAdapter(DemSourceConfig)
        instance = ta.validate_python({"source": "custom", "path": str(tmp_path / "x.tif")})
        assert isinstance(instance, CustomDemSource)
        assert instance.source == "custom"

    def test_dem_ign_variant_dispatch(self) -> None:
        ta = TypeAdapter(DemSourceConfig)
        instance = ta.validate_python({"source": "ign_bdalti"})
        assert isinstance(instance, IgnBdaltiDemSource)
        assert instance.source == "ign_bdalti"

    def test_dem_ign_geoplateforme_variant_dispatch(self) -> None:
        ta = TypeAdapter(DemSourceConfig)
        instance = ta.validate_python(
            {
                "source": "ign_geoplateforme_dem",
                "dataset": "bd-alti",
                "resolution_m": 25.0,
            }
        )
        assert isinstance(instance, IgnGeoplateformeDemSource)
        assert instance.source == "ign_geoplateforme_dem"
        assert instance.dataset == "bd-alti"

    def test_geology_brgm_variant_dispatch(self) -> None:
        ta = TypeAdapter(GeologySourceConfig)
        c1 = ta.validate_python({"source": "brgm_1m"})
        c2 = ta.validate_python({"source": "brgm_50k"})
        assert isinstance(c1, BrgmGeology1mSource)
        assert isinstance(c2, BrgmGeology50kSource)

    def test_unknown_source_rejected(self) -> None:
        ta = TypeAdapter(DemSourceConfig)
        with pytest.raises(ValidationError):
            ta.validate_python({"source": "missing"})

    def test_dem_custom_requires_path(self) -> None:
        with pytest.raises(ValidationError):
            CustomDemSource()

    def test_geology_custom_construction(self, tmp_path) -> None:
        cfg = CustomGeologySource(path=tmp_path / "g.gpkg", code_field="LITHOLOGY")
        assert cfg.source == "custom"
        assert cfg.code_field == "LITHOLOGY"


# ---------------------------------------------------------------------------
# SolverConfig axis (backend discriminator with custom plugin fallback)
# ---------------------------------------------------------------------------


class TestSolverConfigUnion:
    def test_modflow6_backend(self) -> None:
        cfg = SolverConfig(backend={"backend": "modflow6"})
        assert isinstance(cfg.backend, Modflow6Backend)
        assert cfg.backend_name == "modflow6"

    def test_modflow_nwt_backend(self) -> None:
        cfg = SolverConfig(backend={"backend": "modflow_nwt"})
        assert isinstance(cfg.backend, ModflowNwtBackend)
        assert cfg.backend_name == "modflow_nwt"

    def test_boussinesq_backend(self) -> None:
        cfg = SolverConfig(backend={"backend": "boussinesq"})
        assert isinstance(cfg.backend, BoussinesqBackend)
        assert cfg.backend_name == "boussinesq"

    def test_plugin_backend_via_custom(self) -> None:
        cfg = SolverConfig(backend={"backend": "custom", "name": "pluginsolver"})
        assert isinstance(cfg.backend, CustomBackend)
        assert cfg.backend_name == "pluginsolver"

    def test_discriminated_payload_form(self) -> None:
        cfg = SolverConfig(backend={"backend": "modflow_nwt"})
        assert isinstance(cfg.backend, ModflowNwtBackend)

    def test_legacy_solver_engine_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SolverConfig(solver_engine="modflow6")


# ---------------------------------------------------------------------------
# SimulationProcessConfig axis (type discriminator: flow/transport/mesh)
# ---------------------------------------------------------------------------


class TestSimulationProcessUnion:
    def test_flow_variant_dispatch(self) -> None:
        ta = TypeAdapter(SimulationProcessConfig)
        instance = ta.validate_python({"id": "flow_main", "type": "flow", "solvers": ["modflow6"]})
        assert isinstance(instance, FlowProcessConfig)
        assert instance.solvers == ["modflow6"]

    def test_transport_variant_dispatch(self) -> None:
        ta = TypeAdapter(SimulationProcessConfig)
        instance = ta.validate_python({"id": "tr1", "type": "transport", "solvers": ["mt3dms"]})
        assert isinstance(instance, TransportProcessConfig)

    def test_mesh_variant_default_backend(self) -> None:
        ta = TypeAdapter(SimulationProcessConfig)
        instance = ta.validate_python({"id": "mesh_main", "type": "mesh"})
        assert isinstance(instance, MeshProcessConfig)
        assert instance.backend == "catchment"
        assert instance.solvers == []

    def test_unknown_type_rejected(self) -> None:
        ta = TypeAdapter(SimulationProcessConfig)
        with pytest.raises(ValidationError):
            ta.validate_python({"id": "x", "type": "unknown"})

    def test_mesh_rejects_solvers(self) -> None:
        ta = TypeAdapter(SimulationProcessConfig)
        with pytest.raises(ValidationError):
            ta.validate_python({"id": "x", "type": "mesh", "solvers": ["a"]})

    def test_flow_requires_solvers(self) -> None:
        ta = TypeAdapter(SimulationProcessConfig)
        with pytest.raises(ValidationError):
            ta.validate_python({"id": "x", "type": "flow", "solvers": []})
