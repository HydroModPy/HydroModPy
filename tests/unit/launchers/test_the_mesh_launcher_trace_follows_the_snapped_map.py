"""The mesh launcher's river trace follows ``[geographic.snap_streams]``.

A mesh whose ``rivers.source = "file"`` conforms to the mapped network. The
launcher then passes that file, as the mesher reads it: the snapped lines of
the raster snap in ``apply``, the raw file in ``diagnose`` and ``off``. It no
longer needs the DEM-generated trace. With ``source = "geographic_features"``
the trace stays the DEM-generated one, and ``apply`` says why it cannot follow
the snapped map.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from hydromodpy.core.stream_snap import SnapStreamsConfig
from hydromodpy.spatial.geographic.core.raster_stream_snap import (
    RASTER_SNAP_LINES,
    RASTER_SNAP_MANIFEST,
)
from hydromodpy.spatial.mesh.config import MeshCatchmentConfig, MeshCatchmentRiversConfig
from hydromodpy.spatial.mesh.launcher import runtime as mesh_runtime
from hydromodpy.spatial.mesh.launcher.runtime_single_run import _resolve_river_trace

from ._mesh_catchment_builders import _DummyWorkspace

RAW = LineString([(0.0, 0.0), (0.0, 100.0)])
SNAPPED = LineString([(10.0, 0.0), (10.0, 100.0)])
DEM_TRACE = "dem-trace"


@pytest.fixture
def case(tmp_path: Path) -> SimpleNamespace:
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


def _publish(case, *, mode: str) -> None:
    manifest = {
        "mode": mode,
        "source_path": str(case.mapped.resolve()),
        "lines_path": str(case.lines),
    }
    (case.geographic / RASTER_SNAP_MANIFEST).write_text(json.dumps(manifest))


def _geographic_cfg(case, mode: str | None, *, enforce: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        uses_synthetic_geographic=lambda: False,
        river_network=SimpleNamespace(enabled=True),
        crs_project="EPSG:2154",
        snap_streams=None if mode is None else SnapStreamsConfig(mode=mode),
        enforce_streams=SimpleNamespace(stream_geometry_path=str(case.mapped) if enforce else None),
    )


def _features(trace: object | None) -> SimpleNamespace:
    return SimpleNamespace(
        rivers=SimpleNamespace(river_mesh_trace=trace),
        to_domain_geographic_context=lambda: None,
    )


def _resolve(case, mode, *, source="file", trace=DEM_TRACE, enforce=True):
    rivers = (
        MeshCatchmentRiversConfig(source="file", path=str(case.mapped))
        if source == "file"
        else MeshCatchmentRiversConfig()
    )
    return _resolve_river_trace(
        constraints_mode="rivers_only",
        geographic_cfg=_geographic_cfg(case, mode, enforce=enforce),
        geographic_features=_features(trace),
        domain_geographic=case.domain_geographic,
        rivers_cfg=rivers,
        config_path=case.tmp_path / "project.toml",
    )


def _xs(trace) -> set[float]:
    return {x for line in trace.lines for x, _ in line.coords}


def test_a_file_mesh_follows_the_snapped_lines_in_apply(case) -> None:
    _publish(case, mode="apply")

    assert _xs(_resolve(case, "apply")) == {10.0}


def test_a_file_mesh_reads_the_raw_file_in_diagnose(case) -> None:
    _publish(case, mode="diagnose")

    assert _xs(_resolve(case, "diagnose")) == {0.0}


@pytest.mark.parametrize("mode", [None, "off"])
def test_a_file_mesh_reads_the_raw_file_when_the_snap_is_off(case, mode) -> None:
    assert _xs(_resolve(case, mode)) == {0.0}


def test_a_file_mesh_needs_no_dem_trace(case) -> None:
    assert _xs(_resolve(case, None, trace=None)) == {0.0}


def test_apply_without_the_raster_snap_reads_the_raw_file_and_says_why(case, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        trace = _resolve(case, "apply", enforce=False)

    assert _xs(trace) == {0.0}
    assert "[geographic.enforce_streams] stream_geometry_path" in caplog.text


def test_apply_without_snapped_lines_is_refused(case) -> None:
    _publish(case, mode="apply")
    case.lines.unlink()

    with pytest.raises(ValueError, match="published no snapped line"):
        _resolve(case, "apply")


def test_a_missing_mapped_file_is_named(case) -> None:
    case.mapped.unlink()

    with pytest.raises(ValueError, match="rivers.path does not exist"):
        _resolve(case, "apply")


@pytest.mark.parametrize("mode", [None, "off"])
def test_a_dem_mesh_keeps_the_dem_trace_when_the_snap_is_off(case, mode, caplog) -> None:
    with caplog.at_level(logging.INFO):
        assert _resolve(case, mode, source="geographic_features") == DEM_TRACE
    assert "snap_streams" not in caplog.text


def test_a_dem_mesh_keeps_the_dem_trace_in_apply_and_says_why(case, caplog) -> None:
    _publish(case, mode="apply")
    with caplog.at_level(logging.INFO):
        assert _resolve(case, "apply", source="geographic_features") == DEM_TRACE
    assert "network generated from the DEM" in caplog.text


def test_the_launcher_passes_the_snapped_trace_to_the_mesher(monkeypatch, case) -> None:
    _publish(case, mode="apply")
    captured: dict[str, object] = {}

    def _fake_run_case(config_toml, **kwargs):
        _ = config_toml
        captured["case"] = kwargs["river_trace"]
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.run_zone_conformal_meshing_from_toml",
        _fake_run_case,
    )
    workspace_cfg = SimpleNamespace(project_root=case.tmp_path / "projects" / "mesh_case")

    mesh_runtime.run_single_mesh_catchment_workflow(
        config_path=case.tmp_path / "project.toml",
        section_data=MeshCatchmentConfig.model_validate(
            {
                "constraints_mode": "rivers_only",
                "export_exchange_bundle": False,
                "rivers": {"source": "file", "path": str(case.mapped)},
            }
        ),
        workspace_cfg=workspace_cfg,
        geographic_cfg=_geographic_cfg(case, "apply"),
        domain_cfg=None,
        constraints_mode="rivers_only",
        workspace=_DummyWorkspace(workspace_cfg),
        geographic_features=_features(DEM_TRACE),
        domain_geographic=case.domain_geographic,
    )

    assert _xs(captured["case"]) == {10.0}
