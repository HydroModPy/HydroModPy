"""Unit tests for the physically-targeted mesh refinement sources.

Covers the lake shoreline band (not the interior), the widened cutoff-wall
zone absorbing the dam-outlet disk, the opt-in watershed-boundary refinement,
and the user-provided refinement zones.
"""

from __future__ import annotations

from types import SimpleNamespace

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point, Polygon

from hydromodpy.spatial.mesh.config.main import MeshCatchmentConfig
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.config import ZoneMeshingSettings
from hydromodpy.spatial.mesh.lake_refinement import (
    LakeRefinementConfig,
    build_lake_refinement_size_fields,
)
from hydromodpy.spatial.mesh.refinement_zones import (
    RefinementZoneConfig,
    build_refinement_zone_size_fields,
)

LAKE = Polygon([(0.0, 0.0), (1000.0, 0.0), (1000.0, 600.0), (0.0, 600.0)])
GLOBAL_SIZE = 150.0


def _fields_by_name(fields) -> dict:
    return {field.name: field for field in fields}


class TestShorelineBand:
    def test_band_covers_shoreline_not_interior(self) -> None:
        cfg = LakeRefinementConfig(enabled=True, cell_size=40.0, buffer=100.0)
        fields = _fields_by_name(
            build_lake_refinement_size_fields(
                lake_polygon=LAKE, dam_xy=None, cfg=cfg, global_size=GLOBAL_SIZE
            )
        )
        assert set(fields) == {"lake::shoreline"}
        band = fields["lake::shoreline"]
        assert band.region_geometry.covers(Point(0.0, 300.0))
        assert not band.region_geometry.covers(Point(500.0, 300.0))
        assert band.inside_size == pytest.approx(40.0)
        assert band.transition_distance == pytest.approx(100.0)

    def test_band_width_defaults_to_twice_cell_size(self) -> None:
        cfg = LakeRefinementConfig(enabled=True, cell_size=40.0)
        fields = _fields_by_name(
            build_lake_refinement_size_fields(
                lake_polygon=LAKE, dam_xy=None, cfg=cfg, global_size=GLOBAL_SIZE
            )
        )
        band = fields["lake::shoreline"].region_geometry
        assert band.covers(Point(-79.0, 300.0))
        assert not band.covers(Point(-81.0, 300.0))

    def test_band_width_override(self) -> None:
        cfg = LakeRefinementConfig(enabled=True, cell_size=40.0, shoreline_band=60.0)
        fields = _fields_by_name(
            build_lake_refinement_size_fields(
                lake_polygon=LAKE, dam_xy=None, cfg=cfg, global_size=GLOBAL_SIZE
            )
        )
        band = fields["lake::shoreline"].region_geometry
        assert band.covers(Point(-59.0, 300.0))
        assert not band.covers(Point(-61.0, 300.0))

    def test_interior_option_adds_second_field(self) -> None:
        cfg = LakeRefinementConfig(enabled=True, cell_size=40.0, interior_size=80.0)
        fields = _fields_by_name(
            build_lake_refinement_size_fields(
                lake_polygon=LAKE, dam_xy=None, cfg=cfg, global_size=GLOBAL_SIZE
            )
        )
        assert set(fields) == {"lake::shoreline", "lake::interior"}
        interior = fields["lake::interior"]
        assert interior.region_geometry.covers(Point(500.0, 300.0))
        assert interior.inside_size == pytest.approx(80.0)

    def test_interior_finer_than_shoreline_rejected(self) -> None:
        with pytest.raises(ValueError, match="interior_size"):
            LakeRefinementConfig(enabled=True, cell_size=40.0, interior_size=20.0)

    def test_disabled_returns_empty(self) -> None:
        cfg = LakeRefinementConfig(enabled=False)
        assert (
            build_lake_refinement_size_fields(
                lake_polygon=LAKE, dam_xy=None, cfg=cfg, global_size=GLOBAL_SIZE
            )
            == ()
        )


