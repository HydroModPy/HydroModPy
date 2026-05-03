from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.results.run import Run
from hydromodpy.results.simulation_group import SimulationGroup
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
)


@pytest.fixture
def catalog(tmp_path):
    cat = SimulationCatalog(tmp_path / "workspace")
    yield cat
    cat.close()


def _sid():
    return str(uuid.uuid4())


def _register(catalog, sim_id=None, **kw):
    sid = sim_id or _sid()
    defaults = dict(project="test", solver="modflow6", n_cells=10, n_layers=2)
    defaults.update(kw)
    reg = catalog.register_simulation(sid, **defaults)
    if reg.zarr is not None:
        reg.zarr.close()
    return sid


def _populate(catalog, sid):
    catalog.write_parameters(
        sid,
        [
            {"param_name": "K", "value": 1.5, "unit": "m/d"},
            {"param_name": "Sy", "value": 0.05, "unit": "-"},
        ],
    )
    idx = pd.date_range("2020-01-01", periods=10, freq="D")
    catalog.write_timeseries(sid, "P01", "head", pd.Series(np.arange(10.0), index=idx))
    catalog.write_budget(sid, 0, "z1", "recharge", 100.0, 0.0)
    catalog.write_mass_balance(sid, 0, 100.0, 95.0, 5.0)
    catalog.write_metric(sid, "P01", "nse", 0.85)
    catalog.write_metric(sid, "P01", "kge", 0.78)
    catalog.finalize(sid, "completed", 42.0)


def _write_active_accumulation_flux_case(catalog, sid):
    sz = catalog.open_zarr(sid)
    try:
        mesh = sz.root.require_group("mesh")
        mesh.create_array(
            "surface_top",
            data=np.array([100.0, 100.0, -9999.0, 100.0], dtype="float64"),
            overwrite=True,
        )
        frames = [
            np.array([0.0, 2.0, 9.0, 0.0], dtype="float64"),
            np.array([1.0, 2.0, 9.0, 0.0], dtype="float64"),
            np.array([0.0, 2.0, 9.0, 4.0], dtype="float64"),
        ]
        for timestep, values in enumerate(frames):
            sz.write_field(
                "accumulation_flux",
                timestep,
                values,
                n_timesteps=3 if timestep == 0 else None,
                subgroup="derived",
            )
    finally:
        sz.close()


# ============================================================================
# Simulation class tests
# ============================================================================


class TestSimulationMetadata:
    def test_basic_properties(self, catalog):
        sid = _register(catalog, name="run1", flow_regime="transient")
        sim = Run(sid, catalog)
        assert sim.sim_id == sid
        assert sim.name == "run1"
        assert sim.project == "test"
        assert sim.solver == "modflow6"
        assert sim.solver_category == "distributed"
        assert sim.flow_regime == "transient"
        assert sim.status == "running"

    def test_config_roundtrip(self, catalog):
        cfg = {"flow": {"K": 1.5}}
        sid = _register(catalog, config=cfg)
        sim = Run(sid, catalog)
        assert sim.config_snapshot == cfg

    def test_tags(self, catalog):
        sid = _register(catalog, tags=["fast", "test"])
        sim = Run(sid, catalog)
        assert sim.tags == ["fast", "test"]

    def test_not_found(self, catalog):
        sim = Run("nonexistent-uuid", catalog)
        with pytest.raises(KeyError):
            _ = sim.name


