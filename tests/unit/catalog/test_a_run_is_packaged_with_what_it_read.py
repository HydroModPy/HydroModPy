"""The install index of a run lists every file it read, where it goes, and how it is served.

Each file is named by its destination relative to the workspace, with its
variable, provider, request, licence and the digest of its sidecar. A station
series brings its registry row, a file a provider delivered the row of the
data cache that serves it, the run its ``[site]``. A declared folder is never
taken whole: a station the run did not read stays out.
"""

from __future__ import annotations

from hydromodpy.core.payload import sidecar_name, stored_name
from hydromodpy.project.exchange.share import run_bundle
from tests.unit.catalog._shared_run import (
    CUSTOM_FILE,
    HUBEAU_FILE,
    UNREAD_FILE,
    make_shared_run,
    sha256_of,
)


def test_the_index_lists_every_file_the_run_read_and_nothing_else(tmp_path) -> None:
    run_dir = make_shared_run(tmp_path / "ws")

    bundle = run_bundle(run_dir, project_root=run_dir.parent.parent)

    dests = [item.dest for item in bundle.index.files]
    assert dests == [
        "data/dem/dem.tif",
        f"data/hydrometry/{CUSTOM_FILE}",
        f"data/hydrometry/{HUBEAU_FILE}",
    ]
    assert not any(UNREAD_FILE in dest for dest in dests)
    dem = bundle.index.file_at("data/dem/dem.tif")
    assert (dem.variable, dem.provider, dem.license) == ("dem", "custom", "LicenseRef-undetermined")
    for item in bundle.index.files:
        assert bundle.blobs[stored_name(item.sha256, item.dest)].is_file()


def test_a_delivered_file_brings_its_sidecar_and_its_data_cache_row(tmp_path) -> None:
    workspace = tmp_path / "ws"
    run_dir = make_shared_run(workspace)
    sidecar = workspace / "data" / "hydrometry" / f"{HUBEAU_FILE}.json"

    bundle = run_bundle(run_dir, project_root=run_dir.parent.parent)

    item = bundle.index.file_at(f"data/hydrometry/{HUBEAU_FILE}")
    assert (item.variable, item.provider, item.license) == ("hydrometry", "hubeau", "etalab-2.0")
    assert item.request == {"station": "J0014010", "period": ["2000-01-01T00:00:00", None]}
    assert item.sidecar_sha256 == sha256_of(sidecar)
    assert bundle.blobs[sidecar_name(item.sidecar_sha256)] == sidecar
    assert item.cache["source"] == "hubeau"
    assert item.cache["station_id"] == "J0014010"
    assert item.cache["frequency"] == "D"
    assert item.cache["bbox"] == [-1.19645, 48.37558, -1.19645, 48.37558]
    assert item.cache["fetch_metadata"] == {
        "asked_window": ["2000-01-01T00:00:00", "2002-12-31T00:00:00"]
    }
    assert bundle.index.file_at(f"data/hydrometry/{CUSTOM_FILE}").cache is None


def test_each_station_series_brings_its_registry_row_and_the_run_its_site(tmp_path) -> None:
    run_dir = make_shared_run(tmp_path / "ws")

    bundle = run_bundle(run_dir, project_root=run_dir.parent.parent)

    rows = {(station.dest, station.id): dict(station.row) for station in bundle.index.stations}
    assert set(rows) == {
        ("data/hydrometry/hydrometry_custom_LOC.csv", "NANCON"),
        ("data/hydrometry/hydrometry_hubeau_LOC.csv", "J0014010"),
    }
    assert rows[("data/hydrometry/hydrometry_custom_LOC.csv", "NANCON")]["unit"] == "m3/s"
    (site,) = bundle.index.sites
    assert (site.site, site.gauge, site.uri) == ("J0014010", "J0014010", "hubeau:J0014010")