class TestDamOutletDisk:
    DAM_XY = (500.0, -50.0)

    def test_disk_absorbed_by_cutoff_wall(self) -> None:
        cfg = LakeRefinementConfig(enabled=True)
        fields = _fields_by_name(
            build_lake_refinement_size_fields(
                lake_polygon=LAKE,
                dam_xy=self.DAM_XY,
                cfg=cfg,
                global_size=GLOBAL_SIZE,
                has_cutoff_wall=True,
            )
        )
        assert "lake::dam_outlet" not in fields

    def test_disk_emitted_without_cutoff_wall(self) -> None:
        cfg = LakeRefinementConfig(enabled=True)
        fields = _fields_by_name(
            build_lake_refinement_size_fields(
                lake_polygon=LAKE,
                dam_xy=self.DAM_XY,
                cfg=cfg,
                global_size=GLOBAL_SIZE,
                has_cutoff_wall=False,
            )
        )
        disk = fields["lake::dam_outlet"]
        assert disk.region_geometry.covers(Point(*self.DAM_XY))
        assert disk.inside_size == pytest.approx(cfg.dam_cell_size)

    def test_disk_forced_despite_cutoff_wall(self) -> None:
        cfg = LakeRefinementConfig(enabled=True, dam_outlet_disk=True)
        fields = _fields_by_name(
            build_lake_refinement_size_fields(
                lake_polygon=LAKE,
                dam_xy=self.DAM_XY,
                cfg=cfg,
                global_size=GLOBAL_SIZE,
                has_cutoff_wall=True,
            )
        )
        assert "lake::dam_outlet" in fields

    def test_disk_suppressed_explicitly(self) -> None:
        cfg = LakeRefinementConfig(enabled=True, dam_outlet_disk=False)
        fields = _fields_by_name(
            build_lake_refinement_size_fields(
                lake_polygon=LAKE,
                dam_xy=self.DAM_XY,
                cfg=cfg,
                global_size=GLOBAL_SIZE,
                has_cutoff_wall=False,
            )
        )
        assert "lake::dam_outlet" not in fields


class TestFeatureZones:
    def test_line_feature_dilated_to_zone_buffer(self) -> None:
        cfg = LakeRefinementConfig(enabled=True)
        line = LineString([(400.0, -10.0), (600.0, -10.0)])
        fields = _fields_by_name(
            build_lake_refinement_size_fields(
                lake_polygon=None,
                dam_xy=None,
                cfg=cfg,
                global_size=GLOBAL_SIZE,
                feature_geometries=[("voile:l1", line, 60.0, 260.0)],
            )
        )
        zone = fields["feature::voile:l1"]
        assert zone.region_geometry.covers(Point(500.0, 249.0 - 10.0))
        assert not zone.region_geometry.covers(Point(500.0, 261.0 - 10.0))
        assert zone.transition_distance == pytest.approx(260.0)
        assert zone.inside_size == pytest.approx(60.0)

    def test_polygon_feature_kept_as_is(self) -> None:
        cfg = LakeRefinementConfig(enabled=True)
        sill = Polygon([(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)])
        fields = _fields_by_name(
            build_lake_refinement_size_fields(
                lake_polygon=None,
                dam_xy=None,
                cfg=cfg,
                global_size=GLOBAL_SIZE,
                feature_geometries=[("sill:a-b", sill, 20.0, 75.0)],
            )
        )
        zone = fields["feature::sill:a-b"]
        assert zone.region_geometry.equals(sill)
        assert zone.transition_distance == pytest.approx(75.0)