class TestSimulationData:
    def test_parameters(self, catalog):
        sid = _register(catalog)
        _populate(catalog, sid)
        sim = Run(sid, catalog)
        df = sim.parameters
        # Homogeneous-only payload: simple index by param_name, no zone_id.
        assert set(df.index) == {"K", "Sy"}
        assert "value" in df.columns
        assert sim.parameters.loc["K", "value"] == pytest.approx(1.5)

    def test_metrics(self, catalog):
        sid = _register(catalog)
        _populate(catalog, sid)
        sim = Run(sid, catalog)
        df = sim.metrics
        assert len(df) == 2

    def test_timeseries(self, catalog):
        sid = _register(catalog)
        _populate(catalog, sid)
        sim = Run(sid, catalog)
        ts = sim.timeseries("head", station="P01")
        assert len(ts) == 10

    def test_timeseries_not_found(self, catalog):
        sid = _register(catalog)
        sim = Run(sid, catalog)
        with pytest.raises(KeyError):
            sim.timeseries("head", station="NOPE")

    def test_budget(self, catalog):
        sid = _register(catalog)
        _populate(catalog, sid)
        sim = Run(sid, catalog)
        df = sim.budget(component="recharge")
        assert len(df) == 1

    def test_mass_balance(self, catalog):
        sid = _register(catalog)
        _populate(catalog, sid)
        sim = Run(sid, catalog)
        df = sim.mass_balance
        assert len(df) == 1

    def test_provenance(self, catalog):
        sid = _register(catalog)
        catalog.write_provenance(sid, "dem", "dem.tif", np.ones(10))
        sim = Run(sid, catalog)
        df = sim.provenance
        assert len(df) == 1

    def test_hydrographic_network_accessor(self, catalog):
        sid = _register(catalog)
        gdf = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(0.0, 0.0), (1.0, 0.0)])],
            crs="EPSG:2154",
        )
        catalog.write_geographic_feature(sid, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, gdf)

        sim = Run(sid, catalog)
        result = sim.hydrographic_network("reference")

        assert len(result) == 1
        assert result.crs is not None
        assert sim.has_hydrographic_network("reference") is True
        assert sim.has_hydrographic_network("generated") is False
        assert sim.available_hydrographic_network_roles() == ["reference"]
        assert "hydrographic_network_reference" in sim.display_capabilities
        contract = sim.hydrographic_network_naming("reference")
        assert contract["canonical_feature_name"] == HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME
        assert contract["default_vector_filename"] == "streams.shp"

    def test_hydrographic_network_missing_role_reports_available_roles(self, catalog):
        sid = _register(catalog)
        gdf = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(0.0, 0.0), (1.0, 0.0)])],
            crs="EPSG:2154",
        )
        catalog.write_geographic_feature(sid, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, gdf)

        sim = Run(sid, catalog)
        with pytest.raises(KeyError, match="Available roles: reference"):
            sim.hydrographic_network("generated")

    def test_hydrographic_network_comparison_accessor_and_capability(self, catalog):
        sid = _register(catalog)
        reference = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(0.0, 0.0), (1000.0, 0.0)])],
            crs="EPSG:2154",
        )
        generated = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(0.0, 0.0), (800.0, 0.0)])],
            crs="EPSG:2154",
        )
        catalog.write_geographic_feature(
            sid, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, reference
        )
        catalog.write_geographic_feature(
            sid, HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME, generated
        )

        sim = Run(sid, catalog)
        comparison = sim.hydrographic_network_comparison(tolerance_m=25.0)
        metrics = sim.hydrographic_network_comparison_metrics(
            tolerance_m=25.0,
            comparison_id="demo",
        )

        assert comparison.reference_total_length_m == pytest.approx(1000.0)
        assert comparison.candidate_total_length_m == pytest.approx(800.0)
        assert metrics["comparison_id"] == "demo"
        assert metrics["reference_total_length_m"] == pytest.approx(1000.0)
        assert metrics["candidate_total_length_m"] == pytest.approx(800.0)
        assert "hydrographic_network_reference" in sim.display_capabilities
        assert "hydrographic_network_generated" in sim.display_capabilities
        assert "hydrographic_network_comparison" in sim.display_capabilities
        assert "hydrographic_network_reference_missing_only" in sim.display_capabilities
        assert "hydrographic_network_generated_extra_only" in sim.display_capabilities
        generated_contract = sim.hydrographic_network_naming("generated")
        assert (
            generated_contract["canonical_feature_name"]
            == HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME
        )
        assert generated_contract["legacy_feature_name"] == "river_network"

    def test_hydrographic_network_comparison_requires_both_roles(self, catalog):
        sid = _register(catalog)
        reference = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(0.0, 0.0), (1000.0, 0.0)])],
            crs="EPSG:2154",
        )
        catalog.write_geographic_feature(
            sid, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, reference
        )

        sim = Run(sid, catalog)
        with pytest.raises(
            ValueError,
            match="requires both requested roles to be present.*Missing: generated",
        ):
            sim.hydrographic_network_comparison(tolerance_m=25.0)

    def test_simulated_active_network_metrics_from_accumulation_flux(self, catalog):
        sid = _register(catalog, n_cells=4, n_layers=1, n_timesteps=3)
        _write_active_accumulation_flux_case(catalog, sid)

        sim = Run(sid, catalog)
        metrics = sim.simulated_active_network_metrics(
            threshold=0.5,
            persistence_threshold=0.5,
        )

        assert metrics["source_variable"] == "accumulation_flux"
        assert metrics["n_timesteps"] == 3
        assert metrics["catchment_cell_count"] == 3
        assert metrics["active_cell_count_mean"] == pytest.approx(5.0 / 3.0)
        assert metrics["active_cell_count_max"] == 2
        assert metrics["active_cell_count_last"] == 2
        assert metrics["active_cell_count_any"] == 3
        assert metrics["persistent_cell_count"] == 1
        assert metrics["always_active_cell_count"] == 1
        assert metrics["perennial_cell_count"] == 1
        assert metrics["drainage_density_mean_pct"] == pytest.approx(100.0 * 5.0 / 9.0)
        assert metrics["drainage_density_max_pct"] == pytest.approx(100.0 * 2.0 / 3.0)
        assert metrics["drainage_density_last_pct"] == pytest.approx(100.0 * 2.0 / 3.0)
        assert metrics["active_any_ratio"] == pytest.approx(1.0)
        assert metrics["persistent_ratio"] == pytest.approx(1.0 / 3.0)
        assert metrics["always_active_ratio"] == pytest.approx(1.0 / 3.0)
        assert metrics["perennial_ratio"] == pytest.approx(1.0 / 3.0)
        assert metrics["persistence_mean"] == pytest.approx(5.0 / 9.0)
        assert metrics["persistence_max"] == pytest.approx(1.0)

    def test_simulated_active_network_mask_modes(self, catalog):
        sid = _register(catalog, n_cells=4, n_layers=1, n_timesteps=3)
        _write_active_accumulation_flux_case(catalog, sid)

        sim = Run(sid, catalog)

        np.testing.assert_allclose(
            sim.simulated_active_network_mask(threshold=0.5, mode="last"),
            np.array([0.0, 1.0, np.nan, 1.0]),
        )
        np.testing.assert_allclose(
            sim.simulated_active_network_mask(threshold=0.5, mode="any"),
            np.array([1.0, 1.0, np.nan, 1.0]),
        )
        np.testing.assert_allclose(
            sim.simulated_active_network_mask(
                threshold=0.5,
                mode="persistent",
                persistence_threshold=0.5,
            ),
            np.array([0.0, 1.0, np.nan, 0.0]),
        )
        np.testing.assert_allclose(
            sim.simulated_active_network_mask(threshold=0.5, mode="always_active"),
            np.array([0.0, 1.0, np.nan, 0.0]),
        )
        np.testing.assert_allclose(
            sim.simulated_active_network_mask(threshold=0.5, mode="perennial"),
            np.array([0.0, 1.0, np.nan, 0.0]),
        )
        np.testing.assert_allclose(
            sim.simulated_active_network_mask(threshold=0.5, mode="persistence"),
            np.array([1.0 / 3.0, 1.0, np.nan, 1.0 / 3.0]),
        )

    def test_simulated_active_network_mask_default_is_regime_aware(self, catalog):
        transient_sid = _register(
            catalog,
            n_cells=4,
            n_layers=1,
            n_timesteps=3,
            flow_regime="transient",
        )
        steady_sid = _register(
            catalog,
            n_cells=4,
            n_layers=1,
            n_timesteps=3,
            flow_regime="steady",
        )
        _write_active_accumulation_flux_case(catalog, transient_sid)
        _write_active_accumulation_flux_case(catalog, steady_sid)

        transient = Run(transient_sid, catalog)
        steady = Run(steady_sid, catalog)

        np.testing.assert_allclose(
            transient.simulated_active_network_mask(threshold=0.5),
            np.array([0.0, 1.0, np.nan, 0.0]),
        )
        np.testing.assert_allclose(
            steady.simulated_active_network_mask(threshold=0.5),
            np.array([0.0, 1.0, np.nan, 1.0]),
        )

    def test_simulated_active_network_overlap_metrics_against_reference_role_by_default(
        self,
        catalog,
    ):
        sid = _register(catalog, n_cells=4, n_layers=1, n_timesteps=3)
        _write_active_accumulation_flux_case(catalog, sid, write_plot_mesh=True)
        reference = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(1.5, 0.5), (1.5, 1.5)])],
            crs="EPSG:2154",
        )
        catalog.write_geographic_feature(sid, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, reference)

        sim = Run(sid, catalog)
        metrics = sim.simulated_active_network_overlap_metrics(
            threshold=0.5,
            mode="persistent",
            persistence_threshold=0.5,
        )

        assert metrics["network_role"] == "reference"
        assert metrics["catchment_cell_count"] == 3
        assert metrics["active_cell_count"] == 1
        assert metrics["network_cell_count"] == 2
        assert metrics["overlap_cell_count"] == 1
        assert metrics["missing_network_cell_count"] == 1
        assert metrics["extra_active_cell_count"] == 0
        assert metrics["network_coverage_ratio"] == pytest.approx(0.5)
        assert metrics["active_precision_ratio"] == pytest.approx(1.0)
        assert metrics["cell_f1_ratio"] == pytest.approx(2.0 / 3.0)
        assert metrics["cell_jaccard_ratio"] == pytest.approx(0.5)

    def test_simulated_active_network_distance_metrics_against_reference_role(
        self,
        catalog,
    ):
        sid = _register(catalog, n_cells=4, n_layers=1, n_timesteps=3)
        _write_active_accumulation_flux_case(catalog, sid, write_plot_mesh=True)
        reference = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(1.5, 0.5), (1.5, 1.5)])],
            crs="EPSG:2154",
        )
        catalog.write_geographic_feature(sid, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, reference)

        sim = Run(sid, catalog)
        metrics = sim.simulated_active_network_distance_metrics(
            threshold=0.5,
            mode="persistent",
            persistence_threshold=0.5,
        )

        assert metrics["network_role"] == "reference"
        assert metrics["distance_method"] == "planar_cell_centroid_to_network"
        assert metrics["catchment_cell_count"] == 3
        assert metrics["active_cell_count"] == 1
        assert metrics["network_cell_count"] == 2
        assert metrics["sim_to_network_sample_count"] == 1
        assert metrics["network_to_sim_sample_count"] == 2
        assert metrics["sim_to_network_distance_mean_m"] == pytest.approx(0.0)
        assert metrics["network_to_sim_distance_mean_m"] == pytest.approx(0.25)
        assert metrics["network_to_sim_distance_max_m"] == pytest.approx(0.5)
        assert metrics["bidirectional_distance_mean_m"] == pytest.approx(0.125)


