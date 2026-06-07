from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import LineString

from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._refinement_grid import (
    RefinementGridCellId,
    build_refinement_grid,
)


@dataclass(frozen=True)
class _CurveCandidate:
    curve_tag: int
    family: str
    geometry: LineString


def test_build_refinement_grid_indexes_curve_bboxes_on_multiple_cells() -> None:
    grid = build_refinement_grid(
        candidates=(
            _CurveCandidate(
                curve_tag=1,
                family="river",
                geometry=LineString([(0.2, 0.2), (2.4, 0.2)]),
            ),
            _CurveCandidate(
                curve_tag=2,
                family="geology_interface",
                geometry=LineString([(1.2, 1.2), (1.2, 2.8)]),
            ),
        ),
        cell_size=1.0,
    )

    assert grid.row_count == 3
    assert grid.col_count == 3
    assert grid.curve_footprints[1].cell_ids == (
        RefinementGridCellId(row=0, col=0),
        RefinementGridCellId(row=0, col=1),
        RefinementGridCellId(row=0, col=2),
    )
    assert grid.curve_footprints[2].cell_ids == (
        RefinementGridCellId(row=1, col=1),
        RefinementGridCellId(row=2, col=1),
    )


def test_refinement_grid_collects_neighborhood_curve_tags_with_deduplication() -> None:
    grid = build_refinement_grid(
        candidates=(
            _CurveCandidate(
                curve_tag=1,
                family="river",
                geometry=LineString([(0.2, 0.2), (2.4, 0.2)]),
            ),
            _CurveCandidate(
                curve_tag=2,
                family="geology_interface",
                geometry=LineString([(1.2, 1.2), (1.2, 2.8)]),
            ),
        ),
        cell_size=1.0,
    )

    curve_tags = grid.collect_neighborhood_curve_tags(
        RefinementGridCellId(row=1, col=1),
        rings=1,
    )

    assert curve_tags == (1, 2)


def test_refinement_grid_neighborhood_is_clipped_to_bounds() -> None:
    grid = build_refinement_grid(
        candidates=(
            _CurveCandidate(
                curve_tag=1,
                family="river",
                geometry=LineString([(0.0, 0.0), (0.5, 0.5)]),
            ),
        ),
        cell_size=1.0,
    )

    neighborhood = grid.iter_neighborhood_cell_ids(
        RefinementGridCellId(row=0, col=0),
        rings=2,
    )

    assert neighborhood == (RefinementGridCellId(row=0, col=0),)