class TestHydraulicFeatureGeometries:
    @staticmethod
    def _setup_state(lakes: dict) -> SimpleNamespace:
        return SimpleNamespace(flow=SimpleNamespace(sinks_sources={"lakes": lakes}))

    def test_voile_gets_hfb_zone_buffer_default(self) -> None:
        from hydromodpy.workflow.steps.mesh import _hydraulic_feature_geometries

        line = LineString([(0.0, 0.0), (200.0, 0.0)])
        state = self._setup_state({"l1": {"cutoff_wall_line": line, "polygon": None}})
        cfg = LakeRefinementConfig(enabled=True, dam_cell_size=60.0, dam_buffer=130.0)
        features = _hydraulic_feature_geometries(state, cfg)
        assert features == [("voile:l1", line, 60.0, 260.0)]

    def test_voile_hfb_buffer_override(self) -> None:
        from hydromodpy.workflow.steps.mesh import _hydraulic_feature_geometries

        line = LineString([(0.0, 0.0), (200.0, 0.0)])
        state = self._setup_state({"l1": {"cutoff_wall_line": line, "polygon": None}})
        cfg = LakeRefinementConfig(
            enabled=True, dam_cell_size=60.0, dam_buffer=130.0, hfb_buffer=90.0
        )
        features = _hydraulic_feature_geometries(state, cfg)
        assert features[0][3] == pytest.approx(90.0)

    def test_sill_zone_between_two_lakes(self) -> None:
        from hydromodpy.workflow.steps.mesh import _hydraulic_feature_geometries

        lake_a = Polygon([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)])
        lake_b = Polygon([(140.0, 0.0), (240.0, 0.0), (240.0, 100.0), (140.0, 100.0)])
        state = self._setup_state({"a": {"polygon": lake_a}, "b": {"polygon": lake_b}})
        cfg = LakeRefinementConfig(enabled=True, dam_cell_size=60.0)
        features = _hydraulic_feature_geometries(state, cfg)
        (label, zone, size, margin) = features[0]
        assert label == "sill:a-b"
        assert size == pytest.approx(0.4 * 40.0)
        assert margin == pytest.approx(60.0)
        assert zone.covers(Point(120.0, 50.0))


class TestWatershedBoundaryOptIn:
    def test_family_disabled_by_default(self) -> None:
        settings = ZoneMeshingSettings.from_mapping(
            {"refine_interfaces": True, "refinement_policy": {"enabled": True}}
        )
        assert settings.refinement_policy.families["watershed_boundary"].enabled is False
        assert settings.refinement_policy.families["river"].enabled is True

    def test_refinement_enabled_helper(self) -> None:
        from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_2d_geology_conformal.planning import (
            _watershed_boundary_refinement_enabled,
        )

        no_policy = ZoneMeshingSettings.from_mapping({"refine_interfaces": True})
        assert _watershed_boundary_refinement_enabled(no_policy) is False

        default_family = ZoneMeshingSettings.from_mapping(
            {"refine_interfaces": True, "refinement_policy": {"enabled": True}}
        )
        assert _watershed_boundary_refinement_enabled(default_family) is False

        opted_in = ZoneMeshingSettings.from_mapping(
            {
                "refine_interfaces": True,
                "interface_size": 80.0,
                "interface_distance": 250.0,
                "refinement_policy": {
                    "families": {"watershed_boundary": {"enabled": True, "priority": 100}}
                },
            }
        )
        assert _watershed_boundary_refinement_enabled(opted_in) is True

    @staticmethod
    def _watershed_boundary_cfg(boundary_refinement_distance: float | None = None):
        from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_2d_geology_conformal.contracts import (
            ZoneConformalWatershedBoundaryConfig,
            ZoneConformalWatershedBoundarySmoothingConfig,
            ZoneConformalWatershedGeologyConformityConfig,
            ZoneConformalWatershedOutsideCoarseningConfig,
        )

        return ZoneConformalWatershedBoundaryConfig(
            enabled=True,
            boundary_refinement_distance=boundary_refinement_distance,
            smoothing=ZoneConformalWatershedBoundarySmoothingConfig(
                enabled=False, distance=None, river_buffer_distance=None, outer_bias_distance=None
            ),
            outside_coarsening=ZoneConformalWatershedOutsideCoarseningConfig(
                enabled=False, size_factor=2.0, transition_distance=None, grid_resolution=None
            ),
            geology_conformity=ZoneConformalWatershedGeologyConformityConfig(
                mode="full_domain", buffer_distance=None
            ),
        )

    def test_derive_keeps_config_untouched_without_opt_in(self) -> None:
        from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_2d_geology_conformal.planning import (
            _derive_watershed_runtime_zone_meshing_config,
        )

        settings = ZoneMeshingSettings.from_mapping(
            {"refine_interfaces": True, "interface_size": 80.0, "interface_distance": 250.0}
        )
        derived = _derive_watershed_runtime_zone_meshing_config(
            zone_meshing_cfg=settings,
            watershed_boundary_cfg=self._watershed_boundary_cfg(),
            watershed_geometry=Polygon([(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0)]),
        )
        assert derived is settings

    def test_derive_forces_policy_on_opt_in(self) -> None:
        from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_2d_geology_conformal.planning import (
            _derive_watershed_runtime_zone_meshing_config,
        )

        settings = ZoneMeshingSettings.from_mapping(
            {
                "refine_interfaces": True,
                "interface_size": 80.0,
                "interface_distance": 250.0,
                "refinement_policy": {
                    "families": {"watershed_boundary": {"enabled": True, "priority": 100}}
                },
            }
        )
        derived = _derive_watershed_runtime_zone_meshing_config(
            zone_meshing_cfg=settings,
            watershed_boundary_cfg=self._watershed_boundary_cfg(250.0),
            watershed_geometry=Polygon([(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0)]),
        )
        assert derived.refinement_policy.enabled is True
        family = derived.refinement_policy.families["watershed_boundary"]
        assert family.enabled is True
        assert family.interface_size == pytest.approx(80.0)
        assert family.interface_distance == pytest.approx(250.0)

    def test_boundary_constraint_refinement_flag(self) -> None:
        from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_2d_geology_conformal.planning import (
            _build_watershed_boundary_constraint,
        )

        domain = Polygon([(-500.0, -500.0), (2000.0, -500.0), (2000.0, 2000.0), (-500.0, 2000.0)])
        payload = SimpleNamespace(geometry=domain)
        constraint = _build_watershed_boundary_constraint(
            watershed_geometry=Polygon([(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0)]),
            effective_domain_payload=payload,
            participates_in_refinement=False,
        )
        assert constraint is not None
        assert constraint.participates_in_refinement is False


