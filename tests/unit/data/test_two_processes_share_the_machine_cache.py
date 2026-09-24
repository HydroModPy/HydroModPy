"""Two processes that fetch the same DEM or geology archive both succeed.

The machine cache under ``~/.cache/hydromodpy`` is shared by every run on the
host. Each test starts two real processes on the same department, with a
provider slow enough for them to overlap, and checks that both end with a
complete, readable file, that the provider was called once, and that no staged
or partial file is left behind.
"""

from __future__ import annotations

import multiprocessing
import time
import traceback
import urllib.request
import zipfile
from pathlib import Path

import pytest

from hydromodpy.data.variables.dem.apis import _bdalti_archive_index, ign_dem_fr
from hydromodpy.data.variables.dem.apis.geoplateforme_download import (
    DownloadFile,
    download_file,
)
from hydromodpy.data.variables.geology.apis import brgm_1m, brgm_50k

_PAYLOAD = bytes(range(256)) * 64
_CHUNKS = 16


def _rendezvous(worker, arguments: tuple, barrier, results) -> None:
    barrier.wait(timeout=120)
    try:
        results.put(("ok", worker(arguments)))
    except BaseException:
        results.put(("error", traceback.format_exc()))


def _run_twice(worker, arguments: tuple) -> list:
    """Run ``worker`` in two processes released together once both are up."""
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    results = ctx.Queue()
    processes = [
        ctx.Process(target=_rendezvous, args=(worker, arguments, barrier, results))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    outcomes = [results.get(timeout=180) for _ in processes]
    for process in processes:
        process.join(timeout=60)
    errors = [detail for status, detail in outcomes if status == "error"]
    assert errors == []
    return [detail for _, detail in outcomes]


def _count_call(calls: Path) -> None:
    with open(calls, "a", encoding="utf-8") as handle:
        handle.write("call\n")


def _calls(calls: Path) -> int:
    return len(calls.read_text(encoding="utf-8").splitlines()) if calls.exists() else 0


def _leftovers(root: Path) -> list[Path]:
    staged = (".tmp-", "ign_dem_", "_brgm_1m_extract_")
    return [
        p
        for p in root.rglob("*")
        if any(token in p.name for token in staged) or p.name.endswith(".part")
    ]


class _SlowResponse:
    status_code = 200

    def iter_content(self, chunk_size: int):
        del chunk_size
        step = len(_PAYLOAD) // _CHUNKS
        for index in range(_CHUNKS):
            time.sleep(0.02)
            yield _PAYLOAD[index * step : (index + 1) * step]


class _SlowSession:
    def __init__(self, calls: Path) -> None:
        self.calls = calls

    def get(self, url: str, **kwargs):
        del url, kwargs
        _count_call(self.calls)
        return _SlowResponse()


def _download_worker(arguments: tuple) -> str:
    destination, calls = arguments
    file = DownloadFile(
        resource_name="BDALTI",
        subresource_name="sub",
        file_name="archive.7z",
        url="https://data.geopf.fr/telechargement/download/BDALTI/sub/archive.7z",
    )
    return str(download_file(file, destination, session=_SlowSession(calls)))


def test_two_processes_download_one_archive_once(tmp_path: Path) -> None:
    calls = tmp_path / "calls.log"
    destination = tmp_path / "raw"

    targets = _run_twice(_download_worker, (destination, calls))

    assert targets[0] == targets[1]
    assert Path(targets[0]).read_bytes() == _PAYLOAD
    assert _calls(calls) == 1
    assert _leftovers(destination) == []


_ASC_TILE = (
    "\n".join(
        [
            "ncols 3",
            "nrows 3",
            "xllcorner 100",
            "yllcorner 100",
            "cellsize 25",
            "NODATA_value -99999",
            "1 2 3",
            "4 5 6",
            "7 8 9",
        ]
    )
    + "\n"
)


def _dem_worker(arguments: tuple) -> str:
    output_dir, archive, calls = arguments

    def fake_download(**kwargs):
        del kwargs
        return [Path(archive)]

    def slow_extract(archive_path, destination):
        _count_call(calls)
        asc_dir = Path(destination) / Path(archive_path).stem
        asc_dir.mkdir(parents=True)
        time.sleep(0.3)
        (asc_dir / "tile.asc").write_text(_ASC_TILE, encoding="ascii")

    ign_dem_fr.download_ign_dem_departments = fake_download
    _bdalti_archive_index._extract_7z = slow_extract
    return str(
        ign_dem_fr.fetch_ign_dem(
            output_dir=output_dir,
            bbox=(100.0, 100.0, 175.0, 175.0),
            departments=["29"],
        )
    )


def test_two_processes_assemble_one_dem(tmp_path: Path) -> None:
    rasterio = pytest.importorskip("rasterio")
    archive = tmp_path / "raw" / "D029" / "fixture.7z"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"archive")
    output_dir = tmp_path / "dem"
    calls = tmp_path / "calls.log"

    rasters = _run_twice(_dem_worker, (output_dir, archive, calls))

    assert rasters[0] == rasters[1]
    with rasterio.open(rasters[0]) as dataset:
        assert dataset.read(1)[1, 1] == 5
    extracted = sorted((output_dir / "extracted_ign").iterdir())
    assert [p.name for p in extracted if p.is_dir()] == [
        p.name for p in extracted if (p / ".extracted").is_file()
    ]
    assert len([p for p in extracted if p.is_dir()]) == 1
    assert _calls(calls) == 1
    assert _leftovers(output_dir) == []