class TestSimulationField:
    def test_read_field(self, catalog):
        sid = _register(catalog, n_cells=20, n_layers=2, n_timesteps=3)
        sz = catalog.open_zarr(sid)
        for t in range(3):
            sz.write_field("head", t, np.ones((2, 20)), n_timesteps=3 if t == 0 else None)
        sim = Run(sid, catalog)
        result = sim.field("head", timestep=1)
        assert result.shape == (2, 20)

    def test_negative_timestep(self, catalog):
        sid = _register(catalog, n_cells=5, n_layers=1, n_timesteps=4)
        sz = catalog.open_zarr(sid)
        for t in range(4):
            vals = np.full(5, float(t))
            sz.write_field("head", t, vals, n_timesteps=4 if t == 0 else None)
        sim = Run(sid, catalog)
        result = sim.field("head", timestep=-1)
        np.testing.assert_array_equal(result, np.full(5, 3.0))


class TestSimulationDisplayCapabilities:
    def test_basic_caps(self, catalog):
        sid = _register(catalog, n_cells=10, n_layers=1, flow_regime="steady")
        sim = Run(sid, catalog)
        caps = sim.display_capabilities
        assert "piezometric_map" in caps
        assert "water_budget" in caps
        assert "cross_section" not in caps

    def test_multilayer_caps(self, catalog):
        sid = _register(catalog, n_cells=10, n_layers=3, flow_regime="steady")
        sim = Run(sid, catalog)
        assert "cross_section" in sim.display_capabilities

    def test_transient_caps(self, catalog):
        sid = _register(catalog, n_cells=10, n_layers=1, flow_regime="transient")
        sim = Run(sid, catalog)
        caps = sim.display_capabilities
        assert "hydrograph" in caps