class TestRefinementZones:
    def test_polygon_and_point_layer(self, tmp_path) -> None:
        polygon = Polygon([(0.0, 0.0), (500.0, 0.0), (500.0, 500.0), (0.0, 500.0)])
        gdf = gpd.GeoDataFrame(
            {"name": ["zone", "well"]},
            geometry=[polygon, Point(2000.0, 2000.0)],
            crs="EPSG:2154",
        )
        layer = tmp_path / "zones.gpkg"
        gdf.to_file(layer, driver="GPKG")

        fields = build_refinement_zone_size_fields(
            zones=[RefinementZoneConfig(path=str(layer), cell_size=40.0, buffer=120.0)],
            global_size=GLOBAL_SIZE,
            target_crs="EPSG:2154",
        )
        assert len(fields) == 1
        field = fields[0]
        assert field.name.endswith(":zones")
        assert field.inside_size == pytest.approx(40.0)
        assert field.transition_distance == pytest.approx(120.0)
        region = field.region_geometry
        assert region.covers(Point(250.0, 250.0))
        assert region.covers(Point(2000.0 + 119.0, 2000.0))
        assert not region.covers(Point(2000.0 + 121.0, 2000.0))

    def test_buffer_defaults_to_twice_cell_size(self, tmp_path) -> None:
        gdf = gpd.GeoDataFrame({"name": ["well"]}, geometry=[Point(0.0, 0.0)], crs="EPSG:2154")
        layer = tmp_path / "well.gpkg"
        gdf.to_file(layer, driver="GPKG")

        fields = build_refinement_zone_size_fields(
            zones=[RefinementZoneConfig(path=str(layer), cell_size=40.0)],
            global_size=GLOBAL_SIZE,
            target_crs="EPSG:2154",
        )
        region = fields[0].region_geometry
        assert region.covers(Point(79.0, 0.0))
        assert not region.covers(Point(81.0, 0.0))

    def test_layer_reprojected_to_target_crs(self, tmp_path) -> None:
        gdf = gpd.GeoDataFrame({"name": ["well"]}, geometry=[Point(-1.0, 48.0)], crs="EPSG:4326")
        layer = tmp_path / "wgs84.gpkg"
        gdf.to_file(layer, driver="GPKG")

        fields = build_refinement_zone_size_fields(
            zones=[RefinementZoneConfig(path=str(layer), cell_size=40.0)],
            global_size=GLOBAL_SIZE,
            target_crs="EPSG:2154",
        )
        projected = gdf.to_crs("EPSG:2154").geometry.iloc[0]
        assert fields[0].region_geometry.covers(projected)

    def test_empty_layer_raises(self, tmp_path) -> None:
        gdf = gpd.GeoDataFrame({"name": []}, geometry=[], crs="EPSG:2154")
        layer = tmp_path / "empty.gpkg"
        gdf.to_file(layer, driver="GPKG")

        with pytest.raises(ValueError, match="no usable geometry"):
            build_refinement_zone_size_fields(
                zones=[RefinementZoneConfig(path=str(layer), cell_size=40.0)],
                global_size=GLOBAL_SIZE,
                target_crs="EPSG:2154",
            )

    def test_bare_name_resolves_against_data_dir(self, tmp_path) -> None:
        zone_dir = tmp_path / "data" / "refinement_zone"
        zone_dir.mkdir(parents=True)
        gdf = gpd.GeoDataFrame({"name": ["well"]}, geometry=[Point(0.0, 0.0)], crs="EPSG:2154")
        gdf.to_file(zone_dir / "captage.gpkg", driver="GPKG")

        fields = build_refinement_zone_size_fields(
            zones=[RefinementZoneConfig(path="captage.gpkg", cell_size=40.0)],
            global_size=GLOBAL_SIZE,
            target_crs="EPSG:2154",
            data_dir=tmp_path / "data",
        )
        assert len(fields) == 1

    def test_mesh_catchment_config_accepts_zone_entries(self) -> None:
        cfg = MeshCatchmentConfig.model_validate(
            {
                "constraints_mode": "rivers_only",
                "refinement_zone": [
                    {"path": "zone_captage.gpkg", "cell_size": 40.0, "buffer": 120.0}
                ],
            }
        )
        assert len(cfg.refinement_zone) == 1
        assert cfg.refinement_zone[0].cell_size == pytest.approx(40.0)

    def test_zone_entry_rejects_unknown_field(self) -> None:
        with pytest.raises(ValueError):
            RefinementZoneConfig.model_validate(
                {"path": "z.gpkg", "cell_size": 40.0, "radius": 10.0}
            )