def _write_geology_zip(zip_path: Path) -> None:
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import box

    shp_dir = zip_path.parent / "shp"
    shp_dir.mkdir()
    gdf = gpd.GeoDataFrame(
        {"CODE_LEG": [1, 2]},
        geometry=[box(0, 0, 100, 100), box(100, 0, 200, 100)],
        crs="EPSG:2154",
    )
    gdf.to_file(shp_dir / "GEO050K_HARM_029_S_FGEOL_2154.shp")
    with zipfile.ZipFile(zip_path, "w") as archive:
        for member in shp_dir.iterdir():
            archive.write(member, arcname=f"GEO050K_HARM_029/{member.name}")


def _slow_copy(source: Path, target: str, calls: Path) -> None:
    _count_call(calls)
    data = source.read_bytes()
    step = max(1, len(data) // _CHUNKS)
    with open(target, "wb") as handle:
        for start in range(0, len(data), step):
            time.sleep(0.02)
            handle.write(data[start : start + step])


def _brgm_50k_worker(arguments: tuple) -> str | None:
    cache_dir, source_zip, calls = arguments
    urllib.request.urlretrieve = lambda url, target: _slow_copy(Path(source_zip), target, calls)
    path = brgm_50k._download_department("29", cache_dir=Path(cache_dir))
    return None if path is None else str(path)


def test_two_processes_convert_one_brgm_department(tmp_path: Path) -> None:
    gpd = pytest.importorskip("geopandas")
    source_zip = tmp_path / "source" / "department.zip"
    source_zip.parent.mkdir()
    _write_geology_zip(source_zip)
    cache_dir = tmp_path / "departments_50k"
    cache_dir.mkdir()
    calls = tmp_path / "calls.log"

    paths = _run_twice(_brgm_50k_worker, (cache_dir, source_zip, calls))

    assert paths[0] is not None and paths[0] == paths[1]
    assert sorted(gpd.read_file(paths[0])["CODE_LEG"]) == [1, 2]
    with zipfile.ZipFile(cache_dir / "GEO050K_HARM_029.zip") as archive:
        assert archive.testzip() is None
    assert _calls(calls) == 1
    assert _leftovers(cache_dir) == []


def _brgm_1m_worker(arguments: tuple) -> str:
    output_dir, source_zip, calls = arguments
    urllib.request.urlretrieve = lambda url, target, reporthook=None: _slow_copy(
        Path(source_zip), target, calls
    )
    return str(brgm_1m.fetch_brgm_1m(output_dir=Path(output_dir)))


def test_two_processes_convert_one_national_map(tmp_path: Path) -> None:
    gpd = pytest.importorskip("geopandas")
    source_zip = tmp_path / "source" / "FR_vecteur.zip"
    source_zip.parent.mkdir()
    _write_geology_zip(source_zip)
    output_dir = tmp_path / "geology"
    calls = tmp_path / "calls.log"

    paths = _run_twice(_brgm_1m_worker, (output_dir, source_zip, calls))

    assert paths[0] == paths[1]
    assert sorted(gpd.read_file(paths[0])["CODE_LEG"]) == [1, 2]
    assert not any(p.name.startswith("_brgm_1m_extract") for p in output_dir.iterdir())
    assert _calls(calls) == 1
    assert _leftovers(output_dir) == []