class TestSimulationSummary:
    def test_dict_keys(self, catalog):
        sid = _register(catalog, name="run1", flow_regime="transient", n_timesteps=12)
        sim = Run(sid, catalog)
        info = sim.summary()
        assert isinstance(info, dict)
        expected = {
            "sim_id",
            "name",
            "project",
            "solver",
            "solver_category",
            "flow_regime",
            "status",
            "created_at",
            "duration_s",
            "n_layers",
            "n_cells",
            "n_timesteps",
            "tags",
        }
        assert set(info) == expected
        assert info["sim_id"] == sid
        assert info["name"] == "run1"
        assert info["project"] == "test"
        assert info["solver"] == "modflow6"
        assert info["flow_regime"] == "transient"
        assert info["n_layers"] == 2
        assert info["n_cells"] == 10
        assert info["n_timesteps"] == 12

    def test_json_roundtrip(self, catalog):
        sid = _register(catalog, name="run-json", tags=["a", "b"])
        catalog.finalize(sid, "completed", 7.5)
        sim = Run(sid, catalog)
        payload = sim.summary(json=True)
        assert isinstance(payload, str)
        parsed = json.loads(payload)
        assert parsed["sim_id"] == sid
        assert parsed["name"] == "run-json"
        assert parsed["status"] == "completed"
        assert parsed["duration_s"] == pytest.approx(7.5)
        assert parsed["tags"] == ["a", "b"]
        # created_at must serialise (datetime -> string)
        assert isinstance(parsed["created_at"], str)

    def test_not_found(self, catalog):
        sim = Run("nonexistent-uuid", catalog)
        with pytest.raises(KeyError):
            sim.summary()


