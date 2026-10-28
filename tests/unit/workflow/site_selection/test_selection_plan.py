from __future__ import annotations

import json

import pytest

from hydromodpy.spatial.site_selection.config.site_selection_config import OutputConfig
from hydromodpy.workflow.site_selection.selection_plan import plan_site_selection
from tests._helpers.site_selection_cases import selection_section, write_selection_toml

pytestmark = pytest.mark.fast

PLANNED = {
    "write_rejected": "rejected",
    "write_selected": "selected",
    "write_geojson": "geojson",
    "write_geoparquet": "geoparquet",
    "write_geopackage": "geopackage",
    "write_csv": "csv",
    "write_report_html": "report_html",
}


@pytest.mark.parametrize("switch", [False, True], ids=["defaults", "all_outputs"])
def test_the_plan_resolves_paths_and_lists_the_switched_outputs(tmp_path, switch):
    output = {key: True for key in PLANNED} if switch else {}
    section = selection_section(output_root="outputs/demo", output=output)

    plan = plan_site_selection(write_selection_toml(tmp_path, section))

    assert plan.config.output_root == tmp_path / "outputs/demo"
    assert plan.manifest["strategy"]["effective_profile"] == "area_only"
    assert plan.manifest["criteria"]["area_mode"] == "hard_reject"
    defaults = OutputConfig()
    expected = [name for key, name in PLANNED.items() if switch or getattr(defaults, key)]
    assert plan.manifest["planned_outputs"] == expected
    if not switch:  # the documented defaults, written out
        assert "selected" in expected
        assert not {"geoparquet", "report_html"} & set(expected)


def test_the_plan_writes_its_manifest(tmp_path):
    plan = plan_site_selection(write_selection_toml(tmp_path, selection_section("gauged")))

    payload = json.loads(plan.write_manifest().read_text(encoding="utf-8"))

    assert payload["selection_id"] == "demo"
    assert payload["strategy"]["candidate_mode"] == "station_outlets"
    assert payload["strategy"]["effective_profile"] == "gauged_downstream_station"
    assert (tmp_path / "out" / "site_selection_plan.json").is_file()
