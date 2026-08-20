"""Integration runs of the site-selection example workflow from fixtures.

Copies the read-only example project into ``tmp_path``, mocks the IGN DEM
fetch, and runs ``run_site_selection_workflow`` end to end (config -> data ->
spatial -> results -> reporting), asserting the emitted artifacts.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from hydromodpy.workflow.site_selection import run_site_selection_workflow

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_ROOT = REPO_ROOT / "examples" / "projects" / "17_site_selection_workflow"
# Short work-directory name on purpose. Each run nests
# outputs/<selection_id>/data/.hmp/backups/cache.duckdb.bak-<stamp> below it, and
# that path overruns the 259-character Windows limit as soon as pytest-xdist adds
# its popen-gwN level to the base temp directory.
WORK_DIRNAME = "ex"


def test_bretagne_hydrometry_primary_example_runs_from_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDROMODPY_WORKSPACE", str(tmp_path / "workspace"))
    work_example = tmp_path / WORK_DIRNAME
    shutil.copytree(
        EXAMPLE_ROOT,
        work_example,
        ignore=shutil.ignore_patterns("data", "outputs"),
    )
    config_path = work_example / "configs" / "bretagne_hydrometry_primary.toml"
    fixture_dem = work_example / "fixtures" / "dem" / "bretagne_synthetic_dem.tif"

    def fake_fetch_ign_dem(*, output_dir, bbox, departments=None, **kwargs):
        assert departments == ["022", "029", "035", "056"]
        assert kwargs["dataset"] == "bd-alti"
        assert kwargs["resolution_m"] == 25.0
        return fixture_dem

    monkeypatch.setattr(
        "hydromodpy.data.variables.dem.apis.ign_dem_fr.fetch_ign_dem",
        fake_fetch_ign_dem,
    )

    summary = run_site_selection_workflow(config_path)

    assert summary["action"] == "delineated_catchments"
    assert summary["selected"] == 2
    assert summary["rejected"] == 2
    assert summary["site_selection_report_html"]
    assert (
        work_example / "outputs" / "bretagne_hydrometry_primary_v1" / "site_selection_manifest.json"
    ).is_file()
    assert (
        work_example / "outputs" / "bretagne_hydrometry_primary_v1" / "review" / "index.html"
    ).is_file()
    assert (
        work_example
        / "outputs"
        / "bretagne_hydrometry_primary_v1"
        / "review"
        / "site_selection_map.png"
    ).is_file()
    assert (
        work_example / "outputs" / "bretagne_hydrometry_primary_v1" / "observation_points.geojson"
    ).is_file()
    observations = json.loads(
        (
            work_example
            / "outputs"
            / "bretagne_hydrometry_primary_v1"
            / "observation_points.geojson"
        ).read_text(encoding="utf-8")
    )
    assert {feature["properties"]["observation_type"] for feature in observations["features"]} == {
        "flow_station",
        "piezometer",
    }


def test_auvergne_rhone_alpes_area_only_example_runs_from_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDROMODPY_WORKSPACE", str(tmp_path / "workspace"))
    work_example = tmp_path / WORK_DIRNAME
    shutil.copytree(
        EXAMPLE_ROOT,
        work_example,
        ignore=shutil.ignore_patterns("data", "outputs"),
    )
    config_path = work_example / "configs" / "auvergne_rhone_alpes_area_only.toml"
    fixture_dem = work_example / "fixtures" / "dem" / "bretagne_synthetic_dem.tif"

    def fake_fetch_ign_dem(*, output_dir, bbox, departments=None, **kwargs):
        assert departments == [
            "001",
            "003",
            "007",
            "015",
            "026",
            "038",
            "042",
            "043",
            "063",
            "069",
            "073",
            "074",
        ]
        assert kwargs["dataset"] == "bd-alti"
        assert kwargs["resolution_m"] == 25.0
        return fixture_dem

    monkeypatch.setattr(
        "hydromodpy.data.variables.dem.apis.ign_dem_fr.fetch_ign_dem",
        fake_fetch_ign_dem,
    )

    summary = run_site_selection_workflow(config_path)

    assert summary["action"] == "delineated_catchments"
    assert summary["selected"] == 20
    assert summary["rejected"] == 0
    assert summary["selected_outlets_geojson"]
    assert summary["selected_basins_geojson"]
    assert summary["site_selection_map_png"]
    assert (work_example / "outputs" / "aura_area_only_v1" / "selected_sites.csv").is_file()
    assert (work_example / "outputs" / "aura_area_only_v1" / "regional_lab_sites.csv").is_file()
    assert (work_example / "outputs" / "aura_area_only_v1" / "selected_outlets.geojson").is_file()
    assert (work_example / "outputs" / "aura_area_only_v1" / "rejected_outlets.geojson").is_file()
    assert (work_example / "outputs" / "aura_area_only_v1" / "selected_basins.geojson").is_file()
    assert (
        work_example / "outputs" / "aura_area_only_v1" / "site_selection_manifest.json"
    ).is_file()
    assert (work_example / "outputs" / "aura_area_only_v1" / "review" / "index.html").is_file()
    assert (
        work_example / "outputs" / "aura_area_only_v1" / "review" / "site_selection_map.png"
    ).is_file()
    selected_basins = json.loads(
        (work_example / "outputs" / "aura_area_only_v1" / "selected_basins.geojson").read_text(
            encoding="utf-8"
        )
    )
    assert len(selected_basins["features"]) == 20
    assert selected_basins["hydromodpy_skipped_basins"] == []
