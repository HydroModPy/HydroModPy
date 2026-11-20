"""Header of each input file, local or by its final URL, read without the network.

``read_input_headers`` holds a DEM to the contract (projected CRS in metres, square pixel of 1 to
250 m, no rotation, an outlet inside the raster on a cell with a value) and asks other rasters
to open and declare a CRS. Sizes are in metres.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import rasterio
import rasterio.env
from rasterio.transform import Affine

from hydromodpy.config.input_headers import DEM_ROLE, read_input_headers
from hydromodpy.core.io import fetch
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.data.variables.dem.config import FileDemSource, UrlDemSource
from hydromodpy.data.variables.user_rasters import FileSubstratumSource

X0, Y0, SIZE, CELLS = 1000.0, 5000.0, 25.0, 20
INSIDE = (X0 + 12.5 + SIZE * 5, Y0 - 12.5 - SIZE * 5)
FINAL_URL = "https://cdn.example.org/final/dem.tif"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("a header check asked the network")

    monkeypatch.setattr(fetch.HTTPClient, "request", refuse)


def write_raster(
    path: Path,
    *,
    crs: str | None = "EPSG:2154",
    x_size: float = SIZE,
    y_size: float | None = None,
    nodata: float | None = -9999.0,
    hole: tuple[int, int] | None = None,
    turn: float = 0.0,
) -> Path:
    """Write a small GeoTIFF whose header is the one a case asks for."""
    y_size = x_size if y_size is None else y_size
    data = np.ones((CELLS, CELLS), dtype="float32")
    if hole is not None:
        data[hole] = nodata if nodata is not None else np.nan
    transform = Affine(x_size, turn, X0, turn, -y_size, Y0)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=CELLS,
        width=CELLS,
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=nodata,
    ) as target:
        target.write(data, 1)
    return path


def document(
    *dems: Any, outlet: tuple[float, float] | None = INSIDE, crs_project: str | None = "EPSG:2154"
) -> SimpleNamespace:
    """Return the validated sections the check reads: the DEM sources and the outlet."""
    catchment = None if outlet is None else SimpleNamespace(x_outlet=outlet[0], y_outlet=outlet[1])
    return SimpleNamespace(
        data=SimpleNamespace(dem=SimpleNamespace(sources=list(dems))),
        geographic=SimpleNamespace(crs_project=crs_project, catchment=catchment),
    )


def summary(found) -> list[tuple[str, str, str]]:
    return [(item.path, item.code, item.severity) for item in found]


DEM_PATH = "data.dem.sources[0].path"

LOCAL_CASES = [
    pytest.param({}, [], "", id="the_contract_holds"),
    pytest.param(
        {"crs": "EPSG:4326", "x_size": 0.0003, "outlet": None},
        [(DEM_PATH, "input_header", "error")],
        "not a projected CRS in metres",
        id="a_geographic_crs",
    ),
    pytest.param(
        {"crs": None},
        [(DEM_PATH, "input_header", "error")],
        "no CRS",
        id="no_crs_declared",
    ),
    pytest.param(
        {"x_size": 25.0, "y_size": 30.0},
        [(DEM_PATH, "input_header", "error")],
        "not square",
        id="a_pixel_that_is_not_square",
    ),
    pytest.param(
        {"x_size": 500.0, "outlet": None},
        [(DEM_PATH, "input_header", "error")],
        "outside [1.0, 250.0]",
        id="a_resolution_above_250_m",
    ),
    pytest.param(
        {"x_size": 0.5, "outlet": None},
        [(DEM_PATH, "input_header", "error")],
        "outside [1.0, 250.0]",
        id="a_resolution_below_1_m",
    ),
    pytest.param(
        {"turn": 2.5},
        [(DEM_PATH, "input_header", "error")],
        "rotated",
        id="a_rotated_grid",
    ),
    pytest.param(
        {"nodata": None},
        [(DEM_PATH, "input_header", "warning")],
        "no nodata value",
        id="no_nodata_value_is_a_warning",
    ),
    pytest.param(
        {"hole": (5, 5)},
        [(DEM_PATH, "input_header", "error")],
        "holds no value",
        id="an_outlet_on_a_cell_without_value",
    ),
]


@pytest.mark.parametrize(("raster", "expected", "said"), LOCAL_CASES)
def test_local_dem_header(
    tmp_path: Path, raster: dict[str, Any], expected: list, said: str
) -> None:
    outlet = raster.pop("outlet", INSIDE)
    path = write_raster(tmp_path / "dem.tif", **raster)

    found = read_input_headers(
        document(FileDemSource(path=path), outlet=outlet), base=tmp_path, bounds=None
    )

    assert summary(found) == expected
    assert all(said in item.detail for item in found)


def test_outlet_outside_the_raster(tmp_path: Path) -> None:
    path = write_raster(tmp_path / "dem.tif")

    found = read_input_headers(
        document(FileDemSource(path=path), outlet=(9000.0, 9000.0)), base=tmp_path
    )

    assert summary(found) == [(DEM_PATH, "input_header", "error")]
    assert "falls outside" in found[0].detail


def test_outlet_needs_a_single_dem(tmp_path: Path) -> None:
    first = write_raster(tmp_path / "a.tif")
    second = write_raster(tmp_path / "b.tif")

    found = read_input_headers(
        document(FileDemSource(path=first), FileDemSource(path=second), outlet=(9000.0, 9000.0)),
        base=tmp_path,
    )

    assert found == []


def test_missing_file(tmp_path: Path) -> None:
    found = read_input_headers(
        document(FileDemSource(path=tmp_path / "gone.tif"), outlet=None), base=tmp_path
    )

    assert summary(found) == [(DEM_PATH, "input_unreachable", "error")]
    assert "does not exist" in found[0].detail


def test_file_that_is_not_a_raster(tmp_path: Path) -> None:
    path = tmp_path / "dem.tif"
    path.write_bytes(b"not a raster")

    found = read_input_headers(document(FileDemSource(path=path), outlet=None), base=tmp_path)

    assert summary(found) == [(DEM_PATH, "input_unreachable", "error")]
    assert "does not open as a raster" in found[0].detail


def test_directory_only_has_to_exist(tmp_path: Path) -> None:
    (tmp_path / "tiles").mkdir()

    found = read_input_headers(
        document(FileDemSource(path=tmp_path / "tiles"), outlet=None), base=tmp_path
    )

    assert found == []


def test_path_outside_the_allowed_roots(tmp_path: Path) -> None:
    path = write_raster(tmp_path / "dem.tif")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    found = read_input_headers(
        document(FileDemSource(path=path)), base=tmp_path, bounds=Bounds(allowed_roots=(elsewhere,))
    )

    assert summary(found) == [(DEM_PATH, "input_unreachable", "error")]
    assert "outside the roots" in found[0].detail


@pytest.mark.parametrize(
    ("crs", "default_crs", "expected"),
    [
        ("EPSG:2154", "", []),
        (None, "", [("data.substratum.sources[0].path", "input_header", "error")]),
        (None, "EPSG:2154", []),
    ],
    ids=["declared", "undeclared", "undeclared_with_a_default"],
)
def test_other_raster_declares_a_crs(
    tmp_path: Path, crs: str | None, default_crs: str, expected: list
) -> None:
    path = write_raster(tmp_path / "substratum.tif", crs=crs, x_size=1000.0)
    source = FileSubstratumSource.model_construct(path=path, source="file", default_crs=default_crs)
    sections = SimpleNamespace(data=SimpleNamespace(substratum=SimpleNamespace(sources=[source])))

    found = read_input_headers(sections, base=tmp_path)

    assert summary(found) == expected
    assert all("declares no CRS" in item.detail for item in found)


URL_PATH = "data.dem.sources[0].url"


def spy_on_the_open(monkeypatch: pytest.MonkeyPatch, local: Path) -> dict[str, Any]:
    """Record what GDAL is asked to open and the options of its ``Env``, serve a local file."""
    seen: dict[str, Any] = {"opened": [], "options": []}
    real_open = rasterio.open

    def fake_open(location: str, *args: Any, **kwargs: Any) -> Any:
        seen["opened"].append(location)
        seen["options"].append(rasterio.env.get_gdal_config("GDAL_DISABLE_READDIR_ON_OPEN"))
        return real_open(local, *args, **kwargs)

    monkeypatch.setattr(rasterio, "open", fake_open)
    return seen


def test_url_without_bounds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = spy_on_the_open(monkeypatch, write_raster(tmp_path / "dem.tif"))

    found = read_input_headers(
        document(UrlDemSource(url=FINAL_URL), outlet=None), base=tmp_path, bounds=None
    )

    assert summary(found) == [(URL_PATH, "input_unreachable", "error")]
    assert "bounds" in found[0].detail
    assert seen["opened"] == []


def test_host_the_bounds_refuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = spy_on_the_open(monkeypatch, write_raster(tmp_path / "dem.tif"))

    found = read_input_headers(
        document(UrlDemSource(url=FINAL_URL), outlet=None),
        base=tmp_path,
        bounds=Bounds(allowed_hosts=frozenset({"other.example.org"})),
    )

    assert summary(found) == [(URL_PATH, "input_unreachable", "error")]
    assert "cdn.example.org" in found[0].detail
    assert seen["opened"] == []


def test_gdal_gets_the_final_url_in_a_scoped_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = spy_on_the_open(monkeypatch, write_raster(tmp_path / "dem.tif"))
    resolved: list[tuple[str, Bounds | None]] = []

    def head_only(url: str, bounds: Bounds | None = None, *_args: Any, **_kwargs: Any):
        resolved.append((url, bounds))
        return fetch.ResolvedUrl(url=FINAL_URL)

    monkeypatch.setattr(fetch, "resolve_final_url", head_only)
    bounds = Bounds(allowed_hosts=frozenset({"start.example.org", "cdn.example.org"}))

    found = read_input_headers(
        document(UrlDemSource(url="https://start.example.org/dem.tif")),
        base=tmp_path,
        bounds=bounds,
    )

    assert found == []
    assert resolved == [("https://start.example.org/dem.tif", bounds)]
    assert seen["opened"] == [f"/vsicurl/{FINAL_URL}"]
    assert seen["options"] == ["EMPTY_DIR"]
    assert rasterio.env.get_gdal_config("GDAL_DISABLE_READDIR_ON_OPEN") is None


def test_url_that_does_not_answer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hydromodpy.core.exceptions import NetworkError

    def down(url: str, *_args: Any, **_kwargs: Any) -> None:
        raise NetworkError(f"Could not resolve host for {url}", url=url)

    monkeypatch.setattr(fetch, "resolve_final_url", down)

    found = read_input_headers(
        document(UrlDemSource(url=FINAL_URL), outlet=None), base=tmp_path, bounds=Bounds()
    )

    assert summary(found) == [(URL_PATH, "input_unreachable", "error")]
    assert "Could not resolve host" in found[0].detail


def test_url_to_a_non_raster_only_has_to_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = spy_on_the_open(monkeypatch, write_raster(tmp_path / "dem.tif"))
    monkeypatch.setattr(
        fetch, "resolve_final_url", lambda url, *_a, **_k: fetch.ResolvedUrl(url=url)
    )

    found = read_input_headers(
        document(UrlDemSource(url="https://data.example.org/dem.csv"), outlet=None),
        base=tmp_path,
        bounds=Bounds(),
    )

    assert found == []
    assert seen["opened"] == []


def test_dem_role() -> None:
    marker = next(
        meta for meta in FileDemSource.model_fields["path"].metadata if isinstance(meta, InputFile)
    )

    assert marker.role == DEM_ROLE