class TestSimulationRepr:
    def test_repr_found(self, catalog):
        sid = _register(catalog)
        sim = Run(sid, catalog)
        r = repr(sim)
        assert "test" in r
        assert "modflow6" in r

    def test_repr_not_found(self, catalog):
        sim = Run("nope", catalog)
        r = repr(sim)
        assert "not found" in r


# ============================================================================
# SimulationGroup tests
# ============================================================================


class TestSimulationGroup:
    def test_count_and_len(self, catalog):
        sids = [_register(catalog) for _ in range(3)]
        group = SimulationGroup(sids, catalog)
        assert group.count == 3
        assert len(group) == 3

    def test_project_sweep_returns_group_bound_to_catalog(self, monkeypatch, catalog):
        from hydromodpy.project_runner import ProjectRunner

        sids = [_register(catalog) for _ in range(2)]

        def fake_run_sweep(project, *, parameters, strategy, name_template):
            assert parameters == {"K": [1.0, 2.0]}
            assert strategy == "enumerate"
            assert name_template == "{param}_{value:.4g}"
            return sids

        monkeypatch.setattr("hydromodpy.workflow.parallel.run_sweep", fake_run_sweep)
        project = SimpleNamespace(_store=catalog)

        group = ProjectRunner(project).sweep({"K": [1.0, 2.0]})

        assert isinstance(group, SimulationGroup)
        assert group.sim_ids == sids
        assert group[0].sim_id == sids[0]

    def test_project_run_handles_survive_later_runs(self, monkeypatch, tmp_path):
        from hydromodpy.project_runner import ProjectRunner
        from hydromodpy.results.catalog import SimulationCatalog
        from hydromodpy.workflow.internals.state import PipelineState

        class _Step:
            name = "setup_process"

        class _Pipeline:
            counter = 0

            def __init__(self, steps, *, workspace, checkpoint):
                self.steps = steps
                self.workspace = workspace
                self.checkpoint = checkpoint

            def run(self, state, *, resume_from=None):
                _Pipeline.counter += 1
                ctx = state.get("ctx")
                sim_id = str(uuid.uuid4())
                with SimulationCatalog(ctx.setup.workspace.project_root) as run_catalog:
                    reg = run_catalog.register_simulation(
                        sim_id,
                        project="project",
                        solver="fake",
                        name=ctx.setup.run_id,
                        n_cells=1,
                        n_layers=1,
                    )
                    if reg.zarr is not None:
                        reg.zarr.close()
                    run_catalog.write_parameters(
                        sim_id,
                        [
                            {
                                "param_name": "thickness",
                                "value": float(_Pipeline.counter),
                                "unit": "m",
                            }
                        ],
                    )
                    run_catalog.finalize(sim_id, "completed")
                ctx.sim_id = sim_id
                ctx.store = None
                return PipelineState(
                    run_id=state.run_id,
                    step_index=0,
                    step_name="display",
                    data={**state.data, "ctx": ctx},
                )

        monkeypatch.setattr("hydromodpy.workflow.orchestrator.standard_steps", lambda: (_Step(),))
        monkeypatch.setattr(
            "hydromodpy.workflow.steps.planning.step_build_plan", lambda *a, **k: None
        )
        monkeypatch.setattr("hydromodpy.workflow.runner.Pipeline", _Pipeline)

        project_root = tmp_path / "project"
        workspace = SimpleNamespace(
            root=tmp_path / "workspace",
            project_root=project_root,
            catalog_path=project_root / "hydromodpy.duckdb",
            simulations_dir=project_root / "simulations",
        )
        ctx = SimpleNamespace(
            setup=SimpleNamespace(
                workspace=workspace,
                geographic=object(),
                domain=object(),
                run_id=None,
                flow_runtime_overrides=None,
            ),
            raw_toml={},
            store=None,
            sim_id=None,
        )
        project = SimpleNamespace(
            _ctx=ctx,
            cfg=SimpleNamespace(),
            _config_path=tmp_path / "project.toml",
            _spatial_support_registry=None,
            _requested_support_ids=(),
            _requested_domain_supports={},
            _store=None,
            _run_counter=0,
            _solver="fake",
            _no_display=True,
            _headless=True,
            _project_name="project",
            _active_runs={},
            _last_wall_seconds={},
            _run_history=[],
        )

        runner = ProjectRunner(project)
        first = runner.run(name="first")
        first_catalog = first._catalog
        second = runner.run(name="second")

        assert first_catalog is not project._store
        assert first._catalog is project._store
        assert second._catalog is project._store
        assert first.params["thickness"] == pytest.approx(1.0)
        assert second.params["thickness"] == pytest.approx(2.0)

    def test_iter(self, catalog):
        sids = [_register(catalog) for _ in range(2)]
        group = SimulationGroup(sids, catalog)
        sims = list(group)
        assert len(sims) == 2
        assert all(isinstance(s, Run) for s in sims)

    def test_getitem(self, catalog):
        sids = [_register(catalog) for _ in range(3)]
        group = SimulationGroup(sids, catalog)
        sim = group[1]
        assert isinstance(sim, Run)
        assert sim.sim_id == sids[1]

    def test_best_worst(self, catalog):
        s1 = _register(catalog)
        s2 = _register(catalog)
        catalog.write_metric(s1, "P01", "nse", 0.6)
        catalog.write_metric(s2, "P01", "nse", 0.9)
        catalog.finalize(s1, "completed")
        catalog.finalize(s2, "completed")

        group = SimulationGroup([s1, s2], catalog)
        assert group.best("nse").sim_id == s2
        assert group.worst("nse").sim_id == s1

    def test_sort_by(self, catalog):
        s1 = _register(catalog)
        s2 = _register(catalog)
        s3 = _register(catalog)
        catalog.write_metric(s1, "P01", "nse", 0.5)
        catalog.write_metric(s2, "P01", "nse", 0.9)
        catalog.write_metric(s3, "P01", "nse", 0.7)

        group = SimulationGroup([s1, s2, s3], catalog)
        sorted_g = group.sort_by("nse", ascending=False)
        assert sorted_g.sim_ids[0] == s2
        assert sorted_g.sim_ids[-1] == s1

    def test_compare(self, catalog):
        s1 = _register(catalog)
        s2 = _register(catalog)
        catalog.write_metric(s1, "P01", "nse", 0.6)
        catalog.write_metric(s2, "P01", "nse", 0.9)

        group = SimulationGroup([s1, s2], catalog)
        df = group.compare("nse")
        assert len(df) == 2

    def test_to_dataframe(self, catalog):
        s1 = _register(catalog)
        _populate(catalog, s1)
        s2 = _register(catalog)
        _populate(catalog, s2)

        group = SimulationGroup([s1, s2], catalog)
        df = group.to_dataframe()
        assert len(df) == 2
        assert "sim_id" in df.columns

    def test_empty_group(self, catalog):
        group = SimulationGroup([], catalog)
        assert group.count == 0
        assert group.parameters.empty
        assert group.metrics.empty
        assert group.to_dataframe().empty


