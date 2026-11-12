"""The DEM source of the port, on a stubbed assembler.

The contract suite checks the port declarations on every source; this table
checks what the IGN class alone does: the options its section binds, the file
record it returns and the nodata it reads from the raster's header. The
assembled products themselves (BD ALTI archives, RGE ALTI tiles) are covered by
``test_geoplateforme_ign_dem.py`` and ``test_rge_alti_wms.py``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

pyproj = pytest.importorskip("pyproj")
rasterio = pytest.importorskip("rasterio")

from hydromodpy.core.exceptions import DataCapabilityError, DataRequestError  # noqa: E402
from hydromodpy.data.source.port import Extent, FetchRequest, Period  # noqa: E402
from hydromodpy.data.variables.dem.apis import ign_dem_fr  # noqa: E402
from hydromodpy.data.variables.dem.apis.ign_dem_fr import (  # noqa: E402
    GEOPLATEFORME_ORIGIN,
    IgnGeoplateformeDem,
)

BOX = (340000.0, 6800000.0, 350000.0, 6810000.0)
EXTENT = Extent(xmin=BOX[0], ymin=BOX[1], xmax=BOX[2], ymax=BOX[3], crs="EPSG:2154")
FOREIGN = Extent(xmin=-2.0, ymin=48.0, xmax=-1.5, ymax=48.4, crs="EPSG:4326")


def _expected_box(extent: Extent) -> tuple[float, float, float, float]:
    """Reproject with pyproj directly, so the port is not its own reference."""
    transformer = pyproj.Transformer.from_crs(extent.crs, "EPSG:2154", always_xy=True)
    return tuple(transformer.transform_bounds(*extent.bbox))  # type: ignore[return-value]


def _raster(path: Path, *, nodata: float = -9999.0) -> Path:
    """A one-pixel Lambert-93 GeoTIFF declaring *nodata*."""
    import numpy as np
    from rasterio.transform import from_origin

    profile = {
        "driver": "GTiff",
        "height": 1,
        "width": 1,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:2154",
        "transform": from_origin(BOX[0], BOX[3], 5.0, 5.0),
        "nodata": nodata,
    }
    with rasterio.open(str(path), "w", **profile) as dst:
        dst.write(np.full((1, 1), 17.0, dtype="float32"), 1)
    return path


@pytest.mark.fast
def test_a_foreign_crs_box_reaches_the_assembler_in_lambert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: dict = {}

    def fake(*, output_dir, bbox, **kwargs):
        asked.update(bbox=bbox, **kwargs)
        return _raster(Path(output_dir) / "dem.tif")

    monkeypatch.setattr(ign_dem_fr, "fetch_ign_dem", fake)

    result = IgnGeoplateformeDem(dataset="rge-alti").fetch(
        FetchRequest(out_dir=tmp_path, extent=FOREIGN)
    )

    assert asked["bbox"] == pytest.approx(_expected_box(FOREIGN), rel=0, abs=1e-6)
    assert result.extent is not None and result.extent.crs == "EPSG:2154"


@pytest.mark.fast
def test_the_file_record_carries_the_header_nodata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict = {}

    def fake(*, output_dir, bbox, **kwargs):
        seen.update(output_dir=output_dir, bbox=bbox)
        return _raster(Path(output_dir) / "dem_25m.tif")

    monkeypatch.setattr(ign_dem_fr, "fetch_ign_dem", fake)

    result = IgnGeoplateformeDem().fetch(FetchRequest(out_dir=tmp_path, extent=EXTENT))

    [record] = result.files
    assert record.path == seen["output_dir"] / "dem_25m.tif"  # type: ignore[union-attr]
    assert record.state == "raw"
    assert record.nodata == -9999.0
    assert record.origin == GEOPLATEFORME_ORIGIN
    assert record.sha256 == hashlib.sha256(record.path.read_bytes()).hexdigest()
    assert result.variables == ("dem",)


@pytest.mark.fast
def test_the_refusals_of_the_port_are_made_before_the_assembler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(**_kwargs):
        raise AssertionError("the assembler was reached before the request was refused")

    monkeypatch.setattr(ign_dem_fr, "fetch_ign_dem", fail)

    with pytest.raises(DataCapabilityError, match="does not select by"):
        IgnGeoplateformeDem().fetch(FetchRequest(out_dir=tmp_path, station_ids=("X1",)))
    with pytest.raises(DataCapabilityError, match="no time axis"):
        from datetime import datetime

        IgnGeoplateformeDem().fetch(
            FetchRequest(
                out_dir=tmp_path,
                extent=EXTENT,
                period=Period(start=datetime(2020, 1, 1), end=datetime(2020, 2, 1)),
            )
        )


@pytest.mark.fast
def test_a_dataset_nobody_assembles_is_refused_by_the_constructor() -> None:
    with pytest.raises((ValueError, DataRequestError)):
        IgnGeoplateformeDem(dataset="srtm")
