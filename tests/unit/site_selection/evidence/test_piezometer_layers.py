"""Piezometer layers give each basin its nearby piezometers and their distances."""

from __future__ import annotations

import pytest
from shapely.geometry import Point, box

from hydromodpy.spatial.site_selection.config.criteria_config import (
    CriteriaConfig,
    ObservationsCriteriaConfig,
    PiezometerLayerConfig,
)
from hydromodpy.spatial.site_selection.config.outlets_config import SpatialSelectionConfig
from hydromodpy.spatial.site_selection.evaluation.selection import select_delineated_catchments
from hydromodpy.spatial.site_selection.evidence.piezometer_layers import (
    annotate_catchments_with_piezometer_layers,
)
from tests._helpers.site_selection_cases import (
    L93,
    X93,
    Y93,
    make_basin_catchment,
    write_vector_layer,
)

pytestmark = pytest.mark.fast

WELLS = {
    "id": ["PZ_IN", "PZ_BOX", "PZ_NEAR", "PZ_FAR", "PZ_LOST"],
    "label": ["Close piezometer", None, "Near", "Far", "Lost"],
    "years": ["4.5", "n/a", "2", "1", "3"],
    "quality": ["good", None, "partial", "good", "good"],
}
GEOMETRIES = [
    Point(X93 + 40.0, Y93 + 40.0),
    box(X93 + 20.0, Y93 + 20.0, X93 + 22.0, Y93 + 22.0),
    Point(X93 - 500.0, Y93 + 10.0),
    Point(X93 + 5000.0, Y93 + 5000.0),
    None,
]


def _config(tmp_path, *, radius=None, crs=L93, mode="report_only"):
    layer = write_vector_layer(tmp_path / "piezometers.gpkg", GEOMETRIES, crs=crs, **WELLS)
    return ObservationsCriteriaConfig(
        piezometer_mode=mode,
        piezometer_max_distance_km=radius,
        piezometer_layers=[
            PiezometerLayerConfig(
                name="BSS demo", path=layer, id_field="id", label_field="label",
                record_years_field="years", quality_field="quality",
            )
        ],
    )  # fmt: skip


def test_the_nearest_piezometer_inside_the_basin_passes_the_criterion(tmp_path):
    config = _config(tmp_path, radius=1.0, mode="hard_reject")

    (annotated,), evidence = annotate_catchments_with_piezometer_layers(
        [make_basin_catchment(tmp_path)], config=config
    )

    attributes = annotated.outlet.attributes
    assert (attributes["piezometer_count"], attributes["piezometers_in_basin"]) == (3, 2)
    assert attributes["piezometer_inside_basin"] is True
    assert attributes["piezometer_id"] == "PZ_BOX"
    assert attributes["nearest_piezometer_distance_km"] == pytest.approx(0.01414, rel=1e-3)
    close = next(item for item in evidence if item.feature_id == "PZ_IN")
    assert (close.record_year_count, close.quality_status) == (4.5, "good")
    assert close.evidence_json["provider_location"] == {"x": X93 + 40, "y": Y93 + 40, "crs": L93}
    square = next(item for item in evidence if item.feature_id == "PZ_BOX")
    assert (square.feature_label, square.record_year_count, square.quality_status) == (
        "PZ_BOX", None, "unknown",
    )  # fmt: skip
    result = select_delineated_catchments(
        [annotated],
        criteria=CriteriaConfig(observations=config),
        spatial_selection=SpatialSelectionConfig(),
        selection_principle="criteria_crossing",
    )
    assert [item.site_id for item in result.selected] == ["site_001"]
    component = next(
        item for item in result.criteria_components if item.criterion_id == "piezometer"
    )
    assert component.criterion_status == "passed"


@pytest.mark.parametrize(
    ("basin", "radius", "crs", "matches"),
    [
        ("l93", None, L93, {"PZ_IN": 0.0, "PZ_BOX": 0.0}),
        ("l93", 1.0, None, {"PZ_IN": 0.0, "PZ_BOX": 0.0, "PZ_NEAR": 0.5}),
        ("none", 1.0, L93, {"PZ_IN": None, "PZ_BOX": None, "PZ_NEAR": None}),
        ("none", None, L93, {}),
        ("empty", None, L93, {}),
    ],
)
def test_a_piezometer_counts_inside_the_basin_or_within_the_search_radius(
    tmp_path, basin, radius, crs, matches
):
    _annotated, evidence = annotate_catchments_with_piezometer_layers(
        [make_basin_catchment(tmp_path, basin)], config=_config(tmp_path, radius=radius, crs=crs)
    )

    distances = {item.feature_id: item.distance_to_basin_km for item in evidence}
    assert distances == pytest.approx(matches)
    assert all(item.distance_to_outlet_km <= 1.0 for item in evidence)


def test_no_piezometer_layer_leaves_the_catchments_as_they_are(tmp_path):
    catchment = make_basin_catchment(tmp_path)

    assert annotate_catchments_with_piezometer_layers(
        [catchment], config=ObservationsCriteriaConfig()
    ) == ([catchment], [])
    empty = PiezometerLayerConfig(
        name="BSS", path=write_vector_layer(tmp_path / "e.gpkg", [], id=[])
    )
    config = ObservationsCriteriaConfig(piezometer_max_distance_km=1.0, piezometer_layers=[empty])
    assert annotate_catchments_with_piezometer_layers([catchment], config=config) == (
        [catchment],
        [],
    )
