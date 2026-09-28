"""A mesh river constraint read from the mapped file follows ``[geographic.snap_streams]``.

The geographic step publishes the raster snap of the mapped network. A mesh
whose ``rivers.source = "file"`` names that same file reads the snapped lines
in ``apply``, and the raw file in ``diagnose``, with no snap, or for another
file. ``source = "file"`` wins over a trace passed in.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from hydromodpy.spatial.geographic.core.raster_stream_snap import (
    RASTER_SNAP_LINES,
    RASTER_SNAP_MANIFEST,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.orchestration.contracts import (
    ZoneConformalRiversConfig,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.orchestration.planning import (
    _resolve_river_trace_for_meshing,
)

RAW = LineString([(0.0, 0.0), (0.0, 100.0)])
SNAPPED = LineString([(10.0, 0.0), (10.0, 100.0)])


@pytest.fixture
def workspace(tmp_path: Path) -> SimpleNamespace:
    mapped = tmp_path / "streams.gpkg"
    gpd.GeoDataFrame({"id": [1]}, geometry=[RAW], crs="EPSG:2154").to_file(mapped, driver="GPKG")
    geographic = tmp_path / "geographic"
    geographic.mkdir()
    lines = geographic / RASTER_SNAP_LINES
    gpd.GeoDataFrame({"part": [0]}, geometry=[SNAPPED], crs="EPSG:2154").to_file(
        lines, driver="GPKG"
    )
    return SimpleNamespace(
        tmp_path=tmp_path,
        mapped=mapped,
        geographic=geographic,
        lines=lines,
        domain_geographic=SimpleNamespace(watershed_shp=str(geographic / "watershed.shp")),
    )


def _publish(workspace, *, mode: str, source: Path | None = None) -> None:
    manifest = {
        "mode": mode,
        "source_path": str((source or workspace.mapped).resolve()),
        "lines_path": str(workspace.lines),
    }
    (workspace.geographic / RASTER_SNAP_MANIFEST).write_text(json.dumps(manifest))


def _resolve(workspace, *, river_trace: object | None = None):
    return _resolve_river_trace_for_meshing(
        river_trace=river_trace,
        geographic_features=None,
        rivers_cfg=ZoneConformalRiversConfig(
            source="file",
            path=str(workspace.mapped),
            clip_to_domain=True,
            min_segment_length=0.0,
            snap_tolerance=0.0,
        ),
        config_path=workspace.tmp_path / "project.toml",
        domain_geographic=workspace.domain_geographic,
    )


def _xs(trace) -> set[float]:
    return {x for line in trace.lines for x, _ in line.coords}


def test_apply_reads_the_snapped_lines(workspace) -> None:
    _publish(workspace, mode="apply")

    assert _xs(_resolve(workspace)) == {10.0}


def test_diagnose_reads_the_raw_file(workspace) -> None:
    _publish(workspace, mode="diagnose")

    assert _xs(_resolve(workspace)) == {0.0}


def test_no_snap_reads_the_raw_file(workspace) -> None:
    assert _xs(_resolve(workspace)) == {0.0}


def test_a_snap_of_another_file_is_not_read(workspace) -> None:
    _publish(workspace, mode="apply", source=workspace.tmp_path / "other.gpkg")

    assert _xs(_resolve(workspace)) == {0.0}


def test_apply_without_snapped_lines_is_refused(workspace) -> None:
    _publish(workspace, mode="apply")
    workspace.lines.unlink()

    with pytest.raises(ValueError, match="published no snapped line"):
        _resolve(workspace)


def test_the_mapped_file_wins_over_a_trace_passed_in(workspace) -> None:
    assert _xs(_resolve(workspace, river_trace=SimpleNamespace(lines=(SNAPPED,)))) == {0.0}
