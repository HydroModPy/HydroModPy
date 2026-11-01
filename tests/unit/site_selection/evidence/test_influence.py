import pytest
from shapely.geometry import Point

from hydromodpy.site_selection.config.criteria_config import (
    InfluenceCriteriaConfig,
    InfluenceLayerConfig,
)
from hydromodpy.site_selection.evidence.influence import (
    annotate_catchments_with_influence_layers,
)
from tests._helpers.site_selection_cases import (
    L93,
    X93,
    Y93,
    component_of,
    make_basin_catchment,
    run_selection,
    to_wgs84,
    write_vector_layer,
)

pytestmark = pytest.mark.fast

INSIDE, NEAR = Point(X93 + 40.0, Y93 + 40.0), Point(X93 - 500.0, Y93)


def _config(tmp_path, points, *, crs=L93, radius=None, mode="report_only", **columns):
    path = write_vector_layer(tmp_path / "dams.gpkg", points, crs=crs, **columns)
    layer = InfluenceLayerConfig(
        name="Dams", path=path, influence_type="major_dam_upstream", major_values=["major"],
        **{f"{key}_field": key for key in ("id", "label", "severity") if key in columns},
    )  # fmt: skip
    return InfluenceCriteriaConfig(
        mode=mode, reject_major_dam_upstream=True, influence_search_radius_km=radius, layers=[layer]
    )


def test_a_major_dam_inside_the_basin_rejects_the_catchment(tmp_path):
    config = _config(
        tmp_path, [INSIDE, Point(X93 + 60.0, Y93 + 60.0)], mode="hard_reject",
        id=["DAM001", "DAM002"], label=["Demo dam", None], severity=["major", "minor"],
    )  # fmt: skip

    (annotated,), evidence = annotate_catchments_with_influence_layers(
        [make_basin_catchment(tmp_path)], config=config
    )

    assert [(item.feature_id, item.feature_label, item.major) for item in evidence] == [
        ("DAM001", "Demo dam", True), ("DAM002", "DAM002", False),
    ]  # fmt: skip
    refs = ["influence:site_001:major_dam_upstream:DAM001", "influence:site_001:major_dam_upstream:DAM002"]  # fmt: skip
    attributes = annotated.outlet.attributes
    assert (attributes["major_dam_upstream"], attributes["upstream_dam_count"]) == (True, 1)
    assert attributes["major_dam_upstream_feature_count"] == 2
    assert attributes["major_dam_upstream_evidence_refs"] == refs
    assert attributes["influence_status"] == "known"
    result = run_selection([annotated], {"influence": config}, "observation_led")
    assert (result.selected, [item.site_id for item in result.rejected]) == ([], ["site_001"])
    component = component_of(result, "influence")
    assert component.blocking
    assert component.evidence_json["evidence_ref"] == refs[0]


@pytest.mark.parametrize(("basin", "point", "crs", "radius", "relations"), [
    ("l93", INSIDE, L93, None, ["intersects_basin"]),
    ("l93", INSIDE, None, None, ["intersects_basin"]),
    ("l93", to_wgs84(INSIDE), "EPSG:4326", None, ["intersects_basin"]),
    ("wgs84", INSIDE, L93, None, ["intersects_basin"]),
    ("no_crs", INSIDE, L93, None, ["intersects_basin"]),
    ("l93", NEAR, L93, 1.0, []),
    ("none", NEAR, L93, 1.0, ["within_outlet_search_radius"]),
    ("none", NEAR, L93, None, []),
    ("empty", NEAR, L93, 1.0, ["within_outlet_search_radius"]),
    ("no_rows", NEAR, L93, 1.0, ["within_outlet_search_radius"]),
    ("l93", None, L93, None, []),
])  # fmt: skip
def test_influence_features_are_matched_whatever_crs_the_layers_carry(
    tmp_path, basin, point, crs, radius, relations
):
    config = _config(tmp_path, [point] if point else [], crs=crs, radius=radius)
    (annotated,), evidence = annotate_catchments_with_influence_layers(
        [make_basin_catchment(tmp_path, basin)], config=config
    )
    assert [item.relation for item in evidence] == relations
    assert all(item.feature_id == "0" and item.feature_index == 0 for item in evidence)
    assert annotated.outlet.attributes.get("major_dam_upstream") is (True if relations else None)


def test_no_influence_layer_leaves_the_catchments_as_they_are(tmp_path):
    catchment = make_basin_catchment(tmp_path)
    assert annotate_catchments_with_influence_layers([catchment], config=InfluenceCriteriaConfig()) == ([catchment], [])  # fmt: skip


def test_a_withdrawal_inside_the_basin_is_reported_under_its_own_type(tmp_path):
    layer = write_vector_layer(tmp_path / "withdrawals.gpkg", [INSIDE], crs=L93, id=["W001"])
    withdrawals = InfluenceLayerConfig(
        name="Withdrawals", path=layer, influence_type="major_withdrawal_upstream", id_field="id"
    )
    config = InfluenceCriteriaConfig(layers=[withdrawals])

    (annotated,), (item,) = annotate_catchments_with_influence_layers(
        [make_basin_catchment(tmp_path)], config=config
    )

    assert (item.influence_type, item.feature_id) == ("major_withdrawal_upstream", "W001")
    attributes = annotated.outlet.attributes
    assert attributes["major_withdrawal_upstream_feature_count"] == 1
    assert item.major  # no severity field: every feature counts as major
    assert attributes["upstream_major_withdrawal_count"] == 1
