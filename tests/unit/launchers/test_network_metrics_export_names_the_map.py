"""The network metrics CSV exports name the map they read and the snap mode.

``network_map`` and ``snap_mode`` are columns of the overlap and distance
exports. Under ``[geographic.snap_streams] mode = "apply"`` the row scores the
snapped map the run stored; with the snap off it scores the raw map, with the
numbers it always had.
"""

from __future__ import annotations

import csv
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point

from hydromodpy.analysis.comparison.exports import (
    write_simulated_active_network_distance_metrics_export,
    write_simulated_active_network_overlap_metrics_export,
)
from hydromodpy.analysis.comparison.exports.base import (
    CELL_FIELD_NETWORK_DISTANCE_METRICS_FIELDS,
    CELL_FIELD_NETWORK_OVERLAP_METRICS_FIELDS,
)
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.derive.snapped_network import SNAPPED_NETWORK_FEATURES

from ._hydrographic_network_metrics_export_builders import (
    _register_completed_active_network_run,
)


def _summaries(config_path: Path, sim_id: str, tmp_path: Path) -> list[dict]:
    return [
        {
            "id": "mf6_demo",
            "label": "MF6 demo",
            "solver": "modflow6",
            "mesh_mode": "structured",
            "config_path": str(config_path),
            "run_folder": str(tmp_path / "run_folder"),
            "sim_id": sim_id,
            "run_name": "active_network_demo",
            "status": "completed",
        }
    ]


def _case(tmp_path: Path, mode: str | None) -> list[dict]:
    workspace_root = tmp_path / "workspace"
    snapshot = None if mode is None else {"geographic": {"snap_streams": {"mode": mode}}}
    config_path, sim_id = _register_completed_active_network_run(
        workspace_root, config_snapshot=snapshot
    )
    # The raw map lies in cell 1, where the flux is active; the snap moved it to cell 2.
    catalog = Catalog(workspace_root)
    try:
        catalog.write_geographic_feature(
            sim_id,
            SNAPPED_NETWORK_FEATURES["maximal"],
            gpd.GeoDataFrame(
                {
                    "raw_cell": [1],
                    "snapped_cell": [2],
                    "status": ["moved"],
                    "displacement_m": [1.0],
                    "raw_x": [1.5],
                    "raw_y": [0.5],
                    "accumulation_percentile": [90.0],
                },
                geometry=[Point(2.5, 0.5)],
                crs="EPSG:2154",
            ),
        )
    finally:
        catalog.close()
    return _summaries(config_path, sim_id, tmp_path)


def _csv(artifacts: list[dict]) -> list[dict]:
    (artifact,) = [item for item in artifacts if item["kind"].endswith("_csv")]
    with Path(artifact["path"]).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@pytest.mark.parametrize(
    "fields",
    [CELL_FIELD_NETWORK_OVERLAP_METRICS_FIELDS, CELL_FIELD_NETWORK_DISTANCE_METRICS_FIELDS],
)
def test_the_field_lists_carry_the_map_and_the_snap_mode(fields) -> None:
    assert "network_map" in fields
    assert "snap_mode" in fields


def test_the_overlap_export_scores_the_snapped_map_in_apply(tmp_path: Path) -> None:
    artifacts, _ = write_simulated_active_network_overlap_metrics_export(
        comparison_id="demo_compare",
        comparison_root=tmp_path / "comparison_outputs",
        simulation_summaries=_case(tmp_path, "apply"),
    )
    (row,) = _csv(artifacts)

    assert row["network_map"] == "snapped"
    assert row["snap_mode"] == "apply"
    assert row["network_cell_count"] == "1"
    assert float(row["network_coverage_ratio"]) == pytest.approx(0.0)


@pytest.mark.parametrize("mode", [None, "off"])
def test_the_overlap_export_is_unchanged_when_the_snap_is_off(tmp_path: Path, mode) -> None:
    artifacts, _ = write_simulated_active_network_overlap_metrics_export(
        comparison_id="demo_compare",
        comparison_root=tmp_path / "comparison_outputs",
        simulation_summaries=_case(tmp_path, mode),
    )
    (row,) = _csv(artifacts)

    assert row["network_map"] == "raw"
    assert row["snap_mode"] == "off"
    assert row["network_cell_count"] == "1"
    assert float(row["network_coverage_ratio"]) == pytest.approx(1.0)
    assert float(row["cell_jaccard_ratio"]) == pytest.approx(1.0)


@pytest.mark.parametrize(("mode", "network_map"), [("apply", "snapped"), ("off", "raw")])
def test_the_distance_export_names_the_map(tmp_path: Path, mode, network_map) -> None:
    artifacts, _ = write_simulated_active_network_distance_metrics_export(
        comparison_id="demo_compare",
        comparison_root=tmp_path / "comparison_outputs",
        simulation_summaries=_case(tmp_path, mode),
    )
    (row,) = _csv(artifacts)

    assert row["network_map"] == network_map
    assert row["snap_mode"] == mode
