"""The evidence of a selection is written as JSONL tables and as vector layers."""

from __future__ import annotations

import json

import geopandas as gpd
import pytest
from shapely.geometry import Point, box

from hydromodpy.site_selection.config.site_selection_config import OutputConfig
from hydromodpy.site_selection.domain.observation_evidence import ObservationEvidence
from hydromodpy.site_selection.evidence.geology_layers import GeologyEvidence
from hydromodpy.site_selection.evidence.influence import InfluenceEvidence
from hydromodpy.site_selection.outputs.evidence_files import (
    write_site_selection_evidence_outputs,
)
from hydromodpy.site_selection.outputs.evidence_layers import write_evidence_layer
from tests._helpers.site_selection_cases import L93, X93, Y93

pytestmark = pytest.mark.fast

ALL_FORMATS = OutputConfig(write_geojson=True, write_geopackage=True, write_geoparquet=True)


def _evidence(located: bool) -> dict:
    location = {"provider_location": {"x": X93, "y": Y93, "crs": L93}} if located else {}
    kwargs = dict(site_id="site_001", crs=L93 if located else "")
    return {
        "observation_evidence": [ObservationEvidence(
            site_id="site_001", observation_type="piezometer", source_dataset="BSS",
            feature_id="PZ1", evidence_json=location,
        )],
        "influence_evidence": [InfluenceEvidence(
            influence_type="major_dam_upstream", source_layer="Dams", feature_id="D1",
            geometry=Point(X93, Y93) if located else None, **kwargs,
        )],
        "geology_evidence": [GeologyEvidence(
            source_layer="BRGM", geology_class="schist", area_fraction=1.0, area_km2=0.01,
            feature_count=1, geometry=box(X93, Y93, X93 + 100, Y93 + 100) if located else None,
            **kwargs,
        )],
    }  # fmt: skip


def test_located_evidence_is_written_in_every_vector_format(tmp_path):
    evidence = _evidence(located=True)

    paths = write_site_selection_evidence_outputs(
        tmp_path, selection_id="v1", output=ALL_FORMATS,
        piezometer_evidence=evidence["observation_evidence"], **evidence,
    )  # fmt: skip

    assert all(path.is_file() for path in paths.values())
    layers = set(gpd.list_layers(paths["site_selection_gpkg"])["name"])
    assert layers == {"observation_points", "influence_features", "geology_basins"}
    for key in ("observation_points", "influence_features", "geology_basins"):
        assert gpd.read_parquet(paths[f"{key}_geoparquet"]).crs == L93
    for key, kind in (
        ("influence_features", "influence_type"),
        ("geology_basins", "geology_class"),
    ):
        collection = json.loads(paths[f"{key}_geojson"].read_text())
        assert (collection["hydromodpy_geometry_role"], "crs" in collection) == (key, False)
        assert collection["features"][0]["properties"][kind] in {"major_dam_upstream", "schist"}
    lines = paths["site_selection_evidence_jsonl"].read_text().splitlines()
    assert {json.loads(line)["evidence_ref"] for line in lines} == {
        "piezometer:site_001:PZ1", "influence:site_001:major_dam_upstream:D1",
        "geology:site_001:BRGM:schist",
    }  # fmt: skip


@pytest.mark.parametrize(
    ("located", "output", "vectors"),
    [(False, ALL_FORMATS, True), (True, ALL_FORMATS, False), (True, OutputConfig(write_geojson=False), True)],
)  # fmt: skip
def test_evidence_without_geometry_or_vector_output_is_written_as_tables_only(
    tmp_path, located, output, vectors
):
    paths = write_site_selection_evidence_outputs(
        tmp_path, selection_id="v1", output=output, write_observation_vectors=vectors,
        write_context_vectors=vectors, **_evidence(located),
    )  # fmt: skip

    tables = {
        f"{t}_evidence_jsonl" for t in ("geology", "influence", "observation", "site_selection")
    }
    assert {key for key in paths if key.endswith("_jsonl")} == tables
    # The observation GeoJSON keeps the observations it could not place.
    assert set(paths) - tables == (set() if located else {"observation_points_geojson"})


@pytest.mark.parametrize(
    ("crs_values", "label"), [([L93, L93], L93), ([L93, "EPSG:4326"], "mixed")]
)
def test_the_evidence_geojson_names_its_single_project_crs_or_says_mixed(
    tmp_path, crs_values, label
):
    common = dict(site_id="s", source_path=tmp_path / "layer.gpkg")
    geology = [
        GeologyEvidence(source_layer="B", geology_class=f"g{i}", area_fraction=1.0, area_km2=1.0,
                        feature_count=1, geometry=box(0, 0, 1, 1), crs=crs, **common)
        for i, crs in enumerate(crs_values)
    ]  # fmt: skip
    influence = [
        InfluenceEvidence(influence_type="major_dam_upstream", source_layer="D", feature_id=f"d{i}",
                          geometry=Point(0, 0), crs=crs, **common)
        for i, crs in enumerate(crs_values)
    ]  # fmt: skip

    for role, evidence in (("geology_basins", geology), ("influence_features", influence)):
        path = write_evidence_layer(tmp_path / "e.geojson", evidence, role=role, fmt="geojson")
        collection = json.loads(path.read_text())
        assert (collection["hydromodpy_coordinate_crs"], collection["hydromodpy_project_crs"]) == ("OGC:CRS84", label)  # fmt: skip
        assert "crs" not in collection
        assert collection["features"][0]["properties"]["source_path"] == str(common["source_path"])


def test_no_evidence_writes_nothing(tmp_path):
    assert (
        write_site_selection_evidence_outputs(tmp_path, selection_id="v1", output=ALL_FORMATS) == {}
    )
    assert not list(tmp_path.iterdir())
