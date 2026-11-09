"""The two BRGM geology sources of the port, on a stubbed provider.

The contract suite checks the port declarations on every source; this table
checks what the two BRGM classes alone do: the file record they return over a
crop, the code column they carry, and the geology sources the registry serves,
which ``field.py`` reads to tell a BRGM map from a custom file.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pytest

pyproj = pytest.importorskip("pyproj")

from hydromodpy.core.exceptions import DataCapabilityError, DataRequestError  # noqa: E402
from hydromodpy.data.source.port import Extent, FetchRequest, Period  # noqa: E402
from hydromodpy.data.variables.geology.apis import brgm_1m, brgm_50k  # noqa: E402
from hydromodpy.data.variables.geology.apis.brgm_1m import BRGM_1M_URL, Brgm1m  # noqa: E402
from hydromodpy.data.variables.geology.apis.brgm_50k import BRGM_50K_ORIGIN, Brgm50k  # noqa: E402

BOX = (340000.0, 6800000.0, 350000.0, 6810000.0)
EXTENT = Extent(xmin=BOX[0], ymin=BOX[1], xmax=BOX[2], ymax=BOX[3], crs="EPSG:2154")
FOREIGN = Extent(xmin=-2.0, ymin=48.0, xmax=-1.5, ymax=48.4, crs="EPSG:4326")
PERIOD = Period(start=datetime(2020, 1, 1), end=datetime(2020, 2, 1))

CLASSES = [
    pytest.param(Brgm1m, brgm_1m, BRGM_1M_URL, id="brgm_1m"),
    pytest.param(Brgm50k, brgm_50k, BRGM_50K_ORIGIN, id="brgm_50k"),
]
# The pairs, for the cases that need no origin: a ParameterSet does not unpack.
PAIRS = [(Brgm1m, brgm_1m), (Brgm50k, brgm_50k)]


def _expected_box(extent: Extent) -> tuple[float, float, float, float]:
    """Reproject with pyproj directly, so the port is not its own reference."""
    transformer = pyproj.Transformer.from_crs(extent.crs, "EPSG:2154", always_xy=True)
    return tuple(transformer.transform_bounds(*extent.bbox))  # type: ignore[return-value]


def _gpkg(path: Path) -> Path:
    """A one-polygon Lambert-93 GeoPackage with the BRGM code column."""
    import geopandas as gpd
    from shapely.geometry import box

    gpd.GeoDataFrame(
        {"CODE_LEG": ["G1"]},
        geometry=[box(0.0, 0.0, 1.0, 1.0)],
        crs="EPSG:2154",
    ).to_file(path, driver="GPKG")
    return path


@pytest.mark.fast
@pytest.mark.parametrize("cls, module, origin", CLASSES)
def test_the_source_is_registered_under_its_section(cls, module, origin) -> None:
    from hydromodpy.data.source.registry import data_sources

    assert data_sources.get("geology", cls.source_id) is cls
    assert cls.section == "geology"
    assert origin  # the origin of the file record is a constant of the module


@pytest.mark.fast
@pytest.mark.parametrize("cls", [Brgm1m, Brgm50k])
def test_a_source_serves_the_hosts_of_the_schema_entry(cls) -> None:
    from hydromodpy.schema.sources import source_entry

    assert cls().hosts == source_entry(cls.source_id).hosts


@pytest.mark.fast
@pytest.mark.parametrize("cls, module, origin", CLASSES)
def test_a_crop_over_a_request_box_answers_a_file_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cls, module, origin
) -> None:
    asked: dict = {}
    fetch = getattr(module, f"fetch_{cls.source_id}")

    def fake(*, output_dir, bbox, code_field, **_kw):
        asked.update(bbox=bbox, code_field=code_field)
        return _gpkg(Path(output_dir) / f"{cls.source_id}.gpkg")

    monkeypatch.setattr(module, fetch.__name__, fake)

    result = cls().fetch(FetchRequest(out_dir=tmp_path, extent=EXTENT))

    [record] = result.files
    assert asked["bbox"] == BOX
    assert asked["code_field"] == "CODE_LEG"
    assert record.state == "raw"
    assert record.nodata is None
    assert record.origin == origin
    assert record.sha256 == hashlib.sha256(record.path.read_bytes()).hexdigest()
    assert result.variables == ("geology",)


@pytest.mark.fast
@pytest.mark.parametrize("cls, module", PAIRS)
def test_a_foreign_crs_box_reaches_the_provider_in_lambert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cls, module
) -> None:
    asked: dict = {}

    def fake(*, output_dir, bbox, code_field, **_kw):
        asked["bbox"] = bbox
        return _gpkg(Path(output_dir) / "map.gpkg")

    monkeypatch.setattr(module, f"fetch_{cls.source_id}", fake)

    result = cls().fetch(FetchRequest(out_dir=tmp_path, extent=FOREIGN))

    assert asked["bbox"] == pytest.approx(_expected_box(FOREIGN), rel=0, abs=1e-6)
    assert result.extent is not None and result.extent.crs == "EPSG:2154"


@pytest.mark.fast
@pytest.mark.parametrize("cls", [Brgm1m, Brgm50k])
def test_the_refusals_of_the_port_are_made_before_the_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cls
) -> None:
    module = brgm_1m if cls is Brgm1m else brgm_50k

    def fail(**_kwargs):
        raise AssertionError("the provider was reached before the request was refused")

    monkeypatch.setattr(module, f"fetch_{cls.source_id}", fail)

    with pytest.raises(DataCapabilityError, match="does not select by"):
        cls().fetch(FetchRequest(out_dir=tmp_path, station_ids=("X1",)))
    with pytest.raises(DataCapabilityError, match="no time axis"):
        cls().fetch(FetchRequest(out_dir=tmp_path, extent=EXTENT, period=PERIOD))


@pytest.mark.fast
def test_the_registered_geology_sources_are_the_brgm_maps() -> None:
    """``field.py`` reads this to tell a BRGM map from a user's own file."""
    from hydromodpy.data.variables.geology.field import brgm_sources

    assert brgm_sources() == frozenset({"brgm_1m", "brgm_50k"})


@pytest.mark.fast
def test_the_code_column_of_the_field_comes_from_the_registry_reading(
    tmp_path: Path,
) -> None:
    """A record from a registered source reads ``CODE_LEG``, a custom one its own column."""
    from hydromodpy.data.variables.geology.field import _code_field

    record = type("R", (), {"source": "brgm_50k"})()
    config = type("C", (), {"sources": []})()
    assert _code_field(record, config) == "CODE_LEG"

    record.source = "file"
    config.sources = [type("S", (), {"source": "file", "code_field": "CODE_B"})()]
    assert _code_field(record, config) == "CODE_B"


@pytest.mark.fast
def test_a_crop_that_holds_no_feature_is_refused_by_the_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kept from the provider level: an empty crop is the provider's refusal, not a file."""

    def fake(*, output_dir, bbox, code_field, **_kw):
        raise ValueError("No geology feature from the 1M map intersects the requested bbox")

    monkeypatch.setattr(brgm_1m, "fetch_brgm_1m", fake)

    with pytest.raises(ValueError, match="intersects"):
        Brgm1m().fetch(FetchRequest(out_dir=tmp_path, extent=EXTENT))