# ============================================================================
# Catalog query methods tests
# ============================================================================


class TestCatalogQueryMethods:
    def test_simulations_property(self, catalog):
        _register(catalog, project="a")
        _register(catalog, project="b")
        df = catalog.simulations
        assert len(df) == 2

    def test_getitem(self, catalog):
        sid = _register(catalog)
        sim = catalog[sid]
        assert isinstance(sim, Run)
        assert sim.sim_id == sid

    def test_getitem_not_found(self, catalog):
        with pytest.raises(KeyError):
            _ = catalog["nonexistent"]

    def test_find_by_project(self, catalog):
        _register(catalog, project="canut")
        _register(catalog, project="canut")
        _register(catalog, project="nancon")
        group = catalog.find(project="canut")
        assert group.count == 2

    def test_find_by_solver(self, catalog):
        _register(catalog, solver="modflow6")
        _register(catalog, solver="boussinesq")
        group = catalog.find(solver="modflow6")
        assert group.count == 1

    def test_find_by_status(self, catalog):
        s1 = _register(catalog)
        s2 = _register(catalog)
        catalog.finalize(s1, "completed")
        catalog.finalize(s2, "failed")
        group = catalog.find(status="completed")
        assert group.count == 1

    def test_find_by_metric_threshold(self, catalog):
        s1 = _register(catalog)
        s2 = _register(catalog)
        s3 = _register(catalog)
        catalog.write_metric(s1, "P01", "nse", 0.5)
        catalog.write_metric(s2, "P01", "nse", 0.8)
        catalog.write_metric(s3, "P01", "nse", 0.9)
        group = catalog.find(nse_gt=0.7)
        assert group.count == 2

    def test_find_combined_filters(self, catalog):
        s1 = _register(catalog, project="canut")
        s2 = _register(catalog, project="canut")
        s3 = _register(catalog, project="nancon")
        catalog.finalize(s1, "completed")
        catalog.finalize(s2, "failed")
        catalog.finalize(s3, "completed")
        group = catalog.find(project="canut", status="completed")
        assert group.count == 1

    def test_find_by_tags(self, catalog):
        _register(catalog, tags=["transient", "test"])
        _register(catalog, tags=["steady"])
        group = catalog.find(tags="transient")
        assert group.count == 1

    def test_find_unknown_filter(self, catalog):
        with pytest.raises(ValueError, match="Unknown filter"):
            catalog.find(nonexistent_field="x")

    def test_latest(self, catalog):
        s1 = _register(catalog, project="p1")
        catalog.finalize(s1, "completed")
        s2 = _register(catalog, project="p1")
        catalog.finalize(s2, "completed")
        sim = catalog.latest("p1")
        assert sim.sim_id == s2

    def test_latest_not_found(self, catalog):
        with pytest.raises(KeyError):
            catalog.latest("nonexistent")

    def test_best(self, catalog):
        s1 = _register(catalog, project="p1")
        s2 = _register(catalog, project="p1")
        catalog.write_metric(s1, "P01", "nse", 0.6)
        catalog.write_metric(s2, "P01", "nse", 0.9)
        catalog.finalize(s1, "completed")
        catalog.finalize(s2, "completed")
        sim = catalog.best("p1", metric="nse")
        assert sim.sim_id == s2

    def test_best_not_found(self, catalog):
        with pytest.raises(KeyError):
            catalog.best("nonexistent", metric="nse")

    def test_sql(self, catalog):
        _register(catalog, project="p1")
        _register(catalog, project="p2")
        df = catalog.sql("SELECT project, COUNT(*) as n FROM simulations GROUP BY project")
        assert len(df) == 2

    def test_cleanup_by_status(self, catalog):
        s1 = _register(catalog)
        s2 = _register(catalog)
        catalog.finalize(s1, "completed")
        catalog.finalize(s2, "failed")
        n = catalog.cleanup(status="failed")
        assert n == 1
        assert catalog.simulations.shape[0] == 1


class TestHmpOpen:
    def test_open_returns_catalog(self, tmp_path):
        import hydromodpy as hmp

        cat = hmp.open(tmp_path / "ws")
        assert isinstance(cat, SimulationCatalog)
        cat.close()

    def test_open_roundtrip(self, tmp_path):
        import hydromodpy as hmp

        with hmp.open(tmp_path / "ws") as cat:
            cat.register_simulation(
                "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "test",
                "modflow6",
            )
        with hmp.open(tmp_path / "ws") as cat:
            df = cat.simulations
            assert len(df) == 1
