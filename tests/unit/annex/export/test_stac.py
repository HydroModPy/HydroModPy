"""STAC item of a run: bounding box polygon, UTC instants, union of boxes (degrees or metres)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.results.export.context import AssetEntry, FairExportContext
from hydromodpy.results.exporters.port import RUN_VIEW, ExportWriter
from hydromodpy_annex.export.stac import (
    StacItemView,
    _bbox_to_polygon,
    _midpoint,
    _to_utc_iso,
    _union_bbox,
    build_stac_item,
    validate_item,
)

pytestmark = pytest.mark.fast


def _make_context(
    *,
    sim_row: dict | None = None,
    assets: tuple[AssetEntry, ...] = (),
) -> FairExportContext:
    row = {
        "sim_id": "sim-001",
        "name": "fair-sim",
        "project": "test",
        "solver_id": "modflow6",
        "n_cells": 8,
        "n_layers": 1,
        "n_timesteps": 6,
        "bbox_xmin": 0.0,
        "bbox_ymin": 0.0,
        "bbox_xmax": 1000.0,
        "bbox_ymax": 1000.0,
        "crs_epsg": 2154,
        "crs_wkt": "EPSG:2154",
        "period_start": "2020-01-01",
        "period_end": "2020-01-06",
    }
    if sim_row is not None:
        row = sim_row
    return FairExportContext(
        sim_id=str(row.get("sim_id", "sim-001")),
        sim_row=row,
        runs_env={},
        workspace_meta={},
        workspace_path=Path("/tmp/ws"),
        license_url="https://creativecommons.org/licenses/by/4.0/",
        creator_name="Jane Doe",
        creator_email="jane@example.org",
        assets=assets,
        inputs=(),
        lockfile_path=None,
        solver_binary_sha256=None,
        solver_name=None,
        solver_version=None,
        hydromodpy_version="0.0.0-test",
    )


def test_bbox_to_polygon_ring() -> None:
    ring = _bbox_to_polygon((1.0, 2.0, 3.0, 4.0))["coordinates"][0]
    # Counter-clockwise from the lower left corner, closed on its first vertex.
    assert _bbox_to_polygon((1.0, 2.0, 3.0, 4.0))["type"] == "Polygon"
    assert ring == [[1.0, 2.0], [3.0, 2.0], [3.0, 4.0], [1.0, 4.0], [1.0, 2.0]]


UTC_INSTANTS = [
    pytest.param("2020-01-01", "2020-01-01T00:00:00Z", id="naive date at midnight"),
    pytest.param("2020-06-01T12:00:00+02:00", "2020-06-01T10:00:00Z", id="offset to utc"),
    pytest.param("2020-06-01T12:00:00Z", "2020-06-01T12:00:00Z", id="trailing z"),
    pytest.param("not-a-date", "not-a-date", id="unparseable kept verbatim"),
]


@pytest.mark.parametrize(("value", "expected"), UTC_INSTANTS)
def test_to_utc_iso(value, expected) -> None:
    assert _to_utc_iso(value) == expected


MIDPOINTS = [
    pytest.param("2020-01-01", "2020-01-05", "2020-01-03T00:00:00Z", id="between start and end"),
    pytest.param("2020-01-01", None, "2020-01-01T00:00:00Z", id="start only"),
    pytest.param(None, "2020-01-06", "2020-01-06T00:00:00Z", id="end only"),
    pytest.param("not-a-date", "also-bad", "not-a-date", id="invalid falls back to start"),
]


@pytest.mark.parametrize(("start", "end", "expected"), MIDPOINTS)
def test_midpoint(start, end, expected) -> None:
    assert _midpoint(start, end) == expected


def test_midpoint_without_bounds_is_now() -> None:
    out = _midpoint(None, None)
    # Falls back to now in UTC, still shaped as a STAC datetime.
    assert out.endswith("Z")
    assert len(out) == len("2020-01-01T00:00:00Z")


UNIONS = [
    pytest.param(
        [
            {"bbox": [0.0, 0.0, 10.0, 10.0]},
            {"bbox": [-5.0, 2.0, 8.0, 20.0]},
            {"bbox": [3.0, -1.0, 4.0, 4.0]},
        ],
        [-5.0, -1.0, 10.0, 20.0],
        id="min and max over three items",
    ),
    pytest.param([{"bbox": [1.0, 2.0, 3.0, 4.0]}], [1.0, 2.0, 3.0, 4.0], id="single item"),
    pytest.param([{"properties": {}}, {"bbox": None}], None, id="no bbox"),
    pytest.param([], None, id="empty list"),
]


@pytest.mark.parametrize(("items", "expected"), UNIONS)
def test_union_bbox(items, expected) -> None:
    assert _union_bbox(items) == expected


def test_valid_item_passes() -> None:
    pytest.importorskip("pystac")
    ok, reasons = validate_item(build_stac_item(_make_context()))
    assert ok is True
    assert reasons == []


def test_invalid_item_reports_reasons() -> None:
    pytest.importorskip("pystac")
    # A bare dict missing every required STAC field must fail parsing.
    ok, reasons = validate_item({"type": "Feature"})
    assert ok is False
    assert reasons
    assert all(isinstance(r, str) for r in reasons)


def test_view_members_and_protocol() -> None:
    view = StacItemView()
    assert isinstance(view, ExportWriter)
    assert view.name == "stac"
    assert view.suffix == ".json"
    assert RUN_VIEW in view.writes
    assert view.natural == ()
    assert view.instants == "many"
    assert view.reprojects is False
    assert view.help


def test_view_refuses_variable_and_time_selectors(isolated_export_formats) -> None:
    from pydantic import ValidationError

    from hydromodpy.results.exporters.export_spec import ExportRequest

    isolated_export_formats.register(StacItemView)
    with pytest.raises(ValidationError, match='Write variables = "all"'):
        ExportRequest(variables="head", format="stac")
    with pytest.raises(ValidationError, match="time selects nothing"):
        ExportRequest(variables="all", format="stac", time="last")