class TestThinRegionValidators:
    def test_shoreline_band_thinner_than_cell_rejected(self) -> None:
        with pytest.raises(ValueError, match="shoreline_band"):
            LakeRefinementConfig(enabled=True, cell_size=40.0, shoreline_band=5.0)

    def test_hfb_buffer_thinner_than_dam_cell_rejected(self) -> None:
        with pytest.raises(ValueError, match="hfb_buffer"):
            LakeRefinementConfig(enabled=True, dam_cell_size=60.0, hfb_buffer=10.0)

    def test_zone_buffer_thinner_than_cell_rejected(self) -> None:
        with pytest.raises(ValueError, match="buffer"):
            RefinementZoneConfig(path="z.gpkg", cell_size=40.0, buffer=10.0)


class TestPartialFamilyTable:
    def test_partial_watershed_table_keeps_opt_in_default(self) -> None:
        settings = ZoneMeshingSettings.from_mapping(
            {
                "refine_interfaces": True,
                "interface_size": 80.0,
                "interface_distance": 250.0,
                "refinement_policy": {"families": {"watershed_boundary": {"priority": 150}}},
            }
        )
        family = settings.refinement_policy.families["watershed_boundary"]
        assert family.enabled is False
        assert family.priority == 150

    def test_partial_river_table_keeps_enabled_default(self) -> None:
        settings = ZoneMeshingSettings.from_mapping(
            {
                "refine_interfaces": True,
                "interface_size": 80.0,
                "interface_distance": 250.0,
                "refinement_policy": {"families": {"river": {"priority": 10}}},
            }
        )
        family = settings.refinement_policy.families["river"]
        assert family.enabled is True
        assert family.priority == 10


