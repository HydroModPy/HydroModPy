"""Execute the production zone-conformal entry point against a real TOML file.

``run_zone_conformal_meshing_from_toml`` is the function the mesh-catchment
launcher wires its runs to, and every launcher unit test stubs it out. The
neighbouring end-to-end tests do reach it, but always through the demo wrapper
and always with the output paths passed as keyword arguments, so two production
paths stayed unexecuted: the ``output_mesh`` / ``output_summary_json`` /
``output_figure`` keys read from the TOML and resolved relative to the config
file, and the content of the JSON sidecar the entry point writes. This test
guards both: a regression in that wiring would silently drop the sidecar or
write it next to the wrong directory, and no other test would notice.
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import matplotlib
import pytest
from shapely.geometry import LineString, Polygon

matplotlib.use("Agg", force=True)

try:
    import gmsh  # noqa: F401

    _gmsh_available = True
except (ImportError, OSError):
    _gmsh_available = False
_skip_no_gmsh = pytest.mark.skipif(not _gmsh_available, reason="gmsh not available")

import hydromodpy

# Domain loading consumes the GeologyDataSource registered by bootstrap; force
# it so this file is order-independent when run in isolation (its own CI tier).
hydromodpy.bootstrap()

from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.orchestration.runner import (
    run_zone_conformal_meshing_from_toml,
)

# One small square catchment window in Lambert-93, crossed by one straight
# stream. Keeping the domain at 1 km and the target size at 200 m holds the
# whole run near one second.
_X0 = 350000.0
_Y0 = 6800000.0
_SIDE = 1000.0

_CASE_TOML = """
[mesh_case]
constraints_mode = "rivers_only"
output_mesh = "outputs/zone_conformal.msh"
output_summary_json = "outputs/zone_conformal_summary.json"
output_figure = "outputs/zone_conformal.png"
figure_dpi = 60

[mesh_case.domain]
kind = "vector"
path = "domain.geojson"
id_field = "domain_id"
selected_id = "main"

[mesh_case.zone_meshing]
algorithm = "delaunay"
global_size = 200.0
min_size = 80.0
max_size = 300.0
refine_interfaces = true
interface_size = 90.0
interface_distance = 250.0
interface_sampling = 24

[mesh_case.rivers]
source = "file"
path = "rivers.geojson"
clip_to_domain = true
min_segment_length = 0.0
snap_tolerance = 0.0
"""


def _write_case_inputs(case_dir: Path) -> Path:
    """Write the domain, the river trace and the case TOML, return the TOML path."""
    gpd.GeoDataFrame(
        {"domain_id": ["main"]},
        geometry=[
            Polygon(
                [
                    (_X0, _Y0),
                    (_X0 + _SIDE, _Y0),
                    (_X0 + _SIDE, _Y0 + _SIDE),
                    (_X0, _Y0 + _SIDE),
                ]
            )
        ],
        crs="EPSG:2154",
    ).to_file(case_dir / "domain.geojson", driver="GeoJSON")
    gpd.GeoDataFrame(
        {"name": ["main_stem"]},
        geometry=[LineString([(_X0 + 100.0, _Y0 + 500.0), (_X0 + 900.0, _Y0 + 520.0)])],
        crs="EPSG:2154",
    ).to_file(case_dir / "rivers.geojson", driver="GeoJSON")
    config_path = case_dir / "case_zone_conformal.toml"
    config_path.write_text(_CASE_TOML, encoding="utf-8")
    return config_path


@_skip_no_gmsh
def test_zone_conformal_from_toml_writes_mesh_sidecar_and_figure(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir(parents=True, exist_ok=True)
    config_path = _write_case_inputs(case_dir)

    summary = run_zone_conformal_meshing_from_toml(config_path)

    # Output paths come from the TOML only, resolved against the config file.
    expected_outputs = case_dir / "outputs"
    assert Path(summary["output_mesh"]) == expected_outputs / "zone_conformal.msh"
    assert Path(summary["output_summary_json"]) == expected_outputs / "zone_conformal_summary.json"
    assert Path(summary["output_figure"]) == expected_outputs / "zone_conformal.png"
    for key in ("output_mesh", "output_summary_json", "output_figure"):
        assert Path(summary[key]).is_file(), key
    assert Path(summary["output_figure"]).stat().st_size > 0

    # The mesh really was built on the configured domain and river constraint.
    assert summary["summary_schema_version"] == "zone_conformal_sidecar_v1"
    assert summary["mesh_kind"] == "gmsh_2d"
    assert summary["n_cells"] > 0
    assert summary["n_nodes"] > 0
    assert summary["global_size"] == 200.0
    assert summary["domain_kind"] == "vector"
    assert summary["domain_crs"] == "EPSG:2154"
    assert summary["domain_area"] == pytest.approx(_SIDE * _SIDE)
    assert summary["constraints_mode"] == "rivers_only"
    assert summary["rivers_config"]["source"] == "file"
    assert summary["rivers_config"]["path"] == "rivers.geojson"
    assert summary["river_trace"]["provided"] is True
    assert summary["river_trace"]["curve_count"] > 0
    assert summary["river_trace"]["embedded_surface_curve_pairs"] > 0
    assert summary["constraints_qa"]["mode"] == "rivers_only"
    assert summary["constraints_qa"]["overall_pass"] is True
    assert summary["qa_checks"]["constraints_contract_pass"] is True

    # The sidecar holds the same finalized payload, not a truncated one.
    sidecar = json.loads(Path(summary["output_summary_json"]).read_text(encoding="utf-8"))
    assert sidecar == summary
