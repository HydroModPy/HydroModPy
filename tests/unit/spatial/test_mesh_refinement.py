"""Unit tests for the refinement tables of ``[mesh]``.

Covers the cross-field validators of ``[mesh.lake_refinement]`` and
``[[mesh.refinement_zone]]`` and the hydraulic structures the lake table asks
the planner to refine.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, Polygon

from hydromodpy.spatial.mesh.refinement.lake_refinement import LakeRefinementConfig
from hydromodpy.spatial.mesh.refinement.refinement_zones import RefinementZoneConfig

LAKE = Polygon([(0.0, 0.0), (1000.0, 0.0), (1000.0, 600.0), (0.0, 600.0)])


class TestLakeRefinementValidators:
    def test_interior_finer_than_shoreline_rejected(self) -> None:
        with pytest.raises(ValueError, match="interior_size"):
            LakeRefinementConfig(cell_size=40.0, interior_size=20.0)

    def test_shoreline_band_thinner_than_cell_rejected(self) -> None:
        with pytest.raises(ValueError, match="shoreline_band"):
            LakeRefinementConfig(cell_size=40.0, shoreline_band=5.0)

    def test_hfb_buffer_thinner_than_dam_cell_rejected(self) -> None:
        with pytest.raises(ValueError, match="hfb_buffer"):
            LakeRefinementConfig(dam_cell_size=60.0, hfb_buffer=10.0)

    @pytest.mark.parametrize("value", [True, False])
    def test_the_enabled_key_is_refused_and_names_the_table(self, value: bool) -> None:
        with pytest.raises(ValueError, match=r"\[mesh\.lake_refinement\] has no 'enabled' key"):
            LakeRefinementConfig.model_validate({"enabled": value, "cell_size": 40.0})


class TestRefinementZoneValidators:
    def test_zone_buffer_thinner_than_cell_rejected(self) -> None:
        with pytest.raises(ValueError, match="buffer"):
            RefinementZoneConfig(path="z.gpkg", cell_size=40.0, buffer=10.0)

    def test_zone_entry_rejects_unknown_field(self) -> None:
        with pytest.raises(ValueError):
            RefinementZoneConfig.model_validate(
                {"path": "z.gpkg", "cell_size": 40.0, "radius": 10.0}
            )


class TestLakeStructuresWiring:
    @staticmethod
    def _make_inputs(voile_line, x_outlet=331315.0, y_outlet=6781273.0, **overrides):
        lr = LakeRefinementConfig(
            cell_size=80.0,
            buffer=160.0,
            dam_cell_size=60.0,
            dam_buffer=130.0,
            **overrides,
        )
        lakes = {"reservoir": {"polygon": LAKE, "cutoff_wall_line": voile_line}}
        geographic = SimpleNamespace(x_outlet=x_outlet, y_outlet=y_outlet)
        setup_state = SimpleNamespace(flow=SimpleNamespace(sinks_sources={"lakes": lakes}))
        return setup_state, geographic, lr

    @staticmethod
    def _labels(setup_state, geographic, lr) -> set[str]:
        from hydromodpy.workflow.steps.mesh_inputs import lake_structures

        return {label for label, *_ in lake_structures(setup_state, geographic, lr)}

    def test_disk_absorbed_when_wall_zone_reaches_outlet(self) -> None:
        # Wall 100 m from the outlet: zone (260) + disk (130) overlap by far.
        voile = LineString([(331215.0, 6781273.0), (331255.0, 6781173.0)])
        labels = self._labels(*self._make_inputs(voile))
        assert "dam_outlet" not in labels
        assert "voile:reservoir" in labels

    def test_disk_kept_when_wall_is_far_from_outlet(self) -> None:
        # Wall on another lake 2 km away: the under-dam disk must survive.
        voile = LineString([(329300.0, 6781273.0), (329400.0, 6781273.0)])
        assert "dam_outlet" in self._labels(*self._make_inputs(voile))

    def test_the_disk_can_be_forced_next_to_a_wall(self) -> None:
        voile = LineString([(331215.0, 6781273.0), (331255.0, 6781173.0)])
        labels = self._labels(*self._make_inputs(voile, dam_outlet_disk=True))
        assert {"dam_outlet", "voile:reservoir"} <= labels

    def test_the_disk_is_a_point_the_planner_dilates_by_the_dam_buffer(self) -> None:
        from hydromodpy.workflow.steps.mesh_inputs import lake_structures

        voile = LineString([(329300.0, 6781273.0), (329400.0, 6781273.0)])
        structures = {s[0]: s for s in lake_structures(*self._make_inputs(voile))}
        _, geometry, size, buffer = structures["dam_outlet"]
        assert (geometry.x, geometry.y) == (331315.0, 6781273.0)
        assert (size, buffer) == (60.0, 130.0)

    def test_no_structure_without_the_lake_table(self) -> None:
        from hydromodpy.workflow.steps.mesh_inputs import lake_structures

        setup_state, geographic, _ = self._make_inputs(LineString([(0, 0), (1, 1)]))
        assert lake_structures(setup_state, geographic, None) == ()


def test_the_barrier_lines_are_each_lake_wall_then_each_flow_barrier() -> None:
    from hydromodpy.workflow.steps.mesh_inputs import barrier_lines

    wall = LineString([(1000.0, 100.0), (1000.0, 500.0)])
    fence = LineString([(200.0, 700.0), (800.0, 900.0)])
    flow = SimpleNamespace(
        sinks_sources={
            "lakes": {
                "a": {"polygon": LAKE, "cutoff_wall_line": wall},
                "b": {"polygon": LAKE},
            },
            "flow_barriers": {"f": {"barrier": object(), "line": fence}},
        }
    )

    assert barrier_lines(SimpleNamespace(flow=flow)) == (wall, fence)
    assert barrier_lines(SimpleNamespace(flow=SimpleNamespace(sinks_sources={}))) == ()