class TestLakeMeshRefinementWiring:
    @staticmethod
    def _make_inputs(voile_line, x_outlet=331315.0, y_outlet=6781273.0):
        lr = LakeRefinementConfig(
            enabled=True, cell_size=80.0, buffer=160.0, dam_cell_size=60.0, dam_buffer=130.0
        )
        lakes = {"reservoir": {"polygon": LAKE, "cutoff_wall_line": voile_line}}
        cfg = SimpleNamespace(geographic=SimpleNamespace(x_outlet=x_outlet, y_outlet=y_outlet))
        section = SimpleNamespace(
            lake_refinement=lr, zone_meshing=SimpleNamespace(global_size=150.0)
        )
        setup_state = SimpleNamespace(flow=SimpleNamespace(sinks_sources={"lakes": lakes}))
        return cfg, section, setup_state

    def test_disk_absorbed_when_wall_zone_reaches_outlet(self) -> None:
        from hydromodpy.workflow.steps.mesh import _build_lake_mesh_refinement

        # Wall 100 m from the outlet: zone (260) + disk (130) overlap by far.
        voile = LineString([(331215.0, 6781273.0), (331255.0, 6781173.0)])
        cfg, section, state = self._make_inputs(voile)
        fields = {
            f.name
            for f in _build_lake_mesh_refinement(cfg=cfg, section_data=section, setup_state=state)
        }
        assert "lake::dam_outlet" not in fields
        assert "lake::shoreline" in fields
        assert "feature::voile:reservoir" in fields

    def test_disk_kept_when_wall_is_far_from_outlet(self) -> None:
        from hydromodpy.workflow.steps.mesh import _build_lake_mesh_refinement

        # Wall on another lake 2 km away: the under-dam disk must survive.
        voile = LineString([(329300.0, 6781273.0), (329400.0, 6781273.0)])
        cfg, section, state = self._make_inputs(voile)
        fields = {
            f.name
            for f in _build_lake_mesh_refinement(cfg=cfg, section_data=section, setup_state=state)
        }
        assert "lake::dam_outlet" in fields


class TestWatershedBoundaryInputsFlag:
    @staticmethod
    def _run_inputs(tmp_path, settings):
        import geopandas as gpd
        from shapely.geometry import box

        from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_2d_geology_conformal.planning import (
            _build_watershed_boundary_inputs,
        )

        watershed_path = tmp_path / "watershed.geojson"
        gpd.GeoDataFrame(
            {"catch_id": ["ws"]},
            geometry=[box(1000.0, 1000.0, 4000.0, 4000.0)],
            crs="EPSG:2154",
        ).to_file(watershed_path, driver="GeoJSON")
        domain = box(0.0, 0.0, 5000.0, 5000.0)
        payload = SimpleNamespace(
            geometry=domain,
            gdf=gpd.GeoDataFrame({"id": [1]}, geometry=[domain], crs="EPSG:2154"),
        )
        cfg = SimpleNamespace(
            watershed_boundary=TestWatershedBoundaryOptIn._watershed_boundary_cfg(250.0)
        )
        return _build_watershed_boundary_inputs(
            cfg=cfg,
            domain_geographic=SimpleNamespace(watershed_shp=str(watershed_path)),
            river_trace=None,
            effective_domain_payload=payload,
            target_crs="EPSG:2154",
            zone_meshing_cfg=settings,
        )

    def test_constraint_not_refined_by_default(self, tmp_path) -> None:
        settings = ZoneMeshingSettings.from_mapping(
            {"refine_interfaces": True, "interface_size": 80.0, "interface_distance": 250.0}
        )
        _, constraints, runtime_cfg, _, summary = self._run_inputs(tmp_path, settings)
        assert constraints and constraints[0].participates_in_refinement is False
        assert runtime_cfg is settings
        assert summary["refinement_family_enabled"] is False

    def test_constraint_refined_on_opt_in(self, tmp_path) -> None:
        settings = ZoneMeshingSettings.from_mapping(
            {
                "refine_interfaces": True,
                "interface_size": 80.0,
                "interface_distance": 250.0,
                "refinement_policy": {
                    "families": {"watershed_boundary": {"enabled": True, "priority": 100}}
                },
            }
        )
        _, constraints, runtime_cfg, _, summary = self._run_inputs(tmp_path, settings)
        assert constraints and constraints[0].participates_in_refinement is True
        assert runtime_cfg.refinement_policy.enabled is True
        assert summary["refinement_family_enabled"] is True
