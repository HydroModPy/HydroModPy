import pytest
from shapely.geometry import box

from hydromodpy.site_selection.config.criteria_config import (
    GeologyCriteriaConfig,
    GeologyLayerConfig,
)
from hydromodpy.site_selection.evidence.geology_layers import (
    annotate_catchments_with_geology_layers,
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


def _units(x0: float, x1: float):
    return box(X93 + x0, Y93, X93 + x1, Y93 + 100.0)


UNITS = {
    "id": ["G001", "G002", "G003", "G004", "G005"],
    "label": ["Schist unit", "", "Far", "Touching", "Unnamed"],
    "class": ["schist", "granite", "limestone", "sand", ""],
    "geometry": [_units(0, 60), _units(60, 100), _units(500, 600), _units(100, 150), _units(0, 10)],
}


def _config(tmp_path, *, crs=L93, mode="stratify") -> GeologyCriteriaConfig:
    geometries = UNITS["geometry"] if crs != "EPSG:4326" else map(to_wgs84, UNITS["geometry"])
    columns = {key: value for key, value in UNITS.items() if key != "geometry"}
    layer = write_vector_layer(tmp_path / "geology.gpkg", list(geometries), crs=crs, **columns)
    layers = [
        GeologyLayerConfig(name="BRGM demo", path=layer, class_field="class", id_field="id", label_field="label")
    ]  # fmt: skip
    return GeologyCriteriaConfig(mode=mode, layers=layers)


def test_the_dominant_geology_of_a_basin_is_its_largest_class(tmp_path):
    config = _config(tmp_path)

    (annotated,), evidence = annotate_catchments_with_geology_layers(
        [make_basin_catchment(tmp_path)], config=config
    )

    attributes = annotated.outlet.attributes
    assert (attributes["dominant_geology"], attributes["geology_diversity_count"]) == ("schist", 2)
    assert attributes["geology_fractions_json"] == '{"granite": 0.4, "schist": 0.6}'
    assert [(item.geology_class, item.feature_labels) for item in evidence] == [
        ("granite", ["G002"]), ("schist", ["Schist unit"]),
    ]  # fmt: skip
    assert evidence[0].evidence_json["coverage_fraction"] == pytest.approx(1.0)
    component = component_of(run_selection([annotated], {"geology": config}), "geology")
    assert (component.raw_value, component.criterion_status) == ("schist", "stratified")


@pytest.mark.parametrize(("basin", "crs", "fractions"), [
    ("l93", None, {"granite": 0.4, "schist": 0.6}),
    ("l93", "EPSG:4326", {"granite": 0.4, "schist": 0.6}),
    ("wgs84", L93, {"granite": 0.4, "schist": 0.6}),
    ("none", L93, {}),
    ("empty", L93, {}),
    ("no_rows", L93, {}),
])  # fmt: skip
def test_geology_shares_hold_whatever_crs_the_layers_carry(tmp_path, basin, crs, fractions):
    _annotated, evidence = annotate_catchments_with_geology_layers(
        [make_basin_catchment(tmp_path, basin)], config=_config(tmp_path, crs=crs)
    )
    # A reprojected layer leaves a sliver of the unit that only touches the basin.
    shares = {
        item.geology_class: item.area_fraction for item in evidence if item.area_fraction > 1e-6
    }
    assert shares == pytest.approx(fractions, rel=1e-3)
    assert sum(shares.values()) == pytest.approx(1.0 if fractions else 0.0, rel=1e-3)


def test_no_geology_layer_leaves_the_catchments_as_they_are(tmp_path):
    catchment = make_basin_catchment(tmp_path)
    assert annotate_catchments_with_geology_layers([catchment], config=GeologyCriteriaConfig()) == ([catchment], [])  # fmt: skip


@pytest.mark.parametrize("units", [slice(0, 0), slice(2, 3)], ids=["no-unit", "far-unit"])
def test_a_layer_without_a_unit_in_the_basin_gives_no_evidence(tmp_path, units):
    layer = write_vector_layer(
        tmp_path / "g.gpkg", UNITS["geometry"][units], unit=UNITS["class"][units]
    )
    layers = [GeologyLayerConfig(name="BRGM", path=layer, class_field="unit")]

    (annotated,), evidence = annotate_catchments_with_geology_layers(
        [make_basin_catchment(tmp_path)], config=GeologyCriteriaConfig(layers=layers)
    )

    assert evidence == []
    assert "dominant_geology" not in annotated.outlet.attributes
